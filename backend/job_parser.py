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
- salary: Salary range or compensation info (string)
- remote: One of "Remote", "Hybrid", "On-site", or "Not specified"
- description: Cleaned job description text (string)
- requirements: Object with "must_have" (list of strings) and "nice_to_have" (list of strings)
- responsibilities: List of key responsibilities (list of strings)
- keywords: Technical skills and keywords found (list of strings)
- credentials: Required degrees, certifications, years of experience (list of strings)

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

        # Try Ollama parsing
        print(f"[JobParser] Attempting Ollama parsing...")
        ollama_result = await self.ollama.parse_job_description(text)

        if ollama_result and ollama_result.get("company"):
            result = {
                "company": ollama_result.get("company", "Unknown"),
                "position": ollama_result.get("position", "Unknown"),
                "location": ollama_result.get("location"),
                "salary": ollama_result.get("salary"),
                "remote": ollama_result.get("remote", "Not specified"),
                "url": url,
                "raw_text": text,
                "description": ollama_result.get("description", text[:2000]),
                "requirements": ollama_result.get("requirements", {"must_have": [], "nice_to_have": []}),
                "responsibilities": ollama_result.get("responsibilities", []),
                "keywords": ollama_result.get("keywords", []),
                "credentials": ollama_result.get("credentials", [])
            }
            return result
        else:
            raise Exception("Ollama returned empty result")

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
            "credentials": self._extract_credentials(text)
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
        """Extract required credentials, degrees, certifications"""
        credential_patterns = [
            r"(?:Bachelor|Master|PhD|MBA|Degree)\s+(?:of\s+)?(?:Science|Arts|Engineering)?",
            r"(?:AWS|Azure|GCP|PMP|CISSP|CPA|CFA|Scrum)\s+(?:Certified|Certification|Certificate)?",
            r"\d+\+?\s*years?\s+(?:of\s+)?experience",
        ]

        credentials = []
        for pattern in credential_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            credentials.extend(matches)

        return list(set(credentials))

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
