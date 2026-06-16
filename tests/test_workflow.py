"""End-to-end tests for the local job workflow in mock provider mode."""

from __future__ import annotations

from datetime import timedelta
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

    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token, "ticket_number": "t20260326.0018"},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id
        assert active_job.ticket_number == "T20260326.0018"

    text_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "Replaced a failed workstation power supply."},
    )
    assert text_response.status_code == 200

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Energy"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    assert 'value="T20260326.0018"' in review_page_response.text
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
        },
        follow_redirects=False,
    )
    assert accept_response.status_code == 303

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.status == JobStatus.SUBMITTED
        assert job.summary_notes == "Replaced a failed workstation power supply."
        assert job.transcription_status == TranscriptionStatus.SUCCEEDED
        assert job.autotask_external_id == f"mock-time-entry-{active_job_id}"

        attempts = database_session.query(SubmissionAttempt).filter_by(job_id=active_job_id).all()
        assert len(attempts) == 1
        assert attempts[0].succeeded is True


def test_active_job_completion_requires_client_name(authenticated_client: TestClient) -> None:
    """Jobs without a client name cannot be moved from active to review."""

    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token, "ticket_number": "t20260326.0018"},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    failed_end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert failed_end_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.ACTIVE

    succeeded_end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Required Client"},
        follow_redirects=False,
    )
    assert succeeded_end_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.READY_FOR_REVIEW


def test_mobile_active_job_ticket_number_update(authenticated_client: TestClient) -> None:
    """The mobile page can save an optional Autotask ticket number during active work."""

    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id
        assert active_job.ticket_number is None

    save_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "ticket_number": "t20260326.0018"},
        follow_redirects=False,
    )
    assert save_ticket_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        assert active_job.ticket_number == "T20260326.0018"


def test_mobile_active_job_ticket_update_preserves_client_name(authenticated_client: TestClient) -> None:
    """Saving a ticket number from the active card should not erase the original client name."""

    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token, "ticket_number": "T20260326.0018", "client_name": "North Bay"},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id
        assert active_job.client_name == "North Bay"

    save_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "ticket_number": "T20260616.0001"},
        follow_redirects=False,
    )
    assert save_ticket_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.ticket_number == "T20260616.0001"
        assert active_job.client_name == "North Bay"


def test_mobile_active_job_rounded_start_can_be_adjusted(authenticated_client: TestClient) -> None:
    """The active job rounded start time can be incremented in 15-minute steps."""

    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)
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
        original_start = active_job.rounded_start_utc

    adjust_response = authenticated_client.post(
        f"/jobs/{active_job_id}/start-time/adjust",
        data={"csrf_token": csrf_token, "delta_minutes": 15},
        follow_redirects=False,
    )
    assert adjust_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.rounded_start_utc == original_start + timedelta(minutes=15)


def test_review_detail_force_purge_removes_job_and_attempts(authenticated_client: TestClient) -> None:
    """A selected review job can be permanently purged from the detail view."""

    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    text_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "Purge workflow test notes"},
    )
    assert text_response.status_code == 200

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Test Client"},
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
            "summary_notes": "Purge workflow test notes",
        },
        follow_redirects=False,
    )
    assert accept_response.status_code == 303

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert len(database_session.query(SubmissionAttempt).where(SubmissionAttempt.job_id == active_job_id).all()) == 1

    purge_response = authenticated_client.post(
        f"/review/{active_job_id}/purge",
        data={"csrf_token": review_csrf_token},
        follow_redirects=False,
    )
    assert purge_response.status_code == 303
    assert purge_response.headers["location"] == "/review"

    with database.SessionLocal() as database_session:
        assert database_session.get(Job, active_job_id) is None
        remaining_attempts = database_session.query(SubmissionAttempt).where(SubmissionAttempt.job_id == active_job_id).count()
        assert remaining_attempts == 0


def test_review_detail_force_purge_rejects_active_job(authenticated_client: TestClient) -> None:
    """Active jobs cannot be force-purged from the review endpoint."""

    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    purge_response = authenticated_client.post(
        f"/review/{active_job_id}/purge",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert purge_response.status_code == 303
    assert purge_response.headers["location"] == f"/review/{active_job_id}"

    with database.SessionLocal() as database_session:
        assert database_session.get(Job, active_job_id) is not None


def test_manual_summary_carries_to_review_on_completion(authenticated_client: TestClient) -> None:
    """Text typed in the mobile summary field persists when work is ended."""

    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token, "ticket_number": "T20260326.0018", "client_name": "Acme Energy"},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Energy", "summary_notes": "Prepared and repaired the UPS with two-hour follow up"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    assert "Prepared and repaired the UPS with two-hour follow up" in review_page_response.text

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.summary_notes == "Prepared and repaired the UPS with two-hour follow up"
        assert reviewed_job.client_name == "Acme Energy"


def test_mobile_allows_two_active_jobs(authenticated_client: TestClient) -> None:
    """Only two jobs can remain active at the same time."""

    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    first_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token, "ticket_number": "T20260326.0018", "client_name": "Site A"},
        follow_redirects=False,
    )
    assert first_response.status_code == 303

    second_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token, "ticket_number": "T20260616.0001", "client_name": "Site B"},
        follow_redirects=False,
    )
    assert second_response.status_code == 303

    third_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token, "ticket_number": "T20260616.0002", "client_name": "Site C"},
        follow_redirects=False,
    )
    assert third_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_jobs = database_session.query(Job).where(Job.status == JobStatus.ACTIVE).all()
        assert len(active_jobs) == 2
        active_slots = {job.job_slot for job in active_jobs if job.job_slot is not None}
        assert active_slots == {1, 2}
        client_names = {job.client_name for job in active_jobs}
        assert "Site A" in client_names
        assert "Site B" in client_names
