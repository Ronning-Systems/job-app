import re
import json
import os
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
import html
import httpx


class OllamaClient:
    """Client for calling Ollama API (local or cloud)"""

    def __init__(self):
        self.base_url = os.getenv("MODEL_ENDPOINT", "http://localhost:11434").rstrip('/')
        self.model = os.getenv("MODEL_PARSING") or os.getenv("OLLAMA_MODEL") or "llama3.2:latest"
        self.api_key = os.getenv("OLLAMA_API_KEY", "")
        # Ollama Cloud uses OpenAI-compatible chat endpoint
        self.is_cloud = "ollama.com" in self.base_url
        print(f"[OllamaClient] Using model: {self.model} at {self.base_url} (cloud={self.is_cloud})")

    async def parse_job_description(self, text: str) -> Dict[str, Any]:
        """Use Ollama to parse job description into structured data"""

        prompt = f"""You are a Job Description Archiver Agent. Extract structured information from the following job posting.

Analyze the job description and return a JSON object with these exact fields:
- company: The company name (string, required)
- position: The job title/position (string, required)
- location: Job location including city, state, and remote status (string)
- salary: Salary range or compensation info as free text (string). Kept as a fallback for anything that can't be structured.
- pay_range: Object with the structured compensation details:
    - min: number or null (lower bound of the range)
    - max: number or null (upper bound of the range; if only one number is given, put it here and leave min null)
    - currency: string (ISO currency code; default "USD" if not stated)
    - period: one of "annual", "hourly", or "monthly" (default "annual" if not stated)
- application_deadline: ISO date string (YYYY-MM-DD) if an application deadline is mentioned, else null
- remote: One of "Remote", "Hybrid", "On-site", or "Not specified"
- description: Cleaned job description text (string)
- requirements: Object with "must_have" (list of strings) and "nice_to_have" (list of strings)
- responsibilities: List of key responsibilities (list of strings)
- keywords: Technical skills and keywords found (list of strings)
- credentials: Required degrees, certifications, and years of experience (list of strings)

IMPORTANT: Return ONLY valid JSON. No markdown, no explanation, just the JSON object.

Job Description:
---
{text[:8000]}
---

JSON Output:"""

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers["Content-Type"] = "application/json"

        response_text = ""
        try:
            if self.is_cloud:
                # Ollama Cloud: OpenAI-compatible /v1/chat/completions
                url = f"{self.base_url}/v1/chat/completions"
                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                }
            else:
                # Local Ollama: /api/generate
                url = f"{self.base_url}/api/generate"
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 2000},
                }

            print(f"[OllamaClient] Sending request to {url} with model {self.model}")
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                result = response.json()

                # Parse the response based on API format
                if self.is_cloud:
                    response_text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                else:
                    response_text = result.get("response", "").strip()

                print(f"[OllamaClient] Got response: {response_text[:200]}...")

                # Try to extract JSON from the response
                json_text = response_text
                if "```json" in response_text:
                    json_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_text = response_text.split("```")[1].split("```")[0].strip()

                parsed = json.loads(json_text)

                # Validate required fields
                if "company" not in parsed or not parsed["company"]:
                    parsed["company"] = "Unknown Company"
                if "position" not in parsed or not parsed["position"]:
                    parsed["position"] = "Unknown Position"

                print(f"[OllamaClient] Successfully parsed job: {parsed.get('company')} - {parsed.get('position')}")
                return parsed

        except json.JSONDecodeError as e:
            print(f"[OllamaClient] JSON parse error: {e}")
            print(f"[OllamaClient] Response text: {response_text[:500]}")
            raise Exception(f"Failed to parse Ollama response as JSON: {str(e)}")
        except httpx.HTTPError as e:
            print(f"[OllamaClient] HTTP error: {e}")
            raise Exception(f"Ollama HTTP error: {str(e)}")
        except Exception as e:
            print(f"[OllamaClient] API error: {e}")
            raise Exception(f"Ollama API error: {str(e)}")


class JobParser:
    """
    Job Description Archiver Agent - Parser implementation
    Extracts structured job data from HTML or plain text
    Uses Ollama LLM for intelligent parsing
    """

    def __init__(self):
        self.ollama = OllamaClient()

    # Common job board patterns
    JOB_BOARD_SELECTORS = {
        "linkedin": {
            "title": [".top-card-layout__title", "h1"],
            "company": [".top-card-layout__card a", "[data-tracking-control-name='public_jobs_top-card-org-name']"],
            "description": [".show-more-less-html__markup", ".description"],
            "location": [".top-card-layout__first-subline"],
        },
        "indeed": {
            "title": ["h1", ".jobsearch-JobInfoHeader-title"],
            "company": ["[data-testid='company-name']", ".jobsearch-InlineCompanyRating"],
            "description": ["[data-testid='jobDescriptionText']", "#jobDescriptionText"],
            "location": ["[data-testid='job-location']", ".jobsearch-InlineCompanyRating"],
        },
        "generic": {
            "title": ["h1", ".job-title", "[class*='title']"],
            "company": ["[class*='company']", "[class*='employer']"],
            "description": ["[class*='description']", "[class*='details']", "article", "main"],
            "location": ["[class*='location']", "[class*='place']"],
        }
    }

    async def parse_from_html(self, html_content: str, url: str) -> Dict[str, Any]:
        """Parse job details from HTML content using Ollama"""
        soup = BeautifulSoup(html_content, 'html.parser')

        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()

        # Get clean text
        raw_text = soup.get_text(separator='\n', strip=True)

        # Use Ollama to parse the text
        return await self.parse_from_text(raw_text, url)

    async def parse_from_text(self, text: str, url: Optional[str] = None) -> Dict[str, Any]:
        """Parse job details from plain text using Ollama"""

        # Use Ollama parsing
        print(f"[JobParser] Parsing with Ollama...")
        ollama_result = await self.ollama.parse_job_description(text)

        if not ollama_result or not ollama_result.get("company"):
            raise Exception("Ollama returned empty result")

        return {
            "company": ollama_result.get("company", "Unknown"),
            "position": ollama_result.get("position", "Unknown"),
            "location": ollama_result.get("location"),
            "salary": ollama_result.get("salary"),
            "pay_range": ollama_result.get("pay_range"),
            "application_deadline": ollama_result.get("application_deadline"),
            "remote": ollama_result.get("remote", "Not specified"),
            "url": url,
            "raw_text": text,
            "description": ollama_result.get("description", text[:2000]),
            "requirements": ollama_result.get("requirements", {"must_have": [], "nice_to_have": []}),
            "responsibilities": ollama_result.get("responsibilities", []),
            "keywords": ollama_result.get("keywords", []),
            "credentials": ollama_result.get("credentials", [])
        }

    def _detect_job_board(self, url: str, html_content: str) -> str:
        """Detect which job board the URL is from"""
        url_lower = url.lower()
        if "linkedin.com" in url_lower:
            return "linkedin"
        elif "indeed.com" in url_lower:
            return "indeed"
        return "generic"

    def _extract_company(self, soup: BeautifulSoup, selectors: Dict) -> Optional[str]:
        """Extract company name from HTML"""
        for selector in selectors.get("company", []):
            elem = soup.select_one(selector)
            if elem:
                return self._clean_text(elem.get_text())

        # Fallback: try common patterns
        text = soup.get_text()
        return self._extract_company_from_text(text)

    def _extract_title(self, soup: BeautifulSoup, selectors: Dict, raw_text: str) -> Optional[str]:
        """Extract job title from HTML"""
        for selector in selectors.get("title", []):
            elem = soup.select_one(selector)
            if elem:
                return self._clean_text(elem.get_text())

        # Fallback to text parsing
        return self._extract_position_from_text(raw_text)

    def _extract_location(self, soup: BeautifulSoup, selectors: Dict, raw_text: str) -> Optional[str]:
        """Extract location from HTML"""
        for selector in selectors.get("location", []):
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text()
                # Clean up location string
                return self._clean_location(text)

        return self._extract_location_from_text(raw_text)

    def _extract_description(self, soup: BeautifulSoup, selectors: Dict) -> Optional[str]:
        """Extract job description from HTML"""
        for selector in selectors.get("description", []):
            elem = soup.select_one(selector)
            if elem:
                return self._clean_text(elem.get_text(separator='\n'))

        # Fallback to main content
        main = soup.find('main') or soup.find('article')
        if main:
            return self._clean_text(main.get_text(separator='\n'))

        return None

    def _extract_company_from_text(self, text: str) -> Optional[str]:
        """Extract company name from plain text"""
        patterns = [
            r"(?:Company|Organization|Employer)[:\s]+([^\n]+)",
            r"at\s+([A-Z][A-Za-z0-9\s&]+)(?:\s+\(|\s*[-–]|\s*\n)",
            r"([A-Z][A-Za-z0-9\s&]+)\s+(?:is\s+looking|is\s+hiring|seeks)"
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self._clean_text(match.group(1))

        return "Unknown Company"

    def _extract_position_from_text(self, text: str) -> Optional[str]:
        """Extract job title from plain text"""
        patterns = [
            r"(?:Job\s+Title|Position|Role)[:\s]+([^\n]+)",
            r"^([^\n]+(?:Engineer|Developer|Manager|Director|Analyst|Designer|Architect|Lead|Specialist)[^\n]*)",
            r"(?:Hiring|Opening)[:\s]+([^\n]+)"
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                return self._clean_text(match.group(1))

        # Extract first line as fallback
        first_line = text.split('\n')[0][:100]
        return self._clean_text(first_line) or "Unknown Position"

    def _extract_location_from_text(self, text: str) -> Optional[str]:
        """Extract location from plain text"""
        patterns = [
            r"(?:Location|Place|City)[:\s]+([^\n]+)",
            r"(?:Remote|Hybrid|On-site)[,\s]*([^\n]{3,50})?",
            r"([A-Z][a-z]+,\s*[A-Z]{2})"  # City, ST format
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                location = match.group(0)
                return self._clean_location(location)

        return None

    def _extract_salary(self, text: str) -> Optional[str]:
        """Extract salary information from text"""
        patterns = [
            r"\$[\d,]+(?:k|K)?(?:\s*-\s*\$?[\d,]+(?:k|K)?)?",
            r"(?:Salary|Compensation)[:\s]+([^\n]+)",
            r"(\d{2,3},?\d{3}\s*[-–]\s*\d{2,3},?\d{3})",
            r"up\s+to\s+\$?([\d,]+(?:k|K)?)"
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                salary = match.group(0)
                # Clean up salary string
                return self._clean_text(salary)

        return None

    def _detect_remote(self, text: str) -> str:
        """Detect if job is remote/hybrid/onsite"""
        text_lower = text.lower()

        if re.search(r'\b(fully?\s+remote|100%\s+remote|work\s+from\s+home|wfh)\b', text_lower):
            return "Remote"
        elif re.search(r'\bhybrid\b', text_lower):
            return "Hybrid"
        elif re.search(r'\b(on-site|onsite|in[-\s]?office|in[-\s]?person)\b', text_lower):
            return "On-site"

        return "Not specified"

    def _parse_description_details(self, text: str) -> Dict[str, Any]:
        """Parse job description for requirements, responsibilities, and keywords"""
        return {
            "requirements": self._extract_requirements(text),
            "responsibilities": self._extract_responsibilities(text),
            "keywords": self._extract_keywords(text),
            "credentials": self._extract_credentials(text),
            "pay_range": self._extract_pay_range(text),
            "application_deadline": self._extract_application_deadline(text),
        }

    def _extract_requirements(self, text: str) -> Dict[str, List[str]]:
        """Extract must-have and nice-to-have requirements"""
        requirements = {"must_have": [], "nice_to_have": []}

        # Find requirements section
        req_patterns = [
            r"(?:Requirements?|Qualifications?|What\s+You.*Need)[:\s]*\n(.*?)(?:\n\n|\Z)",
            r"(?:Must\s+Have|Required)[:\s]*\n(.*?)(?:\n\n|(?:Nice\s+to|Preferred)|\Z)",
        ]

        req_text = ""
        for pattern in req_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                req_text = match.group(1)
                break

        if not req_text:
            req_text = text

        # Extract bullet points
        bullets = re.findall(r'[•\-\*]\s*([^\n]+)', req_text)

        # Categorize requirements
        for bullet in bullets:
            bullet_lower = bullet.lower()
            if any(word in bullet_lower for word in ['preferred', 'nice', 'plus', 'bonus', 'desired']):
                requirements["nice_to_have"].append(bullet.strip())
            else:
                requirements["must_have"].append(bullet.strip())

        return requirements

    def _extract_responsibilities(self, text: str) -> List[str]:
        """Extract job responsibilities"""
        resp_patterns = [
            r"(?:Responsibilities?|What\s+You.*Do|Duties)[:\s]*\n(.*?)(?:\n\n|\Z)",
        ]

        resp_text = ""
        for pattern in resp_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                resp_text = match.group(1)
                break

        if resp_text:
            bullets = re.findall(r'[•\-\*]\s*([^\n]+)', resp_text)
            return [b.strip() for b in bullets if len(b.strip()) > 10]

        return []

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract technical skills and keywords"""
        # Common tech keywords
        tech_keywords = [
            "Python", "JavaScript", "TypeScript", "React", "Vue", "Angular", "Node.js",
            "SQL", "PostgreSQL", "MongoDB", "AWS", "Azure", "GCP", "Docker", "Kubernetes",
            "Linux", "Git", "CI/CD", "REST", "GraphQL", "FastAPI", "Flask", "Django",
            "Machine Learning", "AI", "Data Science", "Analytics", "ETL", "Big Data",
            "Agile", "Scrum", "Kanban", "Jira", "Confluence", "Figma", "Sketch",
            "Leadership", "Management", "Strategy", "Product", "Design", "Marketing"
        ]

        found_keywords = []
        text_lower = text.lower()

        for keyword in tech_keywords:
            if keyword.lower() in text_lower:
                found_keywords.append(keyword)

        return found_keywords

    def _extract_credentials(self, text: str) -> List[str]:
        """Extract required credentials, degrees, certifications, and years of experience"""
        credential_patterns = [
            # Degrees — capture the full degree phrase when present
            r"\b(?:Bachelor(?:'s|s)?|B\.?S\.?|B\.?A\.?|Master(?:'s|s)?|M\.?S\.?|M\.?A\.?|MBA|Ph\.?D\.?|Doctorate|Associate)\s+(?:of\s+|in\s+)?(?:Science|Arts|Engineering|Business|Computer Science)?\s*(?:degree)?\b",
            r"\b(?:Bachelor|Master|PhD|MBA|Associate|Degree)\s+(?:of\s+|in\s+)?(?:Science|Arts|Engineering)?\s*(?:degree)?\b",
            # Certifications (named certs)
            r"\b(?:PE|PMP|CAPM|CISSP|CISM|CISA|CPA|CFA|CCNA|CCNP|CCIE|TOGAF|ITIL(?:\s+v\d)?|Six\s+Sigma(?:\s+(?:Black|Green|Yellow)\s+Belt)?|CSM|PSM(?:\s+I{0,3})?|PSPO|Sec\+|Security\+|Network\+|A\+|CISSP|CompTIA(?:\s+\w+)?|AWS\s+(?:Certified\s+)?(?:Solutions\s+Architect|Developer|SysOps|Cloud\s+Practitioner|DevOps|Data\s+Engineer|Security|Specialty)(?:\s+(?:Associate|Professional|Specialty))?|Azure\s+(?:Certified\s+)?(?:Solutions\s+Architect|Developer|Administrator|Fundamentals|DevOps|Data\s+Engineer|Security)(?:\s+(?:Associate|Expert|Professional|Fundamentals))?|GCP\s+(?:Certified\s+)?(?:Professional\s+)?(?:Cloud\s+Architect|Cloud\s+Engineer|Data\s+Engineer|Cloud\s+Developer|Cloud\s+DevOps|Cloud\s+Network|Cloud\s+Security))\b",
            # Generic "X Certified" / "X Certification"
            r"\b[A-Z][A-Za-z0-9+#\.\s]{1,40}?\s+(?:Certified|Certification|Certificate)\b",
            # Years of experience phrasing
            r"\b\d+\+?\s*years?\s+(?:of\s+)?(?:relevant\s+|professional\s+)?experience\b",
            r"\b(?:minimum|at\s+least)\s+\d+\s+years?\s+(?:of\s+)?experience\b",
            # Licensed/registered
            r"\b(?:Licensed|Registered)\s+[A-Za-z\s]{3,40}\b",
        ]

        credentials = []
        for pattern in credential_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                cred = m.strip() if isinstance(m, str) else m
                # Normalize whitespace
                cred = re.sub(r"\s+", " ", cred).strip()
                if cred and cred not in credentials:
                    credentials.append(cred)

        # Deduplicate: drop a credential if it is a substring of another
        # captured credential (e.g. keep "PMP certification" over "PMP").
        deduped = []
        for cred in credentials:
            cred_lower = cred.lower()
            if any(
                cred != other and cred_lower in other.lower()
                for other in credentials
            ):
                continue
            deduped.append(cred)

        return deduped

    def _extract_pay_range(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract structured pay range from text.

        Returns a dict with {min, max, currency, period} or None.
        Detects period: "hourly" if /hr, /hour, or numbers in the 15-300 range
        with "/hr"; "annual" otherwise (default). Handles "k" suffix as thousands.
        """
        if not text:
            return None

        text_lower = text.lower()

        # Currency detection (default USD). Check more specific symbols first
        # so that "C$" / "CA$" aren't swallowed by the bare "$" USD rule.
        currency = "USD"
        if re.search(r"\b(?:gbp|pounds?|£)\b", text_lower) or "£" in text_lower:
            currency = "GBP"
        elif re.search(r"\b(?:eur|euros?|€)\b", text_lower) or "€" in text_lower:
            currency = "EUR"
        elif re.search(r"\bcad\b|c\$|ca\$|canadian\s+dollars?", text_lower):
            currency = "CAD"
        elif re.search(r"\b(?:usd|us\$|dollars?)\b", text_lower) or "$" in text_lower:
            currency = "USD"

        # Period detection flags
        is_hourly = bool(re.search(r"\b(?:/hr|/hour|per\s+hour|an\s+hour|hourly)\b", text_lower))
        is_monthly = bool(re.search(r"\b(?:/mo|/month|per\s+month|monthly)\b", text_lower))

        # Patterns for salary ranges. Each pattern should capture the numeric parts.
        # Helper to convert a number token like "80,000" or "80k" to int.
        def to_int(token: str) -> Optional[int]:
            token = token.lower().replace(",", "").replace("$", "").strip()
            if not token:
                return None
            k_suffix = token.endswith("k")
            if k_suffix:
                token = token[:-1]
            try:
                val = float(token)
            except ValueError:
                return None
            if k_suffix:
                val *= 1000
            return int(val)

        min_val: Optional[int] = None
        max_val: Optional[int] = None

        # 1. Explicit range: $80,000 - $120,000 | $80k-$120k | $80-120k | €40,000 - €60,000
        range_patterns = [
            r"(?:[\$€£]|C\$|CA\$|US\$|EUR\s|GBP\s|CAD\s)?\s*([\d,]+(?:\.\d+)?k?)\s*[-–to]+\s*(?:[\$€£]|C\$|CA\$|US\$|EUR\s|GBP\s|CAD\s)?\s*([\d,]+(?:\.\d+)?k?)",
            r"([\d,]+(?:\.\d+)?k?)\s*[-–to]+\s*([\d,]+(?:\.\d+)?k?)\s*(?:/hr|/hour|/year|/yr|/mo|/month)?",
        ]
        for pat in range_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                min_val = to_int(m.group(1))
                max_val = to_int(m.group(2))
                if min_val is not None and max_val is not None:
                    break

        # 2. "up to $150k" / "up to $150,000"
        if min_val is None and max_val is None:
            m = re.search(r"up\s+to\s*[\$€£]?\s*([\d,]+(?:\.\d+)?k?)", text, re.IGNORECASE)
            if m:
                max_val = to_int(m.group(1))

        # 3. Single value with rate: $25/hr, $50/hour
        if min_val is None and max_val is None:
            m = re.search(r"[\$€£]\s*([\d,]+(?:\.\d+)?)\s*(?:/hr|/hour|per\s+hour|an\s+hour)", text, re.IGNORECASE)
            if m:
                max_val = to_int(m.group(1))
                is_hourly = True

        # 4. "Salary: $90,000" / "Salary: $90k"
        if min_val is None and max_val is None:
            m = re.search(r"salary\s*[:\-]?\s*[\$€£]?\s*([\d,]+(?:\.\d+)?k?)", text, re.IGNORECASE)
            if m:
                max_val = to_int(m.group(1))

        # 5. Bare "$90,000" / "$90k"
        if min_val is None and max_val is None:
            m = re.search(r"[\$€£]\s*([\d,]+(?:\.\d+)?k?)", text, re.IGNORECASE)
            if m:
                max_val = to_int(m.group(1))

        if min_val is None and max_val is None:
            return None

        # Determine period
        if is_hourly:
            period = "hourly"
        elif is_monthly:
            period = "monthly"
        else:
            # Heuristic: if max is in the 15-300 range and there's an hourly-ish cue, treat as hourly
            if max_val is not None and 15 <= max_val <= 300 and re.search(r"/hr|/hour", text_lower):
                period = "hourly"
            else:
                period = "annual"

        return {
            "min": min_val,
            "max": max_val,
            "currency": currency,
            "period": period,
        }

    def _extract_application_deadline(self, text: str) -> Optional[str]:
        """Extract application deadline from text.

        Looks for phrases like "apply by", "deadline", "closes on",
        "applications close", "apply before" followed by a date.
        Returns an ISO YYYY-MM-DD string or None.
        """
        if not text:
            return None

        months = {
            "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
            "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
            "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
            "november": 11, "nov": 11, "december": 12, "dec": 12,
        }

        trigger = r"(?:apply\s+by|deadline(?:\s+is)?|closes?\s+on|applications?\s+close|apply\s+before|application\s+deadline|closing\s+date)"

        # Try to find a date near a trigger phrase
        # Date formats we support
        date_patterns = [
            (r"(\d{4})-(\d{1,2})-(\d{1,2})", "ymd_dash"),          # 2026-08-15
            (r"(\d{1,2})/(\d{1,2})/(\d{4})", "mdy_slash"),          # 08/15/2026
            (r"(\d{1,2})-(\d{1,2})-(\d{4})", "mdy_dash"),           # 08-15-2026
            (r"(\d{{1,2}})\s+({m})\s+(\d{{4}})".format(m="|".join(months.keys())), "dmy_text"),
            (r"({m})\s+(\d{{1,2}}),?\s+(\d{{4}})".format(m="|".join(months.keys())), "mdy_text"),
        ]

        # Build a combined search: find the trigger, then look for a date within ~40 chars after it
        for t_match in re.finditer(trigger, text, re.IGNORECASE):
            start = t_match.end()
            window = text[start:start + 60]
            for pat, kind in date_patterns:
                m = re.search(pat, window, re.IGNORECASE)
                if not m:
                    continue
                try:
                    if kind == "ymd_dash":
                        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    elif kind == "mdy_slash" or kind == "mdy_dash":
                        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    elif kind == "dmy_text":
                        d = int(m.group(1))
                        mo = months[m.group(2).lower()]
                        y = int(m.group(3))
                    elif kind == "mdy_text":
                        mo = months[m.group(1).lower()]
                        d = int(m.group(2))
                        y = int(m.group(3))
                    else:
                        continue
                    if not (1 <= mo <= 12 and 1 <= d <= 31):
                        continue
                    return f"{y:04d}-{mo:02d}-{d:02d}"
                except (ValueError, KeyError):
                    continue

        # Fallback: a bare ISO date in the text preceded by any deadline-ish word
        for pat, kind in date_patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                # Only accept if near a deadline cue
                ctx_start = max(0, m.start() - 80)
                ctx = text[ctx_start:m.end()].lower()
                if re.search(r"deadline|clos|apply|application", ctx):
                    try:
                        if kind == "ymd_dash":
                            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                        elif kind == "mdy_slash" or kind == "mdy_dash":
                            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                        elif kind == "dmy_text":
                            d = int(m.group(1))
                            mo = months[m.group(2).lower()]
                            y = int(m.group(3))
                        elif kind == "mdy_text":
                            mo = months[m.group(1).lower()]
                            d = int(m.group(2))
                            y = int(m.group(3))
                        else:
                            continue
                        if 1 <= mo <= 12 and 1 <= d <= 31:
                            return f"{y:04d}-{mo:02d}-{d:02d}"
                    except (ValueError, KeyError):
                        continue

        return None

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        if not text:
            return ""
        # Unescape HTML entities
        text = html.unescape(text)
        # Remove extra whitespace
        text = ' '.join(text.split())
        # Remove common noise
        text = re.sub(r'\s*\.\.\.\s*Apply now\s*', '', text, flags=re.IGNORECASE)
        return text.strip()

    def _clean_location(self, text: str) -> str:
        """Clean location string"""
        text = self._clean_text(text)
        # Remove common prefixes
        text = re.sub(r'^(Location|Place)[:\s]+', '', text, flags=re.IGNORECASE)
        return text
