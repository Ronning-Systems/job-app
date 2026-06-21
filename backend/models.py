import os
import logging
import secrets

from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)

Base = declarative_base()


def generate_public_job_id(length: int = 8) -> str:
    """Generate a globally unique short alphanumeric code for a job.

    Uses a 32-char alphabet (no ambiguous chars) and re-rolls on collision.
    Format: JOB-XXXXXXXX (e.g., JOB-A7K2M9P3)
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32 chars, no 0/O/1/I
    return "JOB-" + "".join(secrets.choice(alphabet) for _ in range(length))


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    auth0_id = Column(String(255), unique=True, index=True, nullable=False)
    email = Column(String(255))
    name = Column(String(255))
    avatar_url = Column(String(512))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    jobs = relationship("Job", back_populates="user")
    base_resumes = relationship("BaseResume", back_populates="user")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    public_job_id = Column(String(32), unique=True, index=True, nullable=True)  # Globally unique short code
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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    applications = relationship("JobApplication", back_populates="job", cascade="all, delete-orphan")
    resumes = relationship("GeneratedResume", back_populates="job", cascade="all, delete-orphan")
    user = relationship("User", back_populates="jobs")


class JobApplication(Base):
    __tablename__ = "job_applications"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user = relationship("User", back_populates="base_resumes")
    created_at = Column(DateTime, default=datetime.utcnow)


class GeneratedResume(Base):
    """Generated resume with revision history, linked to a job"""
    __tablename__ = "generated_resumes"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    current_content = Column(Text)  # Latest version of the resume
    revisions = Column(JSON, default=list)  # List of {version, content, feedback, timestamp}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="resumes")


# Database setup - PostgreSQL for production, SQLite for local dev
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Production: PostgreSQL (e.g., Cloud SQL via Unix socket)
    logger.info(f"Using PostgreSQL database from DATABASE_URL")
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"connect_timeout": 10},
    )
else:
    # Local dev: SQLite fallback
    logger.warning("DATABASE_URL not set; falling back to SQLite for local development")
    engine = create_engine(
        "sqlite:///./job_tracker.db",
        connect_args={"check_same_thread": False},
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    try:
        Base.metadata.create_all(bind=engine)
        _run_migrations(engine)
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        if not DATABASE_URL:
            raise  # SQLite should always work
        # For PostgreSQL, log but don't crash — the app can retry on first request
        logger.warning("PostgreSQL connection failed during startup; will retry on first request")


def _run_migrations(eng):
    """Add missing columns to existing tables (create_all only creates missing tables)."""
    from sqlalchemy import text, inspect
    inspector = inspect(eng)

    # Check generated_resumes table for missing columns
    if 'generated_resumes' in inspector.get_table_names():
        existing_cols = [c['name'] for c in inspector.get_columns('generated_resumes')]
        with eng.connect() as conn:
            if 'revisions' not in existing_cols:
                logger.info("Migrating: adding 'revisions' column to generated_resumes")
                conn.execute(text(
                    "ALTER TABLE generated_resumes ADD COLUMN revisions JSON DEFAULT '[]'::json"
                ))
                conn.commit()
            if 'current_content' not in existing_cols:
                logger.info("Migrating: adding 'current_content' column to generated_resumes")
                conn.execute(text(
                    "ALTER TABLE generated_resumes ADD COLUMN current_content TEXT"
                ))
                conn.commit()
            if 'user_id' not in existing_cols:
                logger.info("Migrating: adding 'user_id' column to generated_resumes")
                conn.execute(text(
                    "ALTER TABLE generated_resumes ADD COLUMN user_id INTEGER REFERENCES users(id)"
                ))
                conn.commit()

    # Check jobs table for missing columns (public_job_id)
    if 'jobs' in inspector.get_table_names():
        existing_cols = [c['name'] for c in inspector.get_columns('jobs')]
        with eng.connect() as conn:
            if 'public_job_id' not in existing_cols:
                logger.info("Migrating: adding 'public_job_id' column to jobs")
                # Use VARCHAR(32) for both SQLite and PostgreSQL — SQLite is type-affinity loose.
                conn.execute(text(
                    "ALTER TABLE jobs ADD COLUMN public_job_id VARCHAR(32)"
                ))
                conn.commit()
                # Backfill any existing rows with a unique code
                rows = conn.execute(text("SELECT id FROM jobs WHERE public_job_id IS NULL")).fetchall()
                for row in rows:
                    job_id = row[0]
                    for _ in range(10):  # try up to 10 times to dodge the rare collision
                        candidate = generate_public_job_id()
                        existing = conn.execute(
                            text("SELECT 1 FROM jobs WHERE public_job_id = :pid"),
                            {"pid": candidate},
                        ).first()
                        if not existing:
                            conn.execute(
                                text("UPDATE jobs SET public_job_id = :pid WHERE id = :id"),
                                {"pid": candidate, "id": job_id},
                            )
                            break
                conn.commit()

            # Add unique index on public_job_id (idempotent)
            try:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_jobs_public_job_id ON jobs (public_job_id)"
                ))
                conn.commit()
            except Exception as e:
                logger.debug(f"Unique index on public_job_id may already exist: {e}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
