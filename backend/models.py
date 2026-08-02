import os
import logging
import secrets
from pathlib import Path

from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Index
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

    # Billing
    # plan: 'free' | 'pro'. Defaults to 'free' for new users. Existing users
    # are grandfathered to 'pro' on first migration run (see _run_migrations).
    plan = Column(String(32), default="free", nullable=False, index=True)
    plan_grandfathered = Column(Boolean, default=False, nullable=False)
    # Stripe customer id (set on first checkout session creation)
    stripe_customer_id = Column(String(128), nullable=True, index=True)

    # Relationships
    jobs = relationship("Job", back_populates="user")
    base_resumes = relationship("BaseResume", back_populates="user")
    base_cover_letters = relationship("BaseCoverLetter", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan")
    usage_events = relationship("UsageEvent", back_populates="user", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    public_job_id = Column(String(32), unique=True, index=True, nullable=True)  # Globally unique short code
    company = Column(String, nullable=False, index=True)
    position = Column(String, nullable=False, index=True)
    location = Column(String, index=True)
    salary = Column(String)  # Free-text salary string (kept for anything that can't be structured)
    remote = Column(String, index=True)  # Remote, Hybrid, On-site

    # Structured pay range (parsed from salary text where possible). Separate
    # from the free-text `salary` column so jobs can be sorted by pay.
    pay_range_min = Column(Integer, nullable=True)
    pay_range_max = Column(Integer, nullable=True)
    pay_currency = Column(String, default="USD")
    pay_period = Column(String, nullable=True)  # 'annual' | 'hourly' | 'monthly'

    # Application deadline parsed from the posting (sortable; no reminders in v1).
    application_deadline = Column(DateTime, nullable=True, index=True)

    # Job description fields
    job_url = Column(String)
    job_description_raw = Column(Text)  # Original posting text
    job_description_parsed = Column(Text)  # Cleaned/parsed version
    requirements = Column(JSON)  # Must have and nice to have
    responsibilities = Column(JSON)
    keywords = Column(JSON)
    required_credentials = Column(JSON)  # Also surfaced as a structured list

    # Source tracking
    source_type = Column(String)  # 'url' or 'text'
    source_url = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    applications = relationship("JobApplication", back_populates="job", cascade="all, delete-orphan")
    resumes = relationship("GeneratedResume", back_populates="job", cascade="all, delete-orphan")
    cover_letters = relationship("GeneratedCoverLetter", back_populates="job", cascade="all, delete-orphan")
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

    # Template-only fields (nullable; populated when resume_type='template').
    # atoms_json: list of style atoms (from backend/template_engine.py).
    # docx_base64: original DOCX bytes so the composer can reuse the
    # template's styles.xml/numbering.xml/theme1.xml exactly.
    atoms_json = Column(JSON, nullable=True)
    docx_base64 = Column(Text, nullable=True)


class GeneratedResume(Base):
    """Generated resume with revision history, linked to a job"""
    __tablename__ = "generated_resumes"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    current_content = Column(Text)  # Latest version of the resume (plain text fallback)
    revisions = Column(JSON, default=list)  # List of {version, content, feedback, timestamp}
    # Template-driven structured output (one row = latest). Each revision may
    # also carry its own structured_content + atoms_used in the JSON list above.
    structured_content = Column(JSON, nullable=True)
    atoms_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="resumes")


class BaseCoverLetter(Base):
    """Stored example cover letters (voice/tone reference for the generator).

    Parallel in structure to BaseResume but simpler: cover letters have no
    template/DOCX variant in v1 — only example letters used for tone.
    """
    __tablename__ = "base_cover_letters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # Filename or user-provided name
    letter_type = Column(String, nullable=False)  # 'example' (only variant in v1)
    content = Column(Text)  # The actual cover letter text (or extracted from DOCX)
    source = Column(String, default="upload")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user = relationship("User", back_populates="base_cover_letters")
    created_at = Column(DateTime, default=datetime.utcnow)


class GeneratedCoverLetter(Base):
    """Generated cover letter with revision history, linked to a job.

    Mirrors GeneratedResume: one row per job, revisions is a versioned list
    carrying the user feedback that produced each version.
    """
    __tablename__ = "generated_cover_letters"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    current_content = Column(Text)  # Latest version (plain text)
    revisions = Column(JSON, default=list)  # List of {version, content, feedback, model, timestamp}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="cover_letters")


class ArtifactScore(Base):
    """Persisted scores from ATS + industry-panel agents.

    One row per (artifact_type, artifact_id, score_type). artifact_id is a
    soft FK to either generated_resumes.id or generated_cover_letters.id
    (polymorphic via artifact_type; no DB-level FK constraint so an artifact
    can be deleted without orphans blocking, the app filters by existence).
    """
    __tablename__ = "artifact_scores"
    __table_args__ = (
        Index("ix_artifact_scores_artifact", "artifact_type", "artifact_id", "score_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    artifact_type = Column(String, nullable=False)  # 'resume' | 'cover_letter'
    artifact_id = Column(Integer, nullable=False)  # FK to generated_resumes or generated_cover_letters
    score_type = Column(String, nullable=False)  # 'ats' | 'industry_panel'
    scores = Column(JSON)  # ATS: {overall, parseability, keyword_match, search_relevance}; panel: {overall, engineering, product, domain, recruiter, composite}
    issues = Column(JSON)  # List of issue strings
    recommendations = Column(JSON)  # List of recommendation strings
    model_used = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Subscription(Base):
    """Active Stripe subscription for a user. One row per user (latest)."""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    stripe_customer_id = Column(String(128), nullable=True, index=True)
    stripe_subscription_id = Column(String(128), nullable=True, unique=True, index=True)
    stripe_price_id = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="incomplete")  # active, trialing, past_due, canceled, unpaid, incomplete, incomplete_expired
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    canceled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="subscription")


class UsageEvent(Base):
    """A single counted use of a billable action. Inserted when a generation
    succeeds (not on failure). The current month is determined by created_at
    via usage counting helpers in billing.py.
    """
    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # 'resume_generation' is the only counted event type for now.
    event_type = Column(String(64), nullable=False, default="resume_generation")
    # Optional reference to the entity this event is associated with (e.g., job id).
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    # Snapshot of plan at the time of the event — useful for analytics.
    plan_at_event = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="usage_events")


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
    """Initialize/migrate the database via Alembic.

    On a fresh DB: `alembic upgrade head` creates all tables from the
    baseline migration.

    On an existing DB that predates Alembic (no `alembic_version` table):
    stamp it at the baseline revision so the schema is marked as current
    without trying to recreate existing tables, then upgrade to head.

    On a DB already tracked by Alembic: `alembic upgrade head` applies any
    pending migrations.

    Falls back to Base.metadata.create_all only if Alembic can't run
    (e.g. package missing in a stripped dev env) — that path creates
    missing tables but does NOT run column-level migrations.
    """
    try:
        _run_alembic_upgrade()
    except Exception as e:
        logger.error(f"Alembic migration failed: {e}")
        if not DATABASE_URL:
            raise  # SQLite should always work
        logger.warning("PostgreSQL migration failed during startup; will retry on first request")


def _run_alembic_upgrade():
    """Run `alembic upgrade head` against the app's engine.

    If the DB has tables but no alembic_version table, it predates Alembic
    (the existing production DB). Stamp it at the baseline revision so we
    don't try to recreate existing tables, then upgrade to head.

    Schema changes (incl. billing columns, subscription/usage_event tables,
    grandfather backfill) live in Alembic revisions under
    `backend/alembic/versions/`. Do not hand-write ALTER TABLE here —
    see AGENTS.md "Never hand-write ALTER TABLE".
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    has_alembic_version = "alembic_version" in tables
    has_app_tables = any(t in tables for t in ("users", "jobs", "job_applications"))

    if has_app_tables and not has_alembic_version:
        # Existing DB that predates Alembic (e.g. the production DB created
        # by the old hand-rolled migrations). Stamp it at the baseline
        # revision so alembic doesn't try to recreate the existing tables.
        logger.info("Existing DB without alembic_version — stamping at baseline")
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(Path(__file__).parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
        cfg.set_main_option("sqlalchemy.url", str(engine.url))
        command.stamp(cfg, "head")
        logger.info("Stamped DB at baseline revision")
    elif not has_app_tables and not has_alembic_version:
        # Truly fresh DB — let alembic create everything from the baseline.
        logger.info("Fresh DB — running alembic upgrade head")
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(Path(__file__).parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
        cfg.set_main_option("sqlalchemy.url", str(engine.url))
        command.upgrade(cfg, "head")
        logger.info("Fresh DB created via alembic upgrade head")
    else:
        # DB already tracked by Alembic — apply pending migrations.
        logger.info("Running alembic upgrade head (apply pending migrations)")
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(Path(__file__).parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
        cfg.set_main_option("sqlalchemy.url", str(engine.url))
        command.upgrade(cfg, "head")
        logger.info("Migrations applied")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
