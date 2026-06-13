import os

from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

Base = declarative_base()

class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    company = Column(String, nullable=False)
    position = Column(String, nullable=False)
    location = Column(String)
    salary = Column(String)
    remote = Column(String)  # Remote, Hybrid, On-site

    # Job description fields
    job_url = Column(String)
    job_description_raw = Column(Text)  # Original posting text
    job_description_parsed = Column(Text)  # Cleaned/parsed version
    requirements = Column(JSON)  # Must have and nice to have
    responsibilities = Column(JSON)
    keywords = Column(JSON)
    required_credentials = Column(JSON)

    # Source tracking
    source_type = Column(String)  # 'url' or 'text'
    source_url = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    applications = relationship("JobApplication", back_populates="job", cascade="all, delete-orphan")
    resumes = relationship("GeneratedResume", back_populates="job", cascade="all, delete-orphan")


class JobApplication(Base):
    __tablename__ = "job_applications"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)

    # Application tracking
    stage = Column(String, default="saved")  # saved, applied, phone_screen, interview, executive_call, offered, rejected, withdrawn, closed
    applied_date = Column(DateTime)
    response_received = Column(Boolean, default=False)
    response_date = Column(DateTime)

    # Notes and comments
    notes = Column(Text)

    # History tracking
    history = Column(JSON, default=list)  # List of {date, action, notes}

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="applications")


class BaseResume(Base):
    """Stored example resumes and templates"""
    __tablename__ = "base_resumes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # Filename or user-provided name
    resume_type = Column(String, nullable=False)  # 'example' or 'template'
    content = Column(Text)  # The actual resume content (text or extracted from DOCX)
    source = Column(String, default="upload")  # 'upload' for now
    created_at = Column(DateTime, default=datetime.utcnow)


class GeneratedResume(Base):
    """Generated resumes linked to jobs"""
    __tablename__ = "generated_resumes"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    content = Column(Text)  # The generated resume content
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="resumes")


# Database setup - PostgreSQL for production, SQLite for local dev
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Production: PostgreSQL via Cloud SQL
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
else:
    # Local dev: SQLite fallback
    engine = create_engine(
        "sqlite:///./job_tracker.db",
        connect_args={"check_same_thread": False},
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
