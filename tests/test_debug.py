"""Tests for Autotask troubleshooting diagnostics pages."""

from __future__ import annotations

from fastapi.testclient import TestClient

from job_logger import database
from job_logger.models import Job, SubmissionAttempt
from job_logger.enums import JobStatus
from job_logger.services.jobs import get_active_job
from tests.conftest import extract_csrf_token


def test_debug_route_requires_login(client: TestClient) -> None:
    """Anonymous users should be redirected to login for debug diagnostics."""

    response = client.get("/debug", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_debug_route_shows_autotask_attempts(authenticated_client: TestClient) -> None:
    """Authenticated users should see submission attempts and connection diagnostics."""

    start_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(start_page_response.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token, "ticket_number": "T20260326.0018"},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    description_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "Checked connection diagnostics for one test submission."},
    )
    assert description_response.status_code == 200

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
            "ticket_number": "T20260326.0018",
            "ticket_status": "complete",
            "start_date": "2026-06-16",
            "start_time": "08:00",
            "end_date": "2026-06-16",
            "end_time": "08:15",
            "summary_notes": "Checked connection diagnostics for one test submission.",
        },
        follow_redirects=False,
    )
    assert accept_response.status_code == 303

    with database.SessionLocal() as database_session:
        attempts = list(database_session.query(SubmissionAttempt).where(SubmissionAttempt.job_id == active_job_id).all())
        assert len(attempts) == 1
        assert attempts[0].succeeded is True

    debug_response = authenticated_client.get("/debug")
    assert debug_response.status_code == 200
    assert "Autotask debug" in debug_response.text
    assert attempts[0].id in debug_response.text
    assert "mock-time-entry" in debug_response.text


def test_debug_route_clears_ticket_data(authenticated_client: TestClient) -> None:
    """The debug reset endpoint removes all ticket-related data and submission attempts."""

    start_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(start_page_response.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.query(Job).where(Job.status == JobStatus.ACTIVE).first()
        assert active_job is not None
        active_job_id = active_job.id
        database_session.add(
            SubmissionAttempt(
                job_id=active_job_id,
                provider="mock",
                idempotency_key="debug-reset-attempt",
                succeeded=True,
                request_snapshot={},
            )
        )
        database_session.commit()

    debug_csrf_response = authenticated_client.get("/debug")
    debug_csrf_token = extract_csrf_token(debug_csrf_response.text)

    reset_response = authenticated_client.post(
        "/debug/tickets/reset",
        data={"csrf_token": debug_csrf_token},
        follow_redirects=False,
    )
    assert reset_response.status_code == 303

    with database.SessionLocal() as database_session:
        reset_job = database_session.get(Job, active_job_id)
        assert reset_job is not None
        assert reset_job.ticket_number is None
        assert reset_job.ticket_status is None
        assert reset_job.autotask_provider is None
        assert reset_job.autotask_external_id is None
        assert reset_job.autotask_error is None
        assert reset_job.autotask_submitted_at_utc is None
        attempts_remaining = database_session.query(SubmissionAttempt).where(SubmissionAttempt.job_id == active_job_id).count()
        assert attempts_remaining == 0
