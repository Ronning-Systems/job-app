import os
import sys
import logging
from pathlib import Path

# Setup logging to file
log_dir = Path(__file__).parent
log_file = log_dir / "backend.log"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=env_path)

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel, HttpUrl
from datetime import datetime
import httpx

from models import (
    init_db,
    get_db,
    Job,
    JobApplication,
    BaseResume,
    GeneratedResume,
    SessionLocal,
)
from job_parser import JobParser
from agents import agent_service

logger = logging.getLogger(__name__)

app = FastAPI(title="Job Tracker API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()


# Pydantic models
class JobCreateInput(BaseModel):
    url: Optional[str] = None
    job_text: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {"url": "https://example.com/job/123", "job_text": ""}
        }


class JobUpdate(BaseModel):
    company: Optional[str] = None
    position: Optional[str] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    remote: Optional[str] = None
    job_url: Optional[str] = None
    job_description_raw: Optional[str] = None
    job_description_parsed: Optional[str] = None
    notes: Optional[str] = None
    applied_date: Optional[datetime] = None


class ApplicationUpdate(BaseModel):
    stage: Optional[str] = None
    applied_date: Optional[datetime] = None
    response_received: Optional[bool] = None
    notes: Optional[str] = None


class BaseResumeCreate(BaseModel):
    name: str
    resume_type: str  # 'example' or 'template'
    content: str  # Base64 encoded file content


class JobResponse(BaseModel):
    id: int
    company: str
    position: str
    location: Optional[str]
    salary: Optional[str]
    remote: Optional[str]
    job_url: Optional[str]
    stage: str
    applied_date: Optional[datetime]
    response_received: bool
    notes: Optional[str]
    keywords: Optional[list]
    generated_resume: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class JobDetailResponse(JobResponse):
    job_description_raw: Optional[str]
    job_description_parsed: Optional[str]
    requirements: Optional[dict]
    responsibilities: Optional[list]
    required_credentials: Optional[list]
    history: Optional[list]
    generated_resume: Optional[str]




@app.post("/api/jobs", response_model=JobDetailResponse)
async def create_job(
    input_data: JobCreateInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Create a new job from job description text.
    The job text is parsed using Ollama to extract structured data.
    The URL is stored for reference only (not fetched).
    """
    parser = JobParser()

    if not input_data.job_text:
        raise HTTPException(status_code=400, detail="Job description text is required")

    # Parse from plain text using Ollama
    try:
        job_data = await parser.parse_from_text(input_data.job_text)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to parse job text: {str(e)}"
        )

    # Create Job record
    job = Job(
        company=job_data.get("company", "Unknown"),
        position=job_data.get("position", "Unknown"),
        location=job_data.get("location"),
        salary=job_data.get("salary"),
        remote=job_data.get("remote"),
        job_url=input_data.url or job_data.get("url"),
        job_description_raw=job_data.get("raw_text", input_data.job_text),
        job_description_parsed=job_data.get("description"),
        requirements=job_data.get("requirements", {}),
        responsibilities=job_data.get("responsibilities", []),
        keywords=job_data.get("keywords", []),
        required_credentials=job_data.get("credentials", []),
        source_type="url" if input_data.url else "text",
        source_url=input_data.url,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    # Create initial application record with "saved" stage
    application = JobApplication(
        job_id=job.id,
        stage="saved",
        history=[
            {
                "date": datetime.utcnow().isoformat(),
                "action": "job_added",
                "notes": "Job added",
            }
        ],
    )
    db.add(application)
    db.commit()

    return format_job_response(job, application)


@app.get("/api/jobs", response_model=List[JobResponse])
def list_jobs(
    stage: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List all jobs with optional filtering"""
    query = db.query(Job, JobApplication).join(
        JobApplication, Job.id == JobApplication.job_id
    )

    if stage:
        query = query.filter(JobApplication.stage == stage)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Job.company.ilike(search_filter))
            | (Job.position.ilike(search_filter))
            | (Job.location.ilike(search_filter))
        )

    results = query.order_by(Job.created_at.desc()).all()

    return [format_job_response(job, app, db) for job, app in results]


@app.get("/api/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Get detailed job information"""
    result = (
        db.query(Job, JobApplication)
        .join(JobApplication, Job.id == JobApplication.job_id)
        .filter(Job.id == job_id)
        .first()
    )

    if not result:
        raise HTTPException(status_code=404, detail="Job not found")

    job, application = result
    return format_job_response(job, application, db)


@app.put("/api/jobs/{job_id}", response_model=JobDetailResponse)
def update_job(job_id: int, update: JobUpdate, db: Session = Depends(get_db)):
    """Update job details"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    update_dict = update.dict(exclude_unset=True)

    # Extract applied_date to update on application instead of job
    applied_date = update_dict.pop("applied_date", None)

    for field, value in update_dict.items():
        if hasattr(job, field):
            setattr(job, field, value)

    # Update applied_date on the application if provided
    if applied_date:
        application = (
            db.query(JobApplication).filter(JobApplication.job_id == job_id).first()
        )
        if application:
            application.applied_date = applied_date

    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)

    application = (
        db.query(JobApplication).filter(JobApplication.job_id == job_id).first()
    )
    return format_job_response(job, application)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    """Delete a job and its application records"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    db.delete(job)
    db.commit()

    return {"message": "Job deleted successfully"}


@app.post("/api/resumes/base")
def create_base_resume(resume: BaseResumeCreate, db: Session = Depends(get_db)):
    """Create or update a base resume (example or template)"""
    # For template type, delete any existing template first
    if resume.resume_type == "template":
        db.query(BaseResume).filter(BaseResume.resume_type == "template").delete()

    # Create new resume record
    base_resume = BaseResume(
        name=resume.name,
        resume_type=resume.resume_type,
        content=resume.content,
        source="upload",
    )
    db.add(base_resume)
    db.commit()
    db.refresh(base_resume)

    return {
        "id": base_resume.id,
        "name": base_resume.name,
        "resume_type": base_resume.resume_type,
        "message": f"{resume.resume_type.capitalize()} resume saved successfully",
    }


@app.get("/api/resumes/base")
def list_base_resumes(resume_type: Optional[str] = None, db: Session = Depends(get_db)):
    """List all base resumes, optionally filtered by type"""
    query = db.query(BaseResume)
    if resume_type:
        query = query.filter(BaseResume.resume_type == resume_type)

    resumes = query.all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "resume_type": r.resume_type,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in resumes
    ]


@app.delete("/api/resumes/base/{resume_id}")
def delete_base_resume(resume_id: int, db: Session = Depends(get_db)):
    """Delete a base resume"""
    resume = db.query(BaseResume).filter(BaseResume.id == resume_id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    db.delete(resume)
    db.commit()

    return {"message": "Resume deleted successfully"}


@app.patch("/api/jobs/{job_id}/stage", response_model=JobDetailResponse)
def update_stage(job_id: int, update: ApplicationUpdate, db: Session = Depends(get_db)):
    """Update the application stage and related fields"""
    application = (
        db.query(JobApplication).filter(JobApplication.job_id == job_id).first()
    )
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    # Add history entry if stage changed
    if update.stage and update.stage != application.stage:
        history_entry = {
            "date": datetime.utcnow().isoformat(),
            "action": f"stage_changed",
            "from": application.stage,
            "to": update.stage,
            "notes": update.notes or f"Stage changed to {update.stage}",
        }
        application.history = (application.history or []) + [history_entry]
        application.stage = update.stage

    # Update other fields
    if update.applied_date is not None:
        application.applied_date = update.applied_date
    if update.response_received is not None:
        application.response_received = update.response_received
        if update.response_received and not application.response_date:
            application.response_date = datetime.utcnow()
    if update.notes is not None:
        application.notes = update.notes

    application.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(application)

    job = db.query(Job).filter(Job.id == job_id).first()
    return format_job_response(job, application)


@app.post("/api/jobs/{job_id}/generate-resume")
async def generate_job_resume(
    job_id: int, resume_request: dict, db: Session = Depends(get_db)
):
    """Generate a resume for a specific job using example resumes and template"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_description = job.job_description_parsed or job.job_description_raw

    # Debug: Log what's received
    logger.info(f"[generate-resume] Received request body: {resume_request}")
    logger.info(
        f"[generate-resume] example_resumes: {resume_request.get('example_resumes')}"
    )
    logger.info(f"[generate-resume] template: {resume_request.get('template')}")

    # Get example_resumes and template from request body first
    example_resumes = resume_request.get("example_resumes", [])
    template = resume_request.get("template")

    logger.info(
        f"[generate-resume] After get - example_resumes: {example_resumes}, template: {template}"
    )

    # Fall back to database if not provided in request
    if not example_resumes:
        example_resumes_db = (
            db.query(BaseResume).filter(BaseResume.resume_type == "example").all()
        )
        example_resumes = [
            {"name": r.name, "content": r.content} for r in example_resumes_db
        ]
        logger.info(
            f"[generate-resume] Fell back to DB - example_resumes: {len(example_resumes)} found"
        )

    if not template:
        template_db = (
            db.query(BaseResume).filter(BaseResume.resume_type == "template").first()
        )
        template = (
            {"name": template_db.name, "content": template_db.content}
            if template_db
            else None
        )
        logger.info(
            f"[generate-resume] Fell back to DB - template: {template_db.name if template_db else None}"
        )

    # Generate resume using agent service
    resume_result = await agent_service.generate_resume(
        user_profile={},
        job_description=job_description,
        example_resumes=example_resumes,
        template=template,
        target_role=job.position,
    )

    # Get the content from the result
    import json

    resume_content = resume_result.get("content", json.dumps(resume_result))

    # Save to GeneratedResume table
    generated_resume = GeneratedResume(job_id=job_id, content=resume_content)
    db.add(generated_resume)
    job.updated_at = datetime.utcnow()
    db.commit()

    return {
        "job_id": job_id,
        "resume": resume_content,
        "resume_id": generated_resume.id,
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "job-tracker-api"}


@app.get("/api/health/ollama")
async def ollama_health_check():
    """Check if Ollama is accessible"""
    ollama_url = os.getenv("MODEL_ENPOINT", "http://localhost:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{ollama_url}/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name") for m in models]
                return {"status": "connected", "url": ollama_url, "models": model_names}
            else:
                return {
                    "status": "error",
                    "url": ollama_url,
                    "message": f"HTTP {response.status_code}",
                }
    except Exception as e:
        return {"status": "unreachable", "url": ollama_url, "message": str(e)}


@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics"""
    from sqlalchemy import func

    stats = {"total": db.query(Job).count(), "by_stage": {}}

    # Count by stage
    stage_counts = (
        db.query(JobApplication.stage, func.count(JobApplication.id))
        .group_by(JobApplication.stage)
        .all()
    )

    for stage, count in stage_counts:
        stats["by_stage"][stage] = count

    # Active = saved, applied, phone_screen, interview, executive_call
    active_stages = ["saved", "applied", "phone_screen", "interview", "executive_call"]
    stats["active"] = sum(stats["by_stage"].get(s, 0) for s in active_stages)
    stats["interviews"] = stats["by_stage"].get("interview", 0) + stats["by_stage"].get(
        "executive_call", 0
    )
    stats["offers"] = stats["by_stage"].get("offered", 0)

    return stats


def format_job_response(
    job: Job, application: JobApplication, db: Session = None
) -> dict:
    """Format job and application into response"""
    # Ensure requirements has the correct structure
    requirements = job.requirements or {}
    if isinstance(requirements, dict):
        # Ensure must_have and nice_to_have keys exist
        if "must_have" not in requirements:
            requirements["must_have"] = []
        if "nice_to_have" not in requirements:
            requirements["nice_to_have"] = []
    else:
        # If requirements is not a dict, create empty structure
        requirements = {"must_have": [], "nice_to_have": []}

    # Get latest generated resume
    generated_resume = None
    if db:
        latest_resume = (
            db.query(GeneratedResume)
            .filter(GeneratedResume.job_id == job.id)
            .order_by(GeneratedResume.created_at.desc())
            .first()
        )
        if latest_resume:
            generated_resume = latest_resume.content

    return {
        "id": job.id,
        "company": job.company,
        "position": job.position,
        "location": job.location,
        "salary": job.salary,
        "remote": job.remote,
        "job_url": job.job_url,
        "stage": application.stage,
        "applied_date": application.applied_date,
        "response_received": application.response_received,
        "notes": application.notes,
        "keywords": job.keywords or [],
        "created_at": job.created_at,
        # Detail fields
        "job_description_raw": job.job_description_raw,
        "job_description_parsed": job.job_description_parsed,
        "requirements": requirements,
        "responsibilities": job.responsibilities or [],
        "required_credentials": job.required_credentials or [],
        "history": application.history or [],
        "generated_resume": generated_resume,
    }


# Agent endpoints
@app.post("/api/agents/ats-analysis")
async def ats_analysis(resume_text: str, job_id: int, db: Session = Depends(get_db)):
    """Run ATS Expert Agent analysis on a resume against a job"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_description = job.job_description_parsed or job.job_description_raw or ""
    analysis = agent_service.get_ats_expert_analysis(resume_text, job_description)

    return {"job_id": job_id, "analysis": analysis}


@app.post("/api/agents/technical-fit")
async def technical_fit(resume_text: str, job_id: int, db: Session = Depends(get_db)):
    """Run Technical Hiring Manager Agent analysis"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    analysis = agent_service.get_technical_fit_analysis(
        resume_text, job.requirements or {}
    )

    return {"job_id": job_id, "analysis": analysis}


@app.post("/api/agents/generate-resume")
async def generate_resume(
    user_profile: dict, job_id: Optional[int] = None, db: Session = Depends(get_db)
):
    """Generate a resume using Resume Generator Agent"""
    job_description = None
    if job_id:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job_description = job.job_description_parsed or job.job_description_raw

    resume = await agent_service.generate_resume(
        user_profile,
        job_description=job_description,
        target_role=user_profile.get("target_role"),
    )

    return {"job_id": job_id, "resume": resume}


# Merged MCP routes (previously mcp_server.py)


@app.post("/api/fetch-job")
async def fetch_job(request: dict):
    """
    Fetch job details from a URL.
    Supports LinkedIn, Indeed, and generic job boards.
    """
    url = request.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
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

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            html_content = response.text

        parser = JobParser()
        job_data = await parser.parse_from_html(html_content, url)
        return job_data

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied (403) when fetching URL. The website may block automated requests: {url}",
            )
        elif e.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Job posting not found (404): {url}",
            )
        else:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch URL (HTTP {e.response.status_code}): {str(e)}",
            )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Network error when fetching URL: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing job: {str(e)}")


# Static file serving and SPA catch-all
STATIC_DIR = str(Path(__file__).parent.parent / "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def serve_index():
    """Serve the main frontend page"""
    return FileResponse(Path(STATIC_DIR) / "index.html")


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Catch-all for SPA routing — return index.html for any non-API path"""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(Path(STATIC_DIR) / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
