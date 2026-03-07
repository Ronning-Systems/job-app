"""
MCP Server for fetching job descriptions from URLs.
This can be run as a separate service or integrated into the main backend.
"""

import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import httpx

from job_parser import JobParser

app = FastAPI(title="JobSync MCP Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class FetchJobRequest(BaseModel):
    url: str


class JobData(BaseModel):
    company: str
    position: str
    location: Optional[str]
    salary: Optional[str]
    remote: Optional[str]
    description: Optional[str]
    raw_text: str
    url: str


@app.post("/fetch-job", response_model=JobData)
async def fetch_job(request: FetchJobRequest):
    """
    Fetch job details from a URL.
    Supports LinkedIn, Indeed, and generic job boards.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(request.url, headers=headers, timeout=30.0)
            response.raise_for_status()
            html_content = response.text

        # Parse the job details
        job_data = parse_job_html(html_content, request.url)
        return job_data

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied (403) when fetching URL. The website may block automated requests: {request.url}"
            )
        elif e.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Job posting not found (404): {request.url}"
            )
        else:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch URL (HTTP {e.response.status_code}): {str(e)}"
            )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Network error when fetching URL: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing job: {str(e)}")


def parse_job_html(html_content: str, url: str) -> dict:
    """Parse job details from HTML"""
    parser = JobParser()
    return parser.parse_from_html(html_content, url)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
