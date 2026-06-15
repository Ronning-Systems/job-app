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
    """Base class for Ollama-powered agents"""

    def __init__(self):
        self.base_url = os.getenv("MODEL_ENDPOINT", "http://localhost:11434").rstrip(
            "/"
        )
        self.model = os.getenv("MODEL_AGENTS", "llama3.2:latest")
        self.generation_model = os.getenv("MODEL_GENERATION") or os.getenv("MODEL_AGENTS", "llama3.2:latest")
        self.api_key = os.getenv("OLLAMA_API_KEY", "")
        self.timeout = 120.0

    async def generate(
        self, prompt: str, system: Optional[str] = None, temperature: float = 0.3, model: Optional[str] = None
    ) -> str:
        """Generate text using Ollama"""
        url = f"{self.base_url}/api/generate"

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": model or self.model,
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
    ) -> Dict[str, Any]:
        """
        Generate a resume using the Resume Generator Agent via Ollama.
        Uses example_resumes and template instead of a base resume.
        """
        agent_prompt = self._load_agent_prompt("resume-generator")

        # Debug: Log what we received
        logger.info(
            f"[ResumeGenerator] Received example_resumes: {len(example_resumes) if example_resumes else 0}"
        )
        logger.info(f"[ResumeGenerator] Received template: {template}")

        # Build example resumes section
        example_resumes_section = ""
        if example_resumes:
            example_resumes_section = (
                "\n\nEXAMPLE RESUMES (reference for style and content):\n"
            )
            for idx, example in enumerate(example_resumes):
                name = example.get("name", f"Example {idx + 1}")
                content = example.get("content", "")

                if content and content.startswith("data:"):
                    content = extract_text_from_file(content, name)
                    logger.info(
                        f"[ResumeGenerator] Extracted text from example {idx + 1}: {name}, length: {len(content)}"
                    )

                example_resumes_section += (
                    f"\n--- Example {idx + 1}: {name} ---\n{content[:40000]}\n"
                )

        # Build template section
        template_section = ""
        if template:
            template_content = template.get("content", "")
            if template_content and template_content.startswith("data:"):
                template_content = extract_text_from_file(
                    template_content, template.get("name", "template.docx")
                )
                logger.info(
                    f"[ResumeGenerator] Extracted text from template: {template.get('name')}, length: {len(template_content)}"
                )
            template_section = f"\nTEMPLATE TO USE:\n{template_content[:8000]}\n"

        # Limit job description to 8000 chars
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
            response = await self.ollama.generate(prompt, temperature=0.7, model=self.ollama.generation_model)
            logger.info(f"[ResumeGenerator] Raw response length: {len(response)}")

            if not response:
                raise Exception("Empty response from Ollama")

            # Return the raw response as content
            return {"content": response.strip()}

        except Exception as e:
            logger.info(f"[ResumeGenerator] Error: {e}")
            return {"error": str(e), "content": f"Error generating resume: {str(e)}"}

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


# Singleton instance
agent_service = AgentService()
