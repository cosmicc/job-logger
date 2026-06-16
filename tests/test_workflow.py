"""End-to-end tests for the local job workflow in mock provider mode."""

from __future__ import annotations

from fastapi.testclient import TestClient

from job_logger import database
from job_logger.enums import JobStatus, TranscriptionStatus
from job_logger.models import Job, SubmissionAttempt
from job_logger.services.jobs import get_active_job
from tests.conftest import extract_csrf_token


def test_login_rejects_missing_csrf(client: TestClient) -> None:
    """State-changing login requests require CSRF protection."""

    response = client.post("/login", data={"username": "admin", "password": "test-password"})

    assert response.status_code == 403


def test_complete_mock_job_workflow(authenticated_client: TestClient) -> None:
    """A job can be started, described, ended, reviewed, and mock-submitted."""

    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    text_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"description_text": "Replaced a failed workstation power supply."},
    )
    assert text_response.status_code == 200

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)

    accept_response = authenticated_client.post(
        f"/review/{active_job_id}/accept",
        data={
            "csrf_token": review_csrf_token,
            "ticket_number": "T20260616.0001",
            "ticket_status": "complete",
            "start_date": "2026-06-16",
            "start_time": "08:00",
            "end_date": "2026-06-16",
            "end_time": "08:15",
            "summary_notes": "Replaced a failed workstation power supply.",
            "description_text": "Replaced a failed workstation power supply.",
        },
        follow_redirects=False,
    )
    assert accept_response.status_code == 303

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.status == JobStatus.SUBMITTED
        assert job.transcription_status == TranscriptionStatus.SUCCEEDED
        assert job.autotask_external_id == f"mock-time-entry-{active_job_id}"

        attempts = database_session.query(SubmissionAttempt).filter_by(job_id=active_job_id).all()
        assert len(attempts) == 1
        assert attempts[0].succeeded is True

