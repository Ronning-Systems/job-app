"""
Agent Service Module

Provides integration with agent prompts for:
- ATS Expert Agent (resume optimization)
- Resume Generator Agent (creating resumes)
- Technical Hiring Manager Agent (technical evaluation)
- Job Description Archiver Agent (parsing job descriptions)
"""

import os
import json
import logging
import httpx
import base64
import io
from typing import Dict, Any, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text_from_file(file_content_b64: str, filename: str) -> str:
    """Extract text from PDF or DOCX file content (base64 encoded)"""
    try:
        b64_data = (
            file_content_b64.split(",")[1]
            if "," in file_content_b64
            else file_content_b64
        )
        file_bytes = base64.b64decode(b64_data)

        file_ext = filename.lower().split(".")[-1]

        if file_ext == "pdf":
            return _extract_pdf_text(file_bytes)
        elif file_ext in ["docx", "doc"]:
            return _extract_docx_text(file_bytes)
        else:
            logger.warning(f"Unsupported file type: {file_ext}")
            b64_data = file_content_b64.split(",")[1]
            decoded = base64.b64decode(b64_data).decode("utf-8", errors="ignore")
            return decoded
    except Exception as e:
        logger.error(f"Failed to extract text from {filename}: {e}")
        return ""


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from PDF bytes using multiple methods"""
    text = ""

    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        if text.strip():
            return text.strip()
    except Exception as e:
        logger.debug(f"pdfplumber failed: {e}")

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        logger.error(f"pypdf failed: {e}")
        return ""


def _extract_docx_text(file_bytes: bytes) -> str:
    """Extract text from DOCX bytes"""
    try:
        from docx import Document

        doc = Document(io.BytesIO(file_bytes))
        return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
    except Exception as e:
        logger.error(f"python-docx failed: {e}")
        return ""


class OllamaAgent:
    """Base class for Ollama-powered agents (local or cloud)"""

    def __init__(self):
        self.base_url = os.getenv("MODEL_ENDPOINT", "http://localhost:11434").rstrip(
            "/"
        )
        self.model = os.getenv("MODEL_AGENTS", "llama3.2:latest")
        self.generation_model = os.getenv("MODEL_GENERATION") or os.getenv("MODEL_AGENTS", "llama3.2:latest")
        self.api_key = os.getenv("OLLAMA_API_KEY", "")
        self.is_cloud = "ollama.com" in self.base_url
        self.timeout = 240.0

    async def generate(
        self, prompt: str, system: Optional[str] = None, temperature: float = 0.3, model: Optional[str] = None
    ) -> str:
        """Generate text using Ollama (local or cloud)"""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers["Content-Type"] = "application/json"

        model_name = model or self.model

        if self.is_cloud:
            # Ollama Cloud: OpenAI-compatible /v1/chat/completions
            url = f"{self.base_url}/v1/chat/completions"
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 32000,
            }
        else:
            # Local Ollama: /api/generate
            url = f"{self.base_url}/api/generate"
            payload = {
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": 32000},
            }
            if system:
                payload["system"] = system

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            if self.is_cloud:
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                return data.get("response", "")


class AgentService:
    """Service for loading and executing agent prompts"""

    def __init__(self):
        self.agents_dir = Path(__file__).parent.parent / "agents"
        self.prompts_cache = {}
        self.ollama = OllamaAgent()

    def _load_agent_prompt(self, agent_name: str) -> str:
        """Load an agent prompt from file"""
        if agent_name in self.prompts_cache:
            return self.prompts_cache[agent_name]

        agent_file = self.agents_dir / f"{agent_name}.md"
        if not agent_file.exists():
            # Try alternative names
            alt_names = {
                "ats-expert": "ats-expert",
                "resume-generator": "resume-generator",
                "technical-hiring-manager": "tech-hiring-manager",
                "tech-hiring-manager": "tech-hiring-manager",
                "job-archiver": "job-archiver",
            }
            agent_file = self.agents_dir / f"{alt_names.get(agent_name, agent_name)}.md"

        if agent_file.exists():
            with open(agent_file, "r") as f:
                prompt = f.read()
                self.prompts_cache[agent_name] = prompt
                return prompt

        return ""

    async def get_ats_expert_analysis(
        self, resume_text: str, job_description: str
    ) -> Dict[str, Any]:
        """
        Get ATS analysis from the ATS Expert Agent via Ollama
        """
        agent_prompt = self._load_agent_prompt("ats-expert")

        prompt = f"""{agent_prompt}

Analyze this resume against the job description and provide ATS analysis.

RESUME:
{resume_text[:16000]}

JOB DESCRIPTION:
{job_description[:16000]}

Respond with ONLY a JSON object in this format:
{{
    "parse_score": 8,
    "keyword_match": 7,
    "search_relevance": 8,
    "overall_score": 7.5,
    "critical_issues": ["issue1", "issue2"],
    "recommendations": ["rec1", "rec2"],
    "keywords_found": ["kw1", "kw2"],
    "keywords_missing": ["missing1", "missing2"]
}}"""

        try:
            response = await self.ollama.generate(prompt, temperature=0.3)
            response = response.strip()

            # Extract JSON from response
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            result = json.loads(response.strip())
            return result

        except json.JSONDecodeError:
            return {
                "parse_score": 7,
                "keyword_match": 6,
                "search_relevance": 7,
                "overall_score": 6.5,
                "critical_issues": ["Could not parse LLM response"],
                "recommendations": ["Review resume manually"],
                "keywords_found": [],
                "keywords_missing": [],
            }
        except Exception as e:
            return {"error": str(e)}

    async def get_technical_fit_analysis(
        self, resume_text: str, job_requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get technical fit analysis from Technical Hiring Manager Agent via Ollama
        """
        agent_prompt = self._load_agent_prompt("technical-hiring-manager")

        must_have = job_requirements.get("must_have", [])
        nice_to_have = job_requirements.get("nice_to_have", [])

        must_have_str = (
            "\n".join([f"- {s}" for s in must_have]) if must_have else "None specified"
        )
        nice_have_str = (
            "\n".join([f"- {s}" for s in nice_to_have])
            if nice_to_have
            else "None specified"
        )

        prompt = f"""{agent_prompt}

Evaluate this candidate's technical fit for the position.

RESUME:
{resume_text[:16000]}

REQUIRED SKILLS:
{must_have_str}

PREFERRED SKILLS:
{nice_have_str}

Respond with ONLY a JSON object in this format:
{{
    "skill_match": 8,
    "experience_relevance": 7,
    "leadership_fit": 6,
    "overall_technical_fit": 7,
    "strengths": ["strength1", "strength2"],
    "gaps": ["gap1", "gap2"],
    "recommendations": ["rec1", "rec2"]
}}"""

        try:
            response = await self.ollama.generate(prompt, temperature=0.3)
            response = response.strip()

            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            result = json.loads(response.strip())
            return result

        except json.JSONDecodeError:
            return {
                "skill_match": 6,
                "experience_relevance": 6,
                "leadership_fit": 5,
                "overall_technical_fit": 6,
                "strengths": ["Could not parse LLM response"],
                "gaps": ["Parse error"],
                "recommendations": ["Review manually"],
            }
        except Exception as e:
            return {"error": str(e)}

    async def generate_resume(
        self,
        user_profile: Dict[str, Any],
        job_description: Optional[str] = None,
        example_resumes: Optional[List[Dict]] = None,
        template: Optional[Dict] = None,
        target_role: Optional[str] = None,
        model_override: Optional[str] = None,
        atoms: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a resume using the Resume Generator Agent via Ollama.

        Two modes:
          1. ATOMS MODE (preferred when available): if `atoms` is a non-empty
             list of style atoms (from the template), the LLM emits a
             structured JSON document conforming to the atom schema. The
             backend DOCX composer then uses the same atoms to render with
             the template's exact styling.
          2. PLAIN-TEXT MODE (fallback): no atoms provided. The LLM emits a
             plain-text resume that the frontend will format heuristically.

        Both modes use the example resumes as the candidate's voice/tone and
        content reference.
        """
        if atoms:
            return await self._generate_resume_structured(
                job_description=job_description,
                example_resumes=example_resumes,
                atoms=atoms,
                target_role=target_role,
                model_override=model_override,
            )
        return await self._generate_resume_plain(
            user_profile=user_profile,
            job_description=job_description,
            example_resumes=example_resumes,
            template=template,
            target_role=target_role,
            model_override=model_override,
        )

    async def _generate_resume_plain(
        self,
        user_profile: Dict[str, Any],
        job_description: Optional[str] = None,
        example_resumes: Optional[List[Dict]] = None,
        template: Optional[Dict] = None,
        target_role: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Original plain-text path. Kept as a fallback when no template atoms
        are available.
        """
        agent_prompt = self._load_agent_prompt("resume-generator")

        # Build example resumes section (limit to most recent + size cap)
        MAX_EXAMPLES = 3
        MAX_TOTAL_CHARS = 20000
        example_resumes_section = ""
        if example_resumes:
            example_resumes_section = (
                "\n\nEXAMPLE RESUMES (reference for style and content):\n"
            )
            selected = example_resumes[-MAX_EXAMPLES:] if len(example_resumes) > MAX_EXAMPLES else example_resumes
            total_chars = 0
            for idx, example in enumerate(selected):
                name = example.get("name", f"Example {idx + 1}")
                content = example.get("content", "")

                if content and content.startswith("data:"):
                    content = extract_text_from_file(content, name)

                remaining = MAX_TOTAL_CHARS - total_chars
                if remaining <= 0:
                    break
                truncated = content[:min(8000, remaining)]
                total_chars += len(truncated)
                example_resumes_section += (
                    f"\n--- Example {idx + 1}: {name} ---\n{truncated}\n"
                )

        # Build template section (used as a text reference in plain mode)
        template_section = ""
        if template:
            template_content = template.get("content", "")
            if template_content and template_content.startswith("data:"):
                template_content = extract_text_from_file(
                    template_content, template.get("name", "template.docx")
                )
            template_section = f"\nTEMPLATE TO USE:\n{template_content[:8000]}\n"

        job_desc_section = (
            f"JOB DESCRIPTION TO TAILOR FOR:\n{job_description[:16000]}"
            if job_description
            else ""
        )

        prompt = f"""{agent_prompt}

Generate a professional resume for this candidate.

TARGET ROLE: {target_role or "Not specified"}

CRITICAL INSTRUCTIONS - FOLLOW EXACTLY:
1. The EXAMPLE RESUMES below contain the CANDIDATE'S REAL EXPERIENCE, SKILLS, EMPLOYMENT HISTORY, EDUCATION, AND CONTACT INFO
2. You MUST copy the candidate's information VERBATIM from the example resumes - do NOT paraphrase or modify names, dates, companies, job titles, or skills
3. DO NOT add any experience, skills, certifications, or achievements that are not explicitly stated in the example resumes
4. If the job description requires skills the candidate doesn't have, leave those skills out - do NOT fabricate them
5. Use the job description ONLY to select which experience to highlight and how to word it - do NOT invent new experience
6. The TEMPLATE is for formatting/structure only - never use template content as candidate information

STRICT RULES:
- Never make up a company name not in the example resumes
- Never make up a job title not in the example resumes
- Never make up dates or durations
- Never make up skills or technologies not in the example resumes
- Never make up education credentials not in the example resumes
- If you are unsure whether something is in the example resumes, DO NOT include it

MANDATORY COMPLETENESS REQUIREMENTS:
- You MUST include EVERY SINGLE job/role listed in the example resumes - do not skip or condense any positions
- You MUST include the complete Education section with ALL degrees, certifications, and training listed
- If the example resumes list 5 jobs, include ALL 5 jobs - never truncate this list
- If the example resumes list multiple degrees or certifications, include ALL of them
- Do not cut off or abbreviate the work history - every role matters

{example_resumes_section}

TEMPLATE (formatting only - do not copy content):
{template_section}

Job Description (use ONLY to tailor wording, not to invent experience):
{job_desc_section}

Output format: Plain text resume only. No JSON needed. Include ALL positions and ALL education."""

        try:
            model = model_override or self.ollama.generation_model
            logger.info(f"[ResumeGenerator/plain] Using model: {model}")
            response = await self.ollama.generate(prompt, temperature=0.7, model=model)
            logger.info(f"[ResumeGenerator/plain] Raw response length: {len(response)}")
            if not response:
                raise Exception("Empty response from Ollama")
            return {"content": response.strip(), "mode": "plain"}
        except Exception as e:
            logger.info(f"[ResumeGenerator/plain] Error: {e}")
            return {"error": str(e), "content": f"Error generating resume: {str(e)}"}

    async def _generate_resume_structured(
        self,
        job_description: Optional[str],
        example_resumes: Optional[List[Dict]],
        atoms: List[Dict[str, Any]],
        target_role: Optional[str],
        model_override: Optional[str],
    ) -> Dict[str, Any]:
        """Structured-JSON path. The LLM receives the atom vocabulary and
        emits a JSON tree of {atom_id, text/segments} entries. The composer
        later turns that into a DOCX that matches the template exactly.

        Why JSON: the LLM is good at choosing what content goes where, but
        bad at reliably reproducing exact fonts/colors/spacing. By having it
        emit only *content decisions* (which atom, what text, what inline
        bolding), we let the captured template handle all visual fidelity.
        """
        import json as _json

        # Build a tight schema description so the LLM knows what's available.
        # We do NOT include all style internals — just the id and what kind
        # of content each atom is for.
        atom_specs = []
        for a in atoms:
            atom_specs.append({
                "id": a.get("id"),
                "purpose": _atom_purpose(a.get("id", "")),
                "schema_hint": _atom_schema_hint(a.get("id", "")),
            })

        # Build example resumes section
        MAX_EXAMPLES = 3
        MAX_TOTAL_CHARS = 20000
        example_resumes_section = ""
        if example_resumes:
            example_resumes_section = (
                "\n\nEXAMPLE RESUMES (reference for style and content):\n"
            )
            selected = example_resumes[-MAX_EXAMPLES:] if len(example_resumes) > MAX_EXAMPLES else example_resumes
            total_chars = 0
            for idx, example in enumerate(selected):
                name = example.get("name", f"Example {idx + 1}")
                content = example.get("content", "")
                if content and content.startswith("data:"):
                    content = extract_text_from_file(content, name)
                remaining = MAX_TOTAL_CHARS - total_chars
                if remaining <= 0:
                    break
                truncated = content[:min(8000, remaining)]
                total_chars += len(truncated)
                example_resumes_section += (
                    f"\n--- Example {idx + 1}: {name} ---\n{truncated}\n"
                )

        job_desc_section = (
            f"JOB DESCRIPTION TO TAILOR FOR:\n{job_description[:16000]}"
            if job_description
            else ""
        )

        # Schema explanation for the LLM
        atom_spec_text = _json.dumps(atom_specs, indent=2)

        system = (
            "You are a resume writer. You output ONLY valid JSON that conforms "
            "to the schema the user provides. Never output prose, never output "
            "markdown fences. Begin your response with '{' and end with '}'."
        )

        prompt = f"""You are tailoring a resume for a specific job. You will output a structured JSON tree that mirrors the candidate's example resumes but emphasizes the experience most relevant to this job description.

TARGET ROLE: {target_role or "Not specified"}

CONTENT RULES (strict — these guard against hallucination):
1. The EXAMPLE RESUMES below contain the candidate's REAL information. Copy names, dates, companies, job titles, skills, and education VERBATIM. Do NOT paraphrase or fabricate.
2. Do NOT add experience, skills, certifications, or achievements not present in the examples.
3. If the job description asks for something the candidate doesn't have, leave it out — never invent.
4. Use the job description ONLY to choose what to emphasize and how to word it.
5. Include EVERY job/role listed in the examples. Include the complete Education section if present.
6. For text fields, write concise, action-oriented resume bullets that match the candidate's tone from the examples.

FORMAT RULES:
1. Output ONLY a JSON object with this exact shape:
   {{
     "atoms": [
       {{ "atom_id": "<one of the atom ids below>", <content fields per atom> }},
       ...
     ]
   }}
2. Use ONLY atom_ids from the ATOM VOCABULARY section below.
3. For atoms that take plain "text" (like section_header, role_title), use {{ "atom_id": "...", "text": "..." }}.
4. For atoms that take "segments" (like title, role_line, bullet), use:
   {{ "atom_id": "...", "segments": [{{ "text": "..." }}, ...] }}
   Use multiple segments with the literal text " | " between to reproduce the template's separator style. For role_line, the FIRST segment is the company name and should include "bold": true. For bullets, segments are typically a single text run.
5. Order atoms in resume order: title, body_para (summary), bullet.summary items if any, section_header, bullet.section items, section_header (next), role_title, role_line, bullet.role, role_title, role_line, bullet.role, ...
6. If a bullet.summary variant exists, use it for numbered highlights near the top (1) 2) 3)). If not, just emit body_para summaries.
7. bullet.section is for bullets under section headers like Core Competencies (no role attached).
8. bullet.role is for accomplishment bullets under a specific role. Always emit AFTER a role_line.
9. Use body_para for plain prose (summary, leadership philosophy, etc.).
10. Do NOT emit anything outside the JSON. No preamble, no explanation, no markdown.

ATOM VOCABULARY (use only these atom_ids):
{atom_spec_text}

ATOM PURPOSES:
- title: top of resume — name + tagline. Segments separated by " | ".
- section_header: "Core Competencies", "Professional Experience", "Education", etc.
- role_title: a job title like "Chief Technology Officer" within an Experience section.
- role_line: directly under role_title — segments separated by " | " like "<Company> | <Location> | <Dates>". First segment is the company name, mark it bold:true.
- bullet.summary: numbered highlight (1) 2) 3)...) used near the top.
- bullet.section: bullet under a section_header (Core Competencies, etc.).
- bullet.role: accomplishment bullet under a role.
- body_para: plain prose paragraph (summary, leadership philosophy).

{example_resumes_section}

{job_desc_section}

Output the JSON now:"""

        try:
            model = model_override or self.ollama.generation_model
            logger.info(f"[ResumeGenerator/structured] Using model: {model}")
            response = await self.ollama.generate(
                prompt, system=system, temperature=0.4, model=model
            )
            logger.info(f"[ResumeGenerator/structured] Raw response length: {len(response)}")

            if not response:
                raise Exception("Empty response from Ollama")

            parsed = _extract_json(response)
            if parsed is None:
                logger.warning(
                    f"[ResumeGenerator/structured] Could not parse JSON; falling back to text wrap. Response: {response[:500]}"
                )
                return {
                    "mode": "structured_fallback",
                    "structured_content": _wrap_plain_text_as_structured(response, atoms),
                    "content": response.strip(),
                }
            # Validate basic shape; reject if it's clearly broken
            if not isinstance(parsed, dict) or "atoms" not in parsed or not isinstance(parsed["atoms"], list):
                logger.warning(
                    f"[ResumeGenerator/structured] JSON missing 'atoms' array; falling back."
                )
                return {
                    "mode": "structured_fallback",
                    "structured_content": _wrap_plain_text_as_structured(response, atoms),
                    "content": response.strip(),
                }
            return {
                "mode": "structured",
                "structured_content": parsed,
                "content": _structured_to_plain_text(parsed),
            }
        except Exception as e:
            logger.info(f"[ResumeGenerator/structured] Error: {e}")
            return {"error": str(e), "content": f"Error generating resume: {str(e)}"}

    async def revise_resume(
        self,
        current_resume: str,
        feedback: str,
        job_description: Optional[str] = None,
        example_resumes: Optional[List[Dict]] = None,
        template: Optional[Dict] = None,
        target_role: Optional[str] = None,
        atoms: Optional[List[Dict[str, Any]]] = None,
        current_structured: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Revise an existing resume based on user feedback.

        Two modes (mirror of generate_resume):
          - STRUCTURED: when `atoms` and `current_structured` are provided,
            emit the revised resume as JSON conforming to the atom schema.
          - PLAIN: otherwise, return revised plain text.
        """
        if atoms and current_structured is not None:
            return await self._revise_resume_structured(
                current_structured=current_structured,
                feedback=feedback,
                job_description=job_description,
                example_resumes=example_resumes,
                atoms=atoms,
                target_role=target_role,
            )
        return await self._revise_resume_plain(
            current_resume=current_resume,
            feedback=feedback,
            job_description=job_description,
            example_resumes=example_resumes,
            template=template,
            target_role=target_role,
        )

    async def _revise_resume_plain(
        self,
        current_resume: str,
        feedback: str,
        job_description: Optional[str],
        example_resumes: Optional[List[Dict]],
        template: Optional[Dict],
        target_role: Optional[str],
    ) -> Dict[str, Any]:
        """Plain-text revision path (legacy)."""
        agent_prompt = self._load_agent_prompt("resume-generator")

        example_resumes_section = ""
        if example_resumes:
            example_resumes_section = "\n\nEXAMPLE RESUMES (reference for style and content):\n"
            for idx, example in enumerate(example_resumes):
                name = example.get("name", f"Example {idx + 1}")
                content = example.get("content", "")
                if content and content.startswith("data:"):
                    content = extract_text_from_file(content, name)
                example_resumes_section += f"\n--- Example {idx + 1}: {name} ---\n{content[:40000]}\n"

        template_section = ""
        if template:
            template_content = template.get("content", "")
            if template_content and template_content.startswith("data:"):
                template_content = extract_text_from_file(
                    template_content, template.get("name", "template.docx")
                )
            template_section = f"\nTEMPLATE (formatting only):\n{template_content[:8000]}\n"

        job_desc_section = f"JOB DESCRIPTION:\n{job_description[:16000]}" if job_description else ""

        prompt = f"""{agent_prompt}

You are REVISING an existing resume based on the user's feedback.

TARGET ROLE: {target_role or "Not specified"}

CURRENT RESUME:
---
{current_resume}
---

USER FEEDBACK (apply these changes):
---
{feedback}
---

{example_resumes_section}

{template_section}

{job_desc_section}

CRITICAL INSTRUCTIONS:
1. Start from the CURRENT RESUME and make the specific changes requested in the FEEDBACK
2. Preserve all existing content that the user did NOT ask to change
3. Do NOT remove any jobs, education, or experience unless the feedback explicitly asks for it
4. Follow the same strict rules about not fabricating experience (see original instructions)
5. Output the COMPLETE revised resume (not just the changed sections)

Output format: Plain text resume only. No JSON."""

        try:
            response = await self.ollama.generate(prompt, temperature=0.7, model=self.ollama.generation_model)
            if not response:
                raise Exception("Empty response from Ollama")
            return {"content": response.strip(), "mode": "plain"}
        except Exception as e:
            logger.info(f"[ResumeRevise/plain] Error: {e}")
            return {"error": str(e), "content": f"Error revising resume: {str(e)}"}

    async def _revise_resume_structured(
        self,
        current_structured: Dict[str, Any],
        feedback: str,
        job_description: Optional[str],
        example_resumes: Optional[List[Dict]],
        atoms: List[Dict[str, Any]],
        target_role: Optional[str],
    ) -> Dict[str, Any]:
        """Structured revision: feed the current structured content + feedback,
        get back a revised structured JSON.
        """
        import json as _json

        atom_specs = []
        for a in atoms:
            atom_specs.append({
                "id": a.get("id"),
                "purpose": _atom_purpose(a.get("id", "")),
                "schema_hint": _atom_schema_hint(a.get("id", "")),
            })

        example_resumes_section = ""
        if example_resumes:
            example_resumes_section = "\n\nEXAMPLE RESUMES (reference for style and content):\n"
            for idx, example in enumerate(example_resumes):
                name = example.get("name", f"Example {idx + 1}")
                content = example.get("content", "")
                if content and content.startswith("data:"):
                    content = extract_text_from_file(content, name)
                example_resumes_section += f"\n--- Example {idx + 1}: {name} ---\n{content[:40000]}\n"

        job_desc_section = f"JOB DESCRIPTION:\n{job_description[:16000]}" if job_description else ""
        atom_spec_text = _json.dumps(atom_specs, indent=2)
        current_text = _json.dumps(current_structured, indent=2)

        system = (
            "You are a resume editor. Output ONLY valid JSON. Begin with '{' "
            "and end with '}'. No prose, no markdown fences."
        )

        prompt = f"""You are REVISING a structured resume based on user feedback.

TARGET ROLE: {target_role or "Not specified"}

CURRENT STRUCTURED RESUME (JSON):
---
{current_text}
---

USER FEEDBACK (apply these changes):
---
{feedback}
---

ATOM VOCABULARY (use only these atom_ids):
{atom_spec_text}

ATOM PURPOSES:
- title: top of resume — name + tagline. Segments separated by " | ".
- section_header: "Core Competencies", "Professional Experience", "Education", etc.
- role_title: a job title within an Experience section.
- role_line: directly under role_title — segments separated by " | ". First segment is company name with "bold": true.
- bullet.summary: numbered highlight bullet near the top.
- bullet.section: bullet under a section_header.
- bullet.role: accomplishment bullet under a role.
- body_para: plain prose paragraph.

RULES:
1. Start from the CURRENT STRUCTURED RESUME and apply the specific changes requested.
2. Preserve every atom the user did NOT ask to change.
3. Do NOT remove any roles, education, or experience unless feedback explicitly says to.
4. Use ONLY atom_ids from the ATOM VOCABULARY above.
5. Output the COMPLETE revised resume (all atoms, in order).
6. Output ONLY a JSON object: {{ "atoms": [{{ "atom_id": "...", <content> }}, ...] }}.

{example_resumes_section}

{job_desc_section}

Output the JSON now:"""

        try:
            response = await self.ollama.generate(
                prompt, system=system, temperature=0.4, model=self.ollama.generation_model
            )
            if not response:
                raise Exception("Empty response from Ollama")
            parsed = _extract_json(response)
            if parsed is None or not isinstance(parsed, dict) or "atoms" not in parsed:
                logger.warning("[ResumeRevise/structured] JSON parse failed; falling back to plain wrap.")
                return {
                    "mode": "structured_fallback",
                    "structured_content": _wrap_plain_text_as_structured(response, atoms),
                    "content": response.strip(),
                }
            return {
                "mode": "structured",
                "structured_content": parsed,
                "content": _structured_to_plain_text(parsed),
            }
        except Exception as e:
            logger.info(f"[ResumeRevise/structured] Error: {e}")
            return {"error": str(e), "content": f"Error revising resume: {str(e)}"}

    async def parse_job_description(
        self, text: str, source_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parse job description using Job Description Archiver Agent via Ollama
        """
        from job_parser import JobParser

        parser = JobParser()
        result = await parser.parse_from_text(text)

        return {
            "company": result.get("company", "Unknown"),
            "position": result.get("position", "Unknown"),
            "location": result.get("location"),
            "salary": result.get("salary"),
            "remote": result.get("remote"),
            "url": source_url or result.get("url"),
            "description": result.get("description"),
            "requirements": result.get("requirements", {}),
            "responsibilities": result.get("responsibilities", []),
            "keywords": result.get("keywords", []),
            "credentials": result.get("credentials", []),
        }


# ---- Structured-resume helpers ------------------------------------------


_ATOM_PURPOSES = {
    "title": "top-of-resume name + tagline (segments separated by ' | ')",
    "section_header": "section heading like 'Core Competencies', 'Professional Experience', 'Education'",
    "role_title": "a job title inside an Experience section",
    "role_line": "directly under role_title: 'Company | Location | Dates' (first segment is bolded company name)",
    "bullet": "generic bullet — use only if no more specific bullet variant is available",
    "bullet.summary": "numbered highlight bullet near the top (1) 2) 3)...)",
    "bullet.section": "bullet under a section header (Core Competencies, etc.) — uses a '•' marker",
    "bullet.role": "accomplishment bullet under a specific role — uses a '•' marker",
    "body_para": "plain prose paragraph (summary, leadership philosophy, etc.)",
}


def _atom_purpose(atom_id: str) -> str:
    return _ATOM_PURPOSES.get(atom_id, "unspecified")


def _atom_schema_hint(atom_id: str) -> str:
    """Describe the JSON shape the LLM should emit for this atom."""
    if atom_id == "title":
        return '{"atom_id": "title", "segments": [{"text": "<Name>"}, {"text": " | "}, {"text": "<Tagline>"}]}'
    if atom_id == "role_line":
        return '{"atom_id": "role_line", "segments": [{"text": "<Company>", "bold": true}, {"text": " | <Location> | <Dates>"}]}'
    if atom_id in ("section_header", "role_title"):
        return '{"atom_id": "<id>", "text": "<value>"}'
    if atom_id.startswith("bullet") or atom_id == "body_para":
        return '{"atom_id": "<id>", "segments": [{"text": "<value>"}]}'
    return '{"atom_id": "<id>", "text": "<value>"}'


def _extract_json(text: str):
    """Pull a JSON object out of an LLM response that may have leading/trailing
    prose or be wrapped in markdown fences. Returns dict or None.
    """
    import json as _json
    s = text.strip()
    # Strip markdown code fences if present
    if s.startswith("```"):
        # Drop first line (```json or ```) and last ```
        lines = s.split("\n")
        # Find first newline after the fence marker
        if len(lines) > 1:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    # Find the outermost {...} block
    if not s.startswith("{"):
        start = s.find("{")
        if start == -1:
            return None
        s = s[start:]
    if not s.endswith("}"):
        end = s.rfind("}")
        if end == -1:
            return None
        s = s[: end + 1]
    try:
        return _json.loads(s)
    except Exception:
        # One more attempt: try to find a balanced {...}
        depth = 0
        in_str = False
        esc = False
        for i, ch in enumerate(s):
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return _json.loads(s[: i + 1])
                    except Exception:
                        return None
        return None


def _structured_to_plain_text(parsed: Dict[str, Any]) -> str:
    """Convert structured content to plain text — used for the legacy
    `current_content` field on GeneratedResume so the existing version
    dropdown / editor still work.
    """
    out: List[str] = []
    for entry in parsed.get("atoms", []):
        atom_id = entry.get("atom_id", "")
        if "text" in entry:
            out.append(entry["text"])
        elif "segments" in entry:
            out.append("".join(seg.get("text", "") for seg in entry["segments"]))
    return "\n".join(out)


def _wrap_plain_text_as_structured(text: str, atoms: List[Dict[str, Any]]) -> Dict[str, Any]:
    """When the LLM didn't emit JSON, fall back to putting each non-empty
    line in a body_para atom. Not visually identical to the template, but
    at least preserves the candidate's content.
    """
    fallback_id = "body_para"
    for a in atoms:
        if a.get("id") == "body_para":
            fallback_id = "body_para"
            break
    entries = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        entries.append({
            "atom_id": fallback_id,
            "segments": [{"text": line}],
        })
    return {"atoms": entries}


# Singleton instance
agent_service = AgentService()
