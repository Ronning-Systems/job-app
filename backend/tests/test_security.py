"""Security regression tests for the Joblign API.

These tests verify fixes for:
  - IDOR on the Debug Resume API (only job owners can call it).
  - Stored XSS vector: the backend returns user content unchanged so the
    frontend is responsible for HTML escaping.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

# Ensure backend/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models


# Point the app at a throw-away SQLite file for these tests. We patch the
# engine after importing models.py (which builds the engine at import time)
# but before creating the TestClient so startup migrations run on the test DB.
TEST_DB_PATH = Path(__file__).resolve().parent / "test_security.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_PATH}"

_test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

models.engine = _test_engine
models.SessionLocal = TestingSessionLocal

# Now it's safe to import the app.
from auth import get_current_user  # noqa: E402
from main import app  # noqa: E402

import pytest
from fastapi.testclient import TestClient

from models import GeneratedResume, Job, JobApplication, SessionLocal, User  # noqa: E402


def _reset_test_db():
    """Drop and recreate the test SQLite schema."""
    # Close any open connections before deleting the file.
    _test_engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    models.Base.metadata.create_all(bind=_test_engine)


@pytest.fixture
def db():
    _reset_test_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        _test_engine.dispose()
        if TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()


def _make_user(db: SessionLocal, suffix: str) -> User:
    user = User(
        auth0_id=f"test-{suffix}-{uuid.uuid4().hex[:8]}",
        email=f"test-{suffix}@example.com",
        name=f"Test {suffix}",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_job_with_resume(db: SessionLocal, user: User) -> tuple[Job, GeneratedResume]:
    job = Job(
        company="Acme",
        position="Engineer",
        location="Remote",
        salary="$100k",
        user_id=user.id,
    )
    db.add(job)
    db.flush()

    application = JobApplication(job_id=job.id, stage="saved", user_id=user.id)
    db.add(application)

    resume = GeneratedResume(
        job_id=job.id,
        user_id=user.id,
        current_content="secret resume content",
        revisions=[{"version": 1}],
    )
    db.add(resume)

    db.commit()
    db.refresh(job)
    db.refresh(resume)
    return job, resume


def _client_for(user: User) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


class TestDebugResumeIdor:
    def test_owner_can_view_debug_resume(self, db):
        user = _make_user(db, "owner")
        job, resume = _make_job_with_resume(db, user)

        client = _client_for(user)
        try:
            response = client.get(f"/api/debug/resume/{job.id}")
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == job.id
            assert data["resume_count"] == 1
            assert data["resumes"][0]["current_content_length"] == len(resume.current_content)
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_other_user_cannot_view_debug_resume(self, db):
        owner = _make_user(db, "owner")
        attacker = _make_user(db, "attacker")
        job, _resume = _make_job_with_resume(db, owner)

        client = _client_for(attacker)
        try:
            response = client.get(f"/api/debug/resume/{job.id}")
            assert response.status_code == 404
            assert response.json()["detail"] == "Job not found"
        finally:
            app.dependency_overrides.pop(get_current_user, None)


class TestStoredXssBackend:
    def test_job_list_returns_user_content_unescaped(self, db):
        """The API must not double-escape stored user content.

        HTML escaping is the frontend's responsibility; the backend simply
        returns the values as stored. This test verifies that a malicious
        string stored in the DB is returned unchanged, which means the
        frontend's escapeHtml helper is the actual mitigation.
        """
        user = _make_user(db, "xss")
        malicious_company = '<script>alert("xss")</script>'
        malicious_position = '<img src=x onerror=alert(1)>'
        malicious_location = 'New York <body onload=alert(2)>'

        job = Job(
            company=malicious_company,
            position=malicious_position,
            location=malicious_location,
            user_id=user.id,
        )
        db.add(job)
        db.flush()
        application = JobApplication(job_id=job.id, stage="saved", user_id=user.id)
        db.add(application)
        db.commit()

        client = _client_for(user)
        try:
            response = client.get("/api/jobs")
            assert response.status_code == 200
            jobs = response.json()
            match = next((j for j in jobs if j["id"] == job.id), None)
            assert match is not None
            assert match["company"] == malicious_company
            assert match["position"] == malicious_position
            assert match["location"] == malicious_location
        finally:
            app.dependency_overrides.pop(get_current_user, None)


class TestStoredXssFrontendTemplate:
    """Lightweight checks that the tracker card and detail modal templates
    escape user-controlled fields before inserting them into innerHTML.
    """

    @pytest.fixture(scope="class")
    def index_html(self):
        path = Path(__file__).resolve().parents[2] / "static" / "index.html"
        return path.read_text()

    def test_render_job_item_escapes_user_fields(self, index_html):
        block = index_html.split("function renderJobItem(job)")[1].split("function formatDate")[0]
        assert "${escapeHtml(job.position)}" in block
        assert "${escapeHtml(job.company)}" in block
        assert "job.location ? escapeHtml(job.location)" in block
        assert "${escapeHtml(job.remote)}" in block

    def test_show_detail_escapes_user_fields(self, index_html):
        block = index_html.split("async function showDetail(id)")[1].split("// Event Listeners")[0]
        assert "${escapeHtml(fullJob.position)}" in block
        assert "${escapeHtml(fullJob.company)}" in block
        assert "fullJob.location ? escapeHtml(fullJob.location)" in block
        assert "fullJob.salary ? escapeHtml(fullJob.salary)" in block
        assert "fullJob.notes ? escapeHtml(fullJob.notes)" in block
        assert "${escapeHtml(desc)}" in block
        assert "${escapeHtml(JSON.stringify(fullJob.requirements" in block
        assert "${escapeHtml(JSON.stringify(fullJob.responsibilities" in block
        assert "${escapeHtml(JSON.stringify(fullJob.keywords" in block
        assert "fullJob.generated_resume ? escapeHtml(fullJob.generated_resume)" in block
        assert "fullJob.cover_letter ? escapeHtml(fullJob.cover_letter)" in block
        assert "escapeHtml(h.notes || h.text)" in block
