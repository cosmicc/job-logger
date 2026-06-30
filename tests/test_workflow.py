"""End-to-end tests for the local job workflow in mock provider mode."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from job_logger import database, ui
from job_logger.enums import EntryType, JobStatus, TicketStatus, TranscriptionStatus, WorkLocation
from job_logger.models import AuditEvent, Job, SubmissionAttempt, WebUser
from job_logger.services.ai_cleanup import AiCleanupResult
from job_logger.services.autotask import AutotaskSubmissionResult
from job_logger.services.jobs import get_active_job
from job_logger.time_utils import format_local_time, local_date_for
from tests.conftest import extract_csrf_token, login_as_super_admin


def create_submitted_mock_job(authenticated_client: TestClient, *, summary_notes: str = "Locked submitted job notes") -> tuple[str, str]:
    """Create a fully submitted mock Autotask job and return its ID plus CSRF token."""

    # csrf_token is the authenticated session token used by the state-changing
    # mobile and review requests in this helper.
    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    assert "Start Work" in mobile_page_response.text

    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        # active_job_id identifies the job that will move through the full
        # start, ticket selection, review, and mock submission workflow.
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    select_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    assert select_ticket_response.status_code == 200

    description_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": summary_notes},
    )
    assert description_response.status_code == 200

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)

    accept_response = authenticated_client.post(
        f"/review/{active_job_id}/accept",
        data={
            "csrf_token": review_csrf_token,
            "ticket_status": "complete",
            "job_date": "2026-06-16",
            "start_time": "08:00",
            "end_time": "08:15",
            "summary_notes": summary_notes,
        },
        follow_redirects=False,
    )
    assert accept_response.status_code == 303

    return active_job_id, review_csrf_token


class FailingDeleteAutotaskProvider:
    """Provider double that fails only the submitted-entry delete operation."""

    provider_name = "fake-autotask"

    def delete_time_entry(self, job: Job, external_id: str, *, resource_id: int) -> AutotaskSubmissionResult:
        """Return a safe remote delete failure without changing local state."""

        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=False,
            external_id=external_id,
            safe_error="Autotask refused to delete that time entry.",
            request_snapshot={
                "operation": "delete_time_entry",
                "job_id": job.id,
                "external_id": external_id,
                "resourceID": resource_id,
            },
        )


def enable_submit_from_work_in_progress(authenticated_client: TestClient) -> None:
    """Enable direct Work in Progress Autotask submission through `/config`."""

    config_response = authenticated_client.get("/config")
    csrf_token = extract_csrf_token(config_response.text)
    save_response = authenticated_client.post(
        "/config",
        headers={"Accept": "application/json", "X-CSRF-Token": csrf_token},
        data={"csrf_token": csrf_token, "submit_from_work_in_progress": "true"},
    )
    assert save_response.status_code == 200
    assert save_response.json()["submit_from_work_in_progress"] is True


def test_login_rejects_missing_csrf(client: TestClient) -> None:
    """State-changing login requests require CSRF protection."""

    response = client.post("/login", data={"username": "admin", "password": "test-password"})

    assert response.status_code == 403


def test_complete_mock_job_workflow(authenticated_client: TestClient) -> None:
    """A job can be started, described, ended, reviewed, and mock-submitted."""

    mobile_page_response = authenticated_client.get("/home")
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
        assert active_job.ticket_number is None

    text_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "Replaced a failed workstation power supply."},
    )
    assert text_response.status_code == 200
    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
        },
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    select_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    assert select_ticket_response.status_code == 200
    assert select_ticket_response.json() == {
        "ticket_number": "T20260616.0001",
        "ticket_title": "Mock open ticket for Acme Services",
        "ticket_description": "Mock ticket description for Acme Services.",
        "ticket_status": "in_progress",
        "ticket_status_label": "In Progress",
    }

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    assert "Mock open ticket for Acme Services" in review_page_response.text
    review_csrf_token = extract_csrf_token(review_page_response.text)

    accept_response = authenticated_client.post(
        f"/review/{active_job_id}/accept",
        data={
            "csrf_token": review_csrf_token,
            "ticket_status": "complete",
            "job_date": "2026-06-16",
            "start_time": "08:00",
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


def test_work_in_progress_can_submit_directly_to_autotask(authenticated_client: TestClient) -> None:
    """The opt-in workflow should submit from Work in Progress without review acceptance."""

    enable_submit_from_work_in_progress(authenticated_client)
    mobile_page_response = authenticated_client.get("/home")
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

    active_page_response = authenticated_client.get("/home")
    assert "Submit to Autotask" in active_page_response.text
    assert 'data-loading-message="Submitting to Autotask..."' in active_page_response.text

    text_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "Completed direct submit work."},
    )
    assert text_response.status_code == 200
    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
        },
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303
    select_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    assert select_ticket_response.status_code == 200

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "work_location": "on_site",
            "ticket_status": "complete",
            "summary_notes": "Completed direct submit work.",
        },
        follow_redirects=False,
    )
    assert end_response.status_code == 303
    assert end_response.headers["location"] == "/home"

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.status == JobStatus.SUBMITTED
        assert job.summary_notes == "Completed direct submit work."
        assert job.work_location == WorkLocation.ON_SITE
        assert job.ticket_status == TicketStatus.COMPLETE
        assert job.autotask_external_id == f"mock-time-entry-{active_job_id}"
        assert job.autotask_error is None

        attempts = database_session.query(SubmissionAttempt).filter_by(job_id=active_job_id).all()
        assert len(attempts) == 1
        assert attempts[0].succeeded is True
        assert attempts[0].request_snapshot["ticket_status"] == "complete"
        assert attempts[0].request_snapshot["work_location"] == "on_site"

        direct_submit_event = database_session.scalar(
            select(AuditEvent).where(
                AuditEvent.job_id == active_job_id,
                AuditEvent.action == "job.autotask.direct_submit",
            )
        )
        assert direct_submit_event is not None
        assert direct_submit_event.details["succeeded"] is True

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    assert review_page_response.status_code == 200
    assert f'action="/review/{active_job_id}/edit-entry"' in review_page_response.text
    assert f'action="/review/{active_job_id}/delete-entry"' in review_page_response.text
    assert f'formaction="/review/{active_job_id}/accept"' not in review_page_response.text


def test_ticket_note_can_be_submitted_from_review_without_time_fields(authenticated_client: TestClient) -> None:
    """A review entry can become a customer-visible ticket note before Autotask submission."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "entry_type": "ticket_note",
            "note_title": "Customer-facing update",
            "append_to_resolution": "true",
            "ticket_status": "in_progress",
            "summary_notes": "The customer can see this note.",
        },
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303
    select_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    assert select_ticket_response.status_code == 200
    text_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "The customer can see this note."},
    )
    assert text_response.status_code == 200

    active_page_response = authenticated_client.get("/home")
    active_html = active_page_response.text
    assert 'value="ticket_note"' in active_html
    assert "Note title" in active_html
    assert "Note description" in active_html
    assert "End Note" in active_html
    assert "Delete Note" in active_html
    assert 'data-work-location-card' in active_html
    assert 'work-location-card is-hidden' in active_html
    assert 'data-duration-row' in active_html

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "entry_type": "ticket_note",
            "note_title": "Customer-facing update",
            "append_to_resolution": "true",
            "ticket_status": "in_progress",
            "summary_notes": "The customer can see this note.",
        },
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_html = review_page_response.text
    review_csrf_token = extract_csrf_token(review_html)
    assert "Ticket note" in review_html
    assert "Note title" in review_html
    assert "Note description" in review_html
    assert "Delete note" in review_html
    assert 'review-work-location-card is-hidden' in review_html

    accept_response = authenticated_client.post(
        f"/review/{active_job_id}/accept",
        data={
            "csrf_token": review_csrf_token,
            "entry_type": "ticket_note",
            "ticket_status": "complete",
            "note_title": "Customer-facing update",
            "append_to_resolution": "true",
            "summary_notes": "The customer can see this note.",
        },
        follow_redirects=False,
    )
    assert accept_response.status_code == 303

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.status == JobStatus.SUBMITTED
        assert job.entry_type == EntryType.TICKET_NOTE
        assert job.note_title == "Customer-facing update"
        assert job.append_to_resolution is True
        assert job.summary_notes == "The customer can see this note."
        assert job.autotask_external_id == f"mock-ticket-note-{active_job_id}"

        attempt = database_session.query(SubmissionAttempt).filter_by(job_id=active_job_id).one()
        assert attempt.succeeded is True
        assert attempt.request_snapshot["entry_type"] == "ticket_note"
        assert attempt.request_snapshot["noteTitleLength"] == len("Customer-facing update")
        assert attempt.request_snapshot["noteDescriptionLength"] == len("The customer can see this note.")
        assert attempt.request_snapshot["appendToResolution"] is True


def test_submitted_ticket_note_can_be_updated_and_deleted(authenticated_client: TestClient) -> None:
    """Submitted ticket notes should update and delete the existing Autotask note ID."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "entry_type": "ticket_note",
            "note_title": "Original note",
            "append_to_resolution": "true",
            "ticket_status": "in_progress",
            "summary_notes": "Original note body.",
        },
        follow_redirects=False,
    )
    authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "entry_type": "ticket_note",
            "note_title": "Original note",
            "append_to_resolution": "true",
            "ticket_status": "in_progress",
            "summary_notes": "Original note body.",
        },
        follow_redirects=False,
    )
    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)
    authenticated_client.post(
        f"/review/{active_job_id}/accept",
        data={
            "csrf_token": review_csrf_token,
            "entry_type": "ticket_note",
            "ticket_status": "in_progress",
            "note_title": "Original note",
            "append_to_resolution": "true",
            "summary_notes": "Original note body.",
        },
        follow_redirects=False,
    )

    edit_response = authenticated_client.post(
        f"/review/{active_job_id}/edit-entry",
        data={
            "csrf_token": review_csrf_token,
            "entry_type": "ticket_note",
            "ticket_status": "follow_up",
            "note_title": "Updated note",
            "append_to_resolution": "false",
            "summary_notes": "Updated note body.",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code == 303

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.status == JobStatus.SUBMITTED
        assert job.entry_type == EntryType.TICKET_NOTE
        assert job.note_title == "Updated note"
        assert job.append_to_resolution is False
        attempts = database_session.query(SubmissionAttempt).filter_by(job_id=active_job_id).all()
        assert attempts[-1].request_snapshot["operation"] == "update_ticket_note"
        assert attempts[-1].request_snapshot["appendToResolution"] is False

    delete_response = authenticated_client.post(
        f"/review/{active_job_id}/delete-entry",
        data={"csrf_token": review_csrf_token},
        follow_redirects=False,
    )
    assert delete_response.status_code == 303

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.status == JobStatus.READY_FOR_REVIEW
        assert job.autotask_external_id is None
        attempts = database_session.query(SubmissionAttempt).filter_by(job_id=active_job_id).all()
        assert attempts[-1].request_snapshot["operation"] == "delete_ticket_note"


def test_direct_work_in_progress_ticket_note_submit(authenticated_client: TestClient) -> None:
    """Direct Work in Progress submission should support ticket notes."""

    enable_submit_from_work_in_progress(authenticated_client)
    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "entry_type": "ticket_note",
            "note_title": "Direct note",
            "append_to_resolution": "true",
            "ticket_status": "complete",
            "summary_notes": "Direct note body.",
        },
        follow_redirects=False,
    )
    authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    active_page_response = authenticated_client.get("/home")
    assert "Submit note" in active_page_response.text

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "entry_type": "ticket_note",
            "note_title": "Direct note",
            "append_to_resolution": "true",
            "ticket_status": "complete",
            "summary_notes": "Direct note body.",
        },
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.status == JobStatus.SUBMITTED
        assert job.entry_type == EntryType.TICKET_NOTE
        assert job.autotask_external_id == f"mock-ticket-note-{active_job_id}"
        attempt = database_session.query(SubmissionAttempt).filter_by(job_id=active_job_id).one()
        assert attempt.request_snapshot["entry_type"] == "ticket_note"


def test_direct_work_in_progress_submit_requires_autotask_fields(authenticated_client: TestClient) -> None:
    """Direct submit should keep the job active when required Autotask fields are missing."""

    enable_submit_from_work_in_progress(authenticated_client)
    mobile_page_response = authenticated_client.get("/home")
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
        json={"summary_notes": "Direct submit should require a ticket."},
    )
    assert text_response.status_code == 200
    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "ticket_status": "in_progress",
            "summary_notes": "Direct submit should require a ticket.",
        },
        follow_redirects=False,
    )
    assert end_response.status_code == 303
    assert end_response.headers["location"] == "/home"

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.ACTIVE
        assert active_job.rounded_end_utc is None
        assert active_job.autotask_external_id is None
        assert database_session.query(SubmissionAttempt).filter_by(job_id=active_job_id).count() == 0


def test_active_job_ai_cleanup_returns_replacement_text(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mobile AI cleanup returns cleaned text without exposing provider details."""

    monkeypatch.setattr(
        "job_logger.routes.mobile.cleanup_summary_text",
        lambda **_kwargs: AiCleanupResult(
            provider="gemini",
            model="test-cleanup-model",
            cleaned_text="Remote replaced the failed power supply and verified startup.",
        ),
    )
    mobile_page_response = authenticated_client.get("/home")
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

    cleanup_response = authenticated_client.post(
        f"/jobs/{active_job_id}/summary/cleanup",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "replaced bad power supply checked boot"},
    )

    assert cleanup_response.status_code == 200
    assert cleanup_response.json() == {
        "summary_notes": "Remote replaced the failed power supply and verified startup.",
        "description_text": "Remote replaced the failed power supply and verified startup.",
        "provider": "gemini",
        "model": "test-cleanup-model",
    }
    with database.SessionLocal() as database_session:
        audit_event = database_session.query(AuditEvent).filter_by(action="job.summary.ai_cleanup").one()
        assert audit_event.job_id == active_job_id
        assert audit_event.details["source"] == "mobile"
        assert audit_event.details["input_text_length"] == len("replaced bad power supply checked boot")
        assert "replaced bad power supply" not in str(audit_event.details)


def test_active_job_ai_cleanup_can_be_reverted_from_persisted_state(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Work in Progress cleanup stores a server-backed original for Revert cleanup."""

    monkeypatch.setattr(
        "job_logger.routes.mobile.cleanup_summary_text",
        lambda **_kwargs: AiCleanupResult(
            provider="gemini",
            model="test-cleanup-model",
            cleaned_text="Remote cleaned up the firewall notes.",
        ),
    )
    mobile_page_response = authenticated_client.get("/home")
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

    cleanup_response = authenticated_client.post(
        f"/jobs/{active_job_id}/summary/cleanup",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "remote firewall notes"},
    )
    assert cleanup_response.status_code == 200

    save_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": cleanup_response.json()["summary_notes"]},
    )
    assert save_response.status_code == 200

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.summary_notes == "Remote cleaned up the firewall notes."
        assert job.ai_cleanup_original_summary == "remote firewall notes"
        assert job.ai_cleanup_source == "mobile"

    revert_response = authenticated_client.post(
        f"/jobs/{active_job_id}/summary/cleanup/revert",
        headers={"X-CSRF-Token": csrf_token},
        json={},
    )

    assert revert_response.status_code == 200
    assert revert_response.json()["summary_notes"] == "remote firewall notes"
    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.summary_notes == "remote firewall notes"
        assert job.ai_cleanup_original_summary is None
        assert job.ai_cleanup_pending_summary is None
        reverted_event = database_session.query(AuditEvent).filter_by(action="job.summary.ai_cleanup_reverted").one()
        assert reverted_event.details["source"] == "mobile"
        assert reverted_event.details["restored_text_length"] == len("remote firewall notes")
        assert "remote firewall notes" not in str(reverted_event.details)


def test_active_job_ai_cleanup_revert_state_expires_on_home_render(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old Work in Progress cleanup undo text should be minimized automatically."""

    monkeypatch.setattr(
        "job_logger.routes.mobile.cleanup_summary_text",
        lambda **_kwargs: AiCleanupResult(
            provider="gemini",
            model="test-cleanup-model",
            cleaned_text="Remote cleaned up old undo notes.",
        ),
    )
    mobile_page_response = authenticated_client.get("/home")
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

    cleanup_response = authenticated_client.post(
        f"/jobs/{active_job_id}/summary/cleanup",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "old undo notes"},
    )
    assert cleanup_response.status_code == 200

    save_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": cleanup_response.json()["summary_notes"]},
    )
    assert save_response.status_code == 200

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        job.ai_cleanup_at_utc = datetime.now(UTC) - timedelta(hours=25)
        database_session.commit()

    refreshed_home_response = authenticated_client.get("/home")

    assert refreshed_home_response.status_code == 200
    assert "Revert cleanup" not in refreshed_home_response.text
    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.summary_notes == "Remote cleaned up old undo notes."
        assert job.ai_cleanup_original_summary is None
        assert job.ai_cleanup_pending_summary is None
        assert job.ai_cleanup_source is None
        assert job.ai_cleanup_at_utc is None


def test_review_ai_cleanup_allows_submitted_summary_replacement(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review cleanup can prepare submitted-entry text without patching Autotask."""

    monkeypatch.setattr(
        "job_logger.routes.review.cleanup_summary_text",
        lambda **_kwargs: AiCleanupResult(
            provider="grok",
            model="test-cleanup-model",
            cleaned_text="Remote updated the backup software and verified the next scheduled run.",
        ),
    )
    submitted_job_id, review_csrf_token = create_submitted_mock_job(authenticated_client)

    cleanup_response = authenticated_client.post(
        f"/review/{submitted_job_id}/summary/cleanup",
        headers={"X-CSRF-Token": review_csrf_token},
        json={"summary_notes": "Remote updated backup software verified next run"},
    )

    assert cleanup_response.status_code == 200
    assert cleanup_response.json()["summary_notes"] == "Remote updated the backup software and verified the next scheduled run."
    with database.SessionLocal() as database_session:
        job = database_session.get(Job, submitted_job_id)
        assert job is not None
        assert job.status == JobStatus.SUBMITTED
        assert job.summary_notes == "Locked submitted job notes"
        audit_event = database_session.query(AuditEvent).filter_by(action="job.summary.ai_cleanup").one()
        assert audit_event.details["source"] == "review"
        assert audit_event.details["job_status"] == "submitted"


def test_submitted_review_ai_cleanup_pending_text_survives_reload_and_reverts(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submitted Review cleanup keeps pending text reloadable without patching Autotask."""

    monkeypatch.setattr(ui, "settings", replace(ui.settings, ai_cleanup_enabled=True))
    monkeypatch.setattr(
        "job_logger.routes.review.cleanup_summary_text",
        lambda **_kwargs: AiCleanupResult(
            provider="grok",
            model="test-cleanup-model",
            cleaned_text="Remote cleaned submitted firewall notes.",
        ),
    )
    submitted_job_id, review_csrf_token = create_submitted_mock_job(authenticated_client)

    cleanup_response = authenticated_client.post(
        f"/review/{submitted_job_id}/summary/cleanup",
        headers={"X-CSRF-Token": review_csrf_token},
        json={"summary_notes": "Remote draft submitted firewall notes"},
    )

    assert cleanup_response.status_code == 200
    reloaded_review_response = authenticated_client.get(f"/review/{submitted_job_id}")
    assert reloaded_review_response.status_code == 200
    assert "Remote cleaned submitted firewall notes." in reloaded_review_response.text
    assert "Revert cleanup" in reloaded_review_response.text
    with database.SessionLocal() as database_session:
        job = database_session.get(Job, submitted_job_id)
        assert job is not None
        assert job.status == JobStatus.SUBMITTED
        assert job.summary_notes == "Locked submitted job notes"
        assert job.ai_cleanup_original_summary == "Remote draft submitted firewall notes"
        assert job.ai_cleanup_pending_summary == "Remote cleaned submitted firewall notes."

    revert_response = authenticated_client.post(
        f"/review/{submitted_job_id}/summary/cleanup/revert",
        headers={"X-CSRF-Token": review_csrf_token},
        json={},
    )

    assert revert_response.status_code == 200
    assert revert_response.json()["summary_notes"] == "Remote draft submitted firewall notes"
    with database.SessionLocal() as database_session:
        job = database_session.get(Job, submitted_job_id)
        assert job is not None
        assert job.status == JobStatus.SUBMITTED
        assert job.summary_notes == "Locked submitted job notes"
        assert job.ai_cleanup_original_summary is None
        assert job.ai_cleanup_pending_summary is None


def test_submitted_review_ai_cleanup_revert_state_expires_on_review_render(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old submitted Review cleanup drafts should not keep customer text forever."""

    monkeypatch.setattr(ui, "settings", replace(ui.settings, ai_cleanup_enabled=True))
    monkeypatch.setattr(
        "job_logger.routes.review.cleanup_summary_text",
        lambda **_kwargs: AiCleanupResult(
            provider="grok",
            model="test-cleanup-model",
            cleaned_text="Remote cleaned submitted notes that should expire.",
        ),
    )
    submitted_job_id, review_csrf_token = create_submitted_mock_job(authenticated_client)

    cleanup_response = authenticated_client.post(
        f"/review/{submitted_job_id}/summary/cleanup",
        headers={"X-CSRF-Token": review_csrf_token},
        json={"summary_notes": "Remote submitted notes before cleanup"},
    )
    assert cleanup_response.status_code == 200

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, submitted_job_id)
        assert job is not None
        job.ai_cleanup_at_utc = datetime.now(UTC) - timedelta(hours=25)
        database_session.commit()

    reloaded_review_response = authenticated_client.get(f"/review/{submitted_job_id}")

    assert reloaded_review_response.status_code == 200
    assert "Remote cleaned submitted notes that should expire." not in reloaded_review_response.text
    assert "Remote. Locked submitted job notes" in reloaded_review_response.text
    assert "Revert cleanup" not in reloaded_review_response.text
    with database.SessionLocal() as database_session:
        job = database_session.get(Job, submitted_job_id)
        assert job is not None
        assert job.summary_notes == "Locked submitted job notes"
        assert job.ai_cleanup_original_summary is None
        assert job.ai_cleanup_pending_summary is None
        assert job.ai_cleanup_source is None
        assert job.ai_cleanup_at_utc is None


def test_submitted_review_page_allows_controlled_entry_edits(authenticated_client: TestClient) -> None:
    """Submitted jobs keep identity protected while allowing explicit entry edits."""

    submitted_job_id, _review_csrf_token = create_submitted_mock_job(authenticated_client)

    review_page_response = authenticated_client.get(f"/review/{submitted_job_id}")
    review_html = review_page_response.text

    assert review_page_response.status_code == 200
    assert "Work Review" in review_html
    assert "Job review" not in review_html
    assert "Submitted Autotask entry" in review_html
    assert "Autotask time entry:" not in review_html
    assert f"mock-time-entry-{submitted_job_id}" not in review_html
    assert "can be updated with Submit changes" in review_html
    assert 'class="review-form review-form-submitted"' in review_html
    assert 'class="review-action-stack"' in review_html
    assert 'class="button-pair-row review-action-row"' in review_html
    assert f'form="review-form-{submitted_job_id}"' in review_html
    assert 'class="date-input-shell"' in review_html
    assert '<span class="date-relative-label" data-review-date-weekday-label></span>' in review_html
    assert re.search(r'<select(?=[^>]*name="ticket_status")(?![^>]*disabled)', review_html)
    assert re.search(r'<input(?=[^>]*name="job_date")(?![^>]*disabled)', review_html)
    assert re.search(r'<input(?=[^>]*name="start_time")(?![^>]*disabled)', review_html)
    assert re.search(r'<input(?=[^>]*name="work_location")(?=[^>]*value="remote")(?![^>]*disabled)', review_html)
    assert re.search(r'<textarea(?=[^>]*name="summary_notes")(?![^>]*disabled)', review_html)
    assert "Remote. Locked submitted job notes" in review_html
    assert "Submit changes" in review_html
    assert f'action="/review/{submitted_job_id}/edit-entry"' in review_html
    assert f'formaction="/review/{submitted_job_id}/edit-entry"' in review_html
    assert f'action="/review/{submitted_job_id}/delete-entry"' in review_html
    assert "Delete From Autotask" in review_html
    assert 'data-confirm-message="This will delete the existing Autotask time entry and return this job to review. Continue?"' in review_html
    assert f'formaction="/review/{submitted_job_id}/save"' not in review_html
    assert f'formaction="/review/{submitted_job_id}/accept"' not in review_html
    assert f'formaction="/review/{submitted_job_id}/retry"' not in review_html
    assert f'action="/review/{submitted_job_id}/reject"' not in review_html
    assert f'action="/review/{submitted_job_id}/purge"' not in review_html
    assert "<details class=\"audit-panel audit-timeline\"" in review_html
    assert "<summary>" in review_html


def test_submitted_jobs_allow_edit_entry_but_block_local_mutations(authenticated_client: TestClient) -> None:
    """Submitted jobs update the external entry only through the edit-entry route."""

    original_summary_notes = "Submitted values must stay unchanged"
    submitted_job_id, review_csrf_token = create_submitted_mock_job(
        authenticated_client,
        summary_notes=original_summary_notes,
    )

    # changed_review_data represents a crafted form post that tries to change
    # review values after the Autotask time entry already exists.
    changed_review_data = {
        "csrf_token": review_csrf_token,
        "ticket_status": "follow_up",
        "job_date": "2026-06-17",
        "start_time": "09:00",
        "end_time": "09:30",
        "summary_notes": "Tampered submitted notes",
    }

    save_response = authenticated_client.post(
        f"/review/{submitted_job_id}/save",
        data=changed_review_data,
        follow_redirects=False,
    )
    accept_response = authenticated_client.post(
        f"/review/{submitted_job_id}/accept",
        data=changed_review_data,
        follow_redirects=False,
    )
    retry_response = authenticated_client.post(
        f"/review/{submitted_job_id}/retry",
        data=changed_review_data,
        follow_redirects=False,
    )
    removed_reject_route_response = authenticated_client.post(
        f"/review/{submitted_job_id}/reject",
        data={"csrf_token": review_csrf_token},
        follow_redirects=False,
    )
    purge_response = authenticated_client.post(
        f"/review/{submitted_job_id}/purge",
        data={"csrf_token": review_csrf_token},
        follow_redirects=False,
    )
    submitted_local_purge_response = authenticated_client.post(
        f"/review/{submitted_job_id}/purge-submitted-local",
        data={"csrf_token": review_csrf_token},
        follow_redirects=False,
    )
    ticket_selection_response = authenticated_client.post(
        f"/review/{submitted_job_id}/ticket",
        headers={"X-CSRF-Token": review_csrf_token},
        json={"ticket_number": "T20260616.0002"},
    )
    edit_entry_response = authenticated_client.post(
        f"/review/{submitted_job_id}/edit-entry",
        data=changed_review_data,
        follow_redirects=False,
    )

    assert save_response.status_code == 303
    assert accept_response.status_code == 303
    assert retry_response.status_code == 303
    assert removed_reject_route_response.status_code == 404
    assert purge_response.status_code == 303
    assert purge_response.headers["location"] == f"/review/{submitted_job_id}"
    assert submitted_local_purge_response.status_code == 303
    assert submitted_local_purge_response.headers["location"] == f"/review/{submitted_job_id}"
    assert ticket_selection_response.status_code == 400
    assert "cannot be deleted locally, resent, or have ticket identity changed" in ticket_selection_response.json()["detail"]
    assert edit_entry_response.status_code == 303

    with database.SessionLocal() as database_session:
        submitted_job = database_session.get(Job, submitted_job_id)
        assert submitted_job is not None
        assert submitted_job.status == JobStatus.SUBMITTED
        assert submitted_job.summary_notes == "Tampered submitted notes"
        assert submitted_job.ticket_status.value == "follow_up"
        assert submitted_job.autotask_external_id == f"mock-time-entry-{submitted_job_id}"

        update_event = database_session.query(AuditEvent).filter_by(action="job.autotask.entry_update").one()
        assert update_event.job_id == submitted_job_id
        assert update_event.details["succeeded"] is True

        # The original create attempt and the explicit edit-entry update attempt
        # are recorded; blocked save/accept/retry posts must not create more.
        submission_attempts = (
            database_session.query(SubmissionAttempt)
            .filter_by(job_id=submitted_job_id)
            .order_by(SubmissionAttempt.created_at_utc)
            .all()
        )
        assert len(submission_attempts) == 2
        assert submission_attempts[0].succeeded is True
        assert submission_attempts[1].succeeded is True
        assert submission_attempts[1].request_snapshot["operation"] == "update_time_entry"
        assert submission_attempts[1].request_snapshot["ticketStatusUpdateAttempted"] is True


def test_submitted_entry_edit_without_status_change_reasserts_ticket_status(authenticated_client: TestClient) -> None:
    """Edit Entry reasserts the selected ticket status even when local status is unchanged."""

    submitted_job_id, review_csrf_token = create_submitted_mock_job(
        authenticated_client,
        summary_notes="Submitted entry can be corrected without status changes",
    )
    unchanged_status_review_data = {
        "csrf_token": review_csrf_token,
        "ticket_status": "complete",
        "job_date": "2026-06-16",
        "start_time": "08:00",
        "end_time": "08:30",
        "summary_notes": "Remote corrected submitted notes without changing ticket status",
    }

    edit_entry_response = authenticated_client.post(
        f"/review/{submitted_job_id}/edit-entry",
        data=unchanged_status_review_data,
        follow_redirects=False,
    )

    assert edit_entry_response.status_code == 303
    assert edit_entry_response.headers["location"] == f"/review/{submitted_job_id}"

    with database.SessionLocal() as database_session:
        submitted_job = database_session.get(Job, submitted_job_id)
        assert submitted_job is not None
        assert submitted_job.status == JobStatus.SUBMITTED
        assert submitted_job.ticket_status.value == "complete"
        assert submitted_job.summary_notes == "corrected submitted notes without changing ticket status"

        submission_attempts = (
            database_session.query(SubmissionAttempt)
            .filter_by(job_id=submitted_job_id)
            .order_by(SubmissionAttempt.created_at_utc)
            .all()
        )
        assert len(submission_attempts) == 2
        assert submission_attempts[1].succeeded is True
        assert submission_attempts[1].request_snapshot["operation"] == "update_time_entry"
        assert submission_attempts[1].request_snapshot["ticketStatusUpdateAttempted"] is True


def test_submitted_job_delete_entry_removes_autotask_entry_only(authenticated_client: TestClient) -> None:
    """Delete From Autotask moves a submitted job back to review without deleting it locally."""

    submitted_job_id, review_csrf_token = create_submitted_mock_job(
        authenticated_client,
        summary_notes="Submitted notes that should remain local.",
    )

    delete_entry_response = authenticated_client.post(
        f"/review/{submitted_job_id}/delete-entry",
        data={"csrf_token": review_csrf_token},
        follow_redirects=False,
    )

    assert delete_entry_response.status_code == 303
    assert delete_entry_response.headers["location"] == f"/review/{submitted_job_id}"

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, submitted_job_id)
        assert reviewed_job is not None
        assert reviewed_job.status == JobStatus.READY_FOR_REVIEW
        assert reviewed_job.summary_notes == "Submitted notes that should remain local."
        assert reviewed_job.ticket_number == "T20260616.0001"
        assert reviewed_job.autotask_external_id is None
        assert reviewed_job.autotask_submitted_at_utc is None
        assert reviewed_job.autotask_error is None

        delete_event = database_session.query(AuditEvent).filter_by(action="job.autotask.entry_deleted").one()
        assert delete_event.job_id == submitted_job_id
        assert delete_event.details["succeeded"] is True
        assert delete_event.details["external_id"] == f"mock-time-entry-{submitted_job_id}"
        assert delete_event.details["status"] == "ready_for_review"

        submission_attempts = (
            database_session.query(SubmissionAttempt)
            .filter_by(job_id=submitted_job_id)
            .order_by(SubmissionAttempt.created_at_utc)
            .all()
        )
        assert len(submission_attempts) == 2
        assert submission_attempts[0].succeeded is True
        assert submission_attempts[1].succeeded is True
        assert submission_attempts[1].external_id == f"mock-time-entry-{submitted_job_id}"
        assert submission_attempts[1].request_snapshot["operation"] == "delete_time_entry"

    updated_review_page_response = authenticated_client.get(f"/review/{submitted_job_id}")
    updated_review_html = updated_review_page_response.text
    assert "Delete From Autotask" not in updated_review_html
    assert f'formaction="/review/{submitted_job_id}/accept"' in updated_review_html


def test_failed_delete_from_autotask_prompts_local_review_purge(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed remote delete can fall back to an explicit local-only purge."""

    submitted_job_id, review_csrf_token = create_submitted_mock_job(
        authenticated_client,
        summary_notes="Submitted notes for failed remote delete.",
    )
    monkeypatch.setattr(
        "job_logger.services.jobs.get_autotask_provider",
        lambda: FailingDeleteAutotaskProvider(),
    )

    delete_entry_response = authenticated_client.post(
        f"/review/{submitted_job_id}/delete-entry",
        data={"csrf_token": review_csrf_token},
        follow_redirects=False,
    )

    assert delete_entry_response.status_code == 303
    assert delete_entry_response.headers["location"] == f"/review/{submitted_job_id}"
    with database.SessionLocal() as database_session:
        submitted_job = database_session.get(Job, submitted_job_id)
        assert submitted_job is not None
        assert submitted_job.status == JobStatus.SUBMITTED
        assert submitted_job.autotask_external_id == f"mock-time-entry-{submitted_job_id}"
        assert submitted_job.autotask_error == "Autotask refused to delete that time entry."

    failed_review_response = authenticated_client.get(f"/review/{submitted_job_id}")
    failed_review_html = failed_review_response.text
    assert "Autotask delete failed" in failed_review_html
    assert "Purge from Job Logger review?" in failed_review_html
    assert "It does not delete the Autotask record." in failed_review_html
    assert f'action="/review/{submitted_job_id}/purge-submitted-local"' in failed_review_html

    purge_csrf_token = extract_csrf_token(failed_review_html)
    purge_response = authenticated_client.post(
        f"/review/{submitted_job_id}/purge-submitted-local",
        data={"csrf_token": purge_csrf_token},
        follow_redirects=False,
    )

    assert purge_response.status_code == 303
    assert purge_response.headers["location"] == "/review"
    with database.SessionLocal() as database_session:
        assert database_session.get(Job, submitted_job_id) is None
        assert database_session.query(SubmissionAttempt).filter_by(job_id=submitted_job_id).count() == 0
        purge_event = database_session.query(AuditEvent).filter_by(
            action="job.review.submitted_delete_failed_local_purged",
        ).one()
        assert purge_event.job_id is None
        assert purge_event.details["job_id"] == submitted_job_id
        assert purge_event.details["external_id"] == f"mock-time-entry-{submitted_job_id}"
        assert purge_event.details["local_only"] is True


def test_mobile_page_and_blank_start_do_not_probe_autotask(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The initial mobile flow should not run provider contactability checks."""

    def fail_if_provider_is_used() -> object:
        """Fail the test if rendering or blank start tries to call Autotask."""

        raise AssertionError("Autotask provider should not be used by the initial mobile page or blank Start Work.")

    monkeypatch.setattr("job_logger.routes.mobile.get_autotask_provider", fail_if_provider_is_used)
    mobile_page_response = authenticated_client.get("/home")
    assert mobile_page_response.status_code == 200
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token, "client_name": "No Probe Client"},
        follow_redirects=False,
    )

    assert start_response.status_code == 303
    with database.SessionLocal() as database_session:
        assert get_active_job(database_session) is not None


def test_legacy_mobile_routes_redirect_to_home(authenticated_client: TestClient) -> None:
    """Old mobile URLs should preserve bookmarks while `/home` stays canonical."""

    page_response = authenticated_client.get("/mobile", follow_redirects=False)
    service_calls_response = authenticated_client.get(
        "/mobile/service-calls?date=2026-06-20",
        follow_redirects=False,
    )
    typo_response = authenticated_client.get("/moble", follow_redirects=False)

    assert page_response.status_code == 308
    assert page_response.headers["location"] == "/home"
    assert service_calls_response.status_code == 308
    assert service_calls_response.headers["location"] == "/home/service-calls?date=2026-06-20"
    assert typo_response.status_code == 303
    assert typo_response.headers["location"] == "/home"


def test_authenticated_mobile_header_renders_phone_icon_navigation(authenticated_client: TestClient) -> None:
    """Phone-sized headers should show version, icon navigation, and logout."""

    response = authenticated_client.get("/home")

    assert response.status_code == 200
    assert 'class="header-status-group desktop-status-group"' in response.text
    assert 'class="header-status-group mobile-version-group"' in response.text
    assert "app-version-link-dev" not in response.text
    assert "dev-build-pill" not in response.text
    assert "autotask-api-indicator" not in response.text
    assert "data-health-alert-button" not in response.text
    assert "Autotask API:" not in response.text
    assert "Secure session" not in response.text
    assert '<a href="/home">Home</a>' in response.text
    assert '<a href="/home">Mobile</a>' not in response.text
    assert 'class="mobile-nav-actions mobile-nav-left"' in response.text
    assert 'class="mobile-nav-actions mobile-nav-right"' in response.text
    assert 'data-mobile-home-link' in response.text
    assert 'aria-label="Home"' in response.text
    assert 'data-mobile-review-link' in response.text
    assert 'aria-label="Review"' in response.text
    assert 'data-mobile-users-link' not in response.text
    assert 'data-mobile-debug-link' not in response.text
    assert 'data-close-app-button' not in response.text
    assert "close-app-button" not in response.text
    assert 'class="logout-form mobile-logout-form"' in response.text
    assert 'class="icon-button mobile-nav-action mobile-logout-action"' in response.text
    assert 'title="Log out"' in response.text
    assert 'aria-label="Log out"' in response.text
    assert 'class="icon-button mobile-nav-action mobile-config-action"' in response.text
    assert 'aria-label="Config"' in response.text
    assert 'data-mobile-config-link' in response.text
    assert 'class="logout-form desktop-logout-form"' in response.text
    assert 'action="/logout"' in response.text
    assert '/static/mobile.js?v=' in response.text
    assert "Review jobs" not in response.text
    assert ">Ready<" not in response.text
    assert "click start work, or choose a service call below to start work on a ticket" in response.text


def test_super_admin_mobile_header_renders_users_review_debug_and_logout(super_admin_client: TestClient) -> None:
    """Super-admin phone navigation should expose admin routes without Config."""

    response = super_admin_client.get("/users")

    assert response.status_code == 200
    assert 'class="header-status-group desktop-status-group"' in response.text
    assert 'class="header-status-group mobile-version-group"' in response.text
    assert 'class="mobile-nav-actions mobile-nav-left"' in response.text
    assert 'class="mobile-nav-actions mobile-nav-right"' in response.text
    assert 'data-mobile-users-link' in response.text
    assert 'aria-label="Users"' in response.text
    assert 'data-mobile-review-link' in response.text
    assert 'aria-label="Review"' in response.text
    assert 'data-mobile-debug-link' in response.text
    assert 'class="icon-button mobile-nav-action mobile-debug-action"' in response.text
    assert 'aria-label="Diagnostics"' in response.text
    assert 'data-mobile-home-link' not in response.text
    assert 'data-mobile-config-link' not in response.text
    assert 'data-close-app-button' not in response.text
    assert 'class="logout-form mobile-logout-form"' in response.text
    assert 'class="icon-button mobile-nav-action mobile-logout-action"' in response.text
    assert 'aria-label="Log out"' in response.text
    assert response.text.index("data-mobile-users-link") < response.text.index("data-mobile-review-link")
    assert response.text.index("data-mobile-review-link") < response.text.index('class="header-status-group mobile-version-group"')
    assert response.text.index('class="mobile-nav-actions mobile-nav-right"') < response.text.index("data-mobile-debug-link")
    assert response.text.index("data-mobile-debug-link") < response.text.index("mobile-logout-action")


def test_non_mobile_authenticated_header_keeps_desktop_navigation_and_logout(authenticated_client: TestClient) -> None:
    """Non-mobile layouts should still expose explicit local-session logout."""

    response = authenticated_client.get("/review")

    assert response.status_code == 200
    assert 'class="secondary-link-button" href="/home"' not in response.text
    assert ">Mobile<" not in response.text
    assert "Secure session" not in response.text
    assert '<a href="/home">Home</a>' in response.text
    assert '<a href="/home">Mobile</a>' not in response.text
    assert 'action="/logout"' in response.text
    assert 'aria-label="Sign out"' in response.text
    assert 'data-close-app-button' not in response.text
    assert 'mobile-logout-action' in response.text
    assert '/static/pwa.js?v=' in response.text
    assert 'class="mobile-nav-actions mobile-nav-left"' in response.text
    assert 'class="mobile-nav-actions mobile-nav-right"' in response.text
    assert 'data-mobile-home-link' in response.text
    assert 'data-mobile-review-link' in response.text
    assert 'data-mobile-config-link' in response.text


def test_dev_build_indicator_renders_in_desktop_and_mobile_header(authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """DEV_BUILD should mark both responsive header variants without changing auth behavior."""

    monkeypatch.setattr(ui, "settings", replace(ui.settings, dev_build=True))

    response = authenticated_client.get("/home")

    assert response.status_code == 200
    assert response.text.count("app-version-link app-version-link-dev") == 2
    assert "dev-build-pill" not in response.text
    assert ">v1.2.0 DEV<" in response.text
    assert 'aria-label="View changelog for version 1.2.0 development build"' in response.text
    assert response.text.index('class="header-status-group desktop-status-group"') < response.text.index('class="top-nav"')
    assert response.text.index('class="header-status-group mobile-version-group"') < response.text.index('class="mobile-nav-actions mobile-nav-right"')


def test_mobile_styles_keep_service_calls_colored_and_ticket_description_scrollable() -> None:
    """CSS should keep mobile service-call cards distinct and long ticket descriptions bounded."""

    stylesheet_path = Path(__file__).resolve().parents[1] / "job_logger" / "static" / "app.css"
    stylesheet = stylesheet_path.read_text(encoding="utf-8")
    phone_stylesheet_path = Path(__file__).resolve().parents[1] / "job_logger" / "static" / "phone.css"
    phone_stylesheet = phone_stylesheet_path.read_text(encoding="utf-8")
    desktop_stylesheet_path = Path(__file__).resolve().parents[1] / "job_logger" / "static" / "desktop.css"
    desktop_stylesheet = desktop_stylesheet_path.read_text(encoding="utf-8")

    assert ".service-call-option-button.service-call-location-remote" in stylesheet
    assert ".service-call-option-button.service-call-location-on_site" in stylesheet
    assert ".ticket-option-button.ticket-location-remote" in stylesheet
    assert ".ticket-option-button.ticket-location-on_site" in stylesheet
    assert ".ticket-option-card-header" in stylesheet
    assert ".ticket-location-badge" in stylesheet
    assert ".ticket-note-list-button" in stylesheet
    assert "min-height: 68px;" in stylesheet
    assert ".ticket-note-list-title" in stylesheet
    assert "-webkit-line-clamp: 2;" in stylesheet
    assert "max-height: calc(1.32em * 2);" in stylesheet
    assert ".review-ticket-status-field" in stylesheet
    assert ".app-version-link-dev" in stylesheet
    assert ".health-alert-button" in stylesheet
    assert ".desktop-health-alert-group" in stylesheet
    assert ".dev-build-pill" not in stylesheet
    assert "border: 1px solid rgba(245, 158, 11, 0.58);" in stylesheet
    assert ".status-chip" in stylesheet
    assert "text-transform: uppercase;" in stylesheet
    assert "border-radius: 999px;" in stylesheet
    assert ".status-waiting_parts" in stylesheet
    assert ".review-table th:nth-child(4)" in stylesheet
    assert "text-overflow: ellipsis;" in stylesheet
    assert "grid-column: 1;" in stylesheet
    assert "linear-gradient(90deg, rgba(45, 212, 191" in stylesheet
    assert "linear-gradient(90deg, rgba(245, 158, 11" in stylesheet
    assert ".service-call-loading-state" in stylesheet
    assert ".service-call-date-nav" in stylesheet
    assert "max-width: 420px;" in stylesheet
    assert ".service-call-date-step-button" in stylesheet
    assert ".service-call-date-button" in stylesheet
    assert ".mobile-page-loading" in stylesheet
    assert ".ticket-status-card select" in stylesheet
    assert "button:not(:disabled):active" in stylesheet
    assert "transform: translateY(1px) scale(0.985);" in stylesheet
    assert ".service-call-time-range" in stylesheet
    assert "max-height: 25lh;" in stylesheet
    assert "max-height: 12.5lh;" in phone_stylesheet
    assert "overscroll-behavior: contain;" in stylesheet
    assert ".mobile-ticket-picker.is-clickable" in stylesheet
    assert ".ticket-picker.is-clickable" in stylesheet
    assert ".recording-status.is-loading" not in stylesheet
    assert ".ai-cleanup-status.is-loading" not in stylesheet
    assert ".ticket-picker-status.is-loading" in stylesheet
    assert ".record-notes-button,\n.recording-control-stack .record-notes-button" in stylesheet
    assert "background: var(--warning);" in stylesheet
    assert ".end-work-button,\n.work-finish-stack .end-work-button" in stylesheet
    assert "background: var(--success);" in stylesheet
    assert ".ai-cleanup-button,\n.summary-tool-row .ai-cleanup-button" in stylesheet
    assert ".summary-action-row" in stylesheet
    assert ".button-pair-row" in stylesheet
    assert ".active-job-panel-slot-1" in stylesheet
    assert ".active-job-panel-slot-2" in stylesheet
    assert ".description-box > .button-grid" in stylesheet
    assert ".review-location-chip" in stylesheet
    assert ".review-detail-heading-row" in stylesheet
    assert ".review-work-location-card" in stylesheet
    assert ".review-shell > .review-header" in stylesheet
    assert ".review-detail-heading-row {\n  align-items: flex-start;" in stylesheet
    assert "flex-direction: column;" in stylesheet
    assert ".review-detail-heading-row .status-chip {\n  align-self: flex-start;" in stylesheet
    assert ".review-work-location-card .work-location-switch" in stylesheet
    assert "justify-self: center;" in stylesheet
    assert ".review-detail-heading-row {\n  gap: 6px;" in phone_stylesheet
    assert ".review-action-stack" in stylesheet
    assert ".review-status-stack" in stylesheet
    assert "[data-review-autosave-status]:empty" in stylesheet
    assert ".review-summary-action-row" in stylesheet
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in stylesheet
    assert ".recording-status:empty,\n[data-active-save-status]:empty" in stylesheet
    assert ".ai-cleanup-status:empty" in stylesheet
    assert "background: var(--ai-action);" in stylesheet
    assert ".app-header {\n  display: grid;" in phone_stylesheet
    assert "grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);" in phone_stylesheet
    assert ".app-header.has-health-alert" in phone_stylesheet
    assert "grid-template-columns: auto minmax(0, 1fr) auto;" in phone_stylesheet
    assert ".mobile-version-group .app-version-link-dev" in phone_stylesheet
    assert "transform: translateX(-8px);" in phone_stylesheet
    assert ".brand {\n  display: none;" in phone_stylesheet
    assert ".login-header .login-brand" in phone_stylesheet
    assert "grid-column: 2;" in phone_stylesheet
    assert ".mobile-version-group {\n  display: inline-flex;" in phone_stylesheet
    assert ".dev-build-pill" not in phone_stylesheet
    assert ".mobile-nav-actions {\n  display: flex;" in phone_stylesheet
    assert ".mobile-nav-left {\n  grid-column: 1;" in phone_stylesheet
    assert ".mobile-nav-right {\n  grid-column: 3;" in phone_stylesheet
    assert ".mobile-logout-form {\n  display: inline-grid;" in phone_stylesheet
    assert ".desktop-logout-form {\n  display: none;" in phone_stylesheet
    assert ".mobile-shell .description-box .job-description,\n.review-shell textarea[data-review-summary-textarea]" in phone_stylesheet
    assert "min-height: 180px;" in phone_stylesheet
    assert ".active-jobs-stack > .work-panel:not([data-active-job-card])" in desktop_stylesheet
    assert ".work-panel[data-active-job-card]" in desktop_stylesheet
    assert "grid-template-columns: minmax(280px, 0.82fr) minmax(420px, 1.18fr);" in desktop_stylesheet
    assert "grid-template-columns: minmax(0, 1fr) minmax(360px, 0.78fr);" in desktop_stylesheet
    assert ".work-panel[data-active-job-card] .summary-action-row .secondary-button" in desktop_stylesheet
    assert ".active-jobs-stack > .work-panel:not([data-active-job-card])" not in phone_stylesheet
    assert ".work-panel[data-active-job-card]" not in phone_stylesheet
    mobile_template = (Path(__file__).resolve().parents[1] / "job_logger" / "templates" / "mobile.html").read_text(encoding="utf-8")
    review_template = (Path(__file__).resolve().parents[1] / "job_logger" / "templates" / "review.html").read_text(encoding="utf-8")
    assert mobile_template.index('class="summary-action-row recording-control-stack"') < mobile_template.index("data-ai-cleanup-button")
    assert mobile_template.index("data-record-audio-label") < mobile_template.index("data-ai-cleanup-button")
    summary_action_index = mobile_template.index('class="summary-action-row recording-control-stack"')
    active_button_grid_index = mobile_template.index('class="button-grid"', summary_action_index)
    recording_status_index = mobile_template.index('class="recording-status workflow-status-line"', active_button_grid_index)
    assert summary_action_index < active_button_grid_index < recording_status_index
    assert 'class="work-panel active-job-panel active-job-panel-slot-{{ job_label }}"' in mobile_template
    assert ">Record</span>" in mobile_template
    assert "Delete time entry" not in mobile_template
    assert "<span data-delete-entry-label>{% if is_ticket_note %}Delete Note{% else %}Delete{% endif %}</span>" in mobile_template
    assert 'class="summary-action-row review-summary-action-row recording-control-stack"' in review_template
    assert review_template.index("data-review-record-button") < review_template.index("data-ai-cleanup-button")
    review_summary_action_index = review_template.index('class="summary-action-row review-summary-action-row recording-control-stack"')
    review_action_stack_index = review_template.index('class="review-action-stack"')
    review_status_stack_index = review_template.index('class="review-status-stack"', review_action_stack_index)
    assert review_summary_action_index < review_action_stack_index < review_status_stack_index
    assert review_template.index("data-review-recording-status", review_status_stack_index) > review_action_stack_index
    assert ">Record</span>" in review_template
    assert "Record Audio" not in review_template
    assert 'class="review-action-stack"' in review_template
    assert 'class="button-pair-row review-action-row"' in review_template
    assert 'form="{{ review_form_id }}"' in review_template


def test_active_job_completion_requires_client_name(authenticated_client: TestClient) -> None:
    """Jobs without a client name cannot be moved from active to review."""

    mobile_page_response = authenticated_client.get("/home")
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
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert succeeded_end_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.READY_FOR_REVIEW


def test_mobile_autotask_company_lookup_returns_options(authenticated_client: TestClient) -> None:
    """Authenticated mobile users can query safe Autotask company options."""

    response = authenticated_client.get("/autotask/companies?query=Acme")

    assert response.status_code == 200
    response_payload = response.json()
    assert response_payload["companies"][0]["company_id"] == 1001
    assert response_payload["companies"][0]["company_name"] == "Acme Services"


def test_mobile_job_start_ignores_prestart_client_and_ticket_fields(authenticated_client: TestClient) -> None:
    """Starting work creates a blank job even if stale form fields are posted."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    assert "Autotask ticket number" not in mobile_page_response.text
    assert 'name="ticket_number"' not in mobile_page_response.text
    assert 'name="client_name"' not in mobile_page_response.text

    start_response = authenticated_client.post(
        "/jobs/start",
        data={
            "csrf_token": csrf_token,
            "ticket_number": "T20260616.0001",
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
        },
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        assert active_job.ticket_number is None
        assert active_job.client_name is None
    assert active_job.autotask_company_id is None


def test_super_admin_review_shows_job_owner_only_for_admin(authenticated_client: TestClient) -> None:
    """Only the super-admin review list and detail should expose job ownership."""

    mobile_page_response = authenticated_client.get("/home")
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

    user_review_response = authenticated_client.get(f"/review/{active_job_id}")
    assert "<th>Owner</th>" not in user_review_response.text
    assert "review-owner-card" not in user_review_response.text
    assert "Test Technician" not in user_review_response.text

    login_as_super_admin(authenticated_client)
    admin_review_response = authenticated_client.get(f"/review/{active_job_id}")
    assert admin_review_response.status_code == 200
    assert "<th>Owner</th>" in admin_review_response.text
    assert "review-owner-card" in admin_review_response.text
    assert "Test Technician" in admin_review_response.text


def test_review_delete_time_entry_can_delete_active_jobs(authenticated_client: TestClient) -> None:
    """The review-page Delete time entry action can remove an active local job."""

    mobile_page_response = authenticated_client.get("/home")
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

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    assert "Delete time entry" in review_page_response.text
    review_csrf_token = extract_csrf_token(review_page_response.text)
    purge_response = authenticated_client.post(
        f"/review/{active_job_id}/purge",
        data={"csrf_token": review_csrf_token},
        follow_redirects=False,
    )

    assert purge_response.status_code == 303
    assert purge_response.headers["location"] == "/review"
    with database.SessionLocal() as database_session:
        assert database_session.get(Job, active_job_id) is None
        audit_event = database_session.query(AuditEvent).filter_by(action="job.review.deleted").one()
        assert audit_event.details["job_status"] == "active"


def test_review_detail_can_end_active_jobs(authenticated_client: TestClient) -> None:
    """Active jobs selected on review detail expose the normal End Work action."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "summary_notes": "Ready to end from review.",
            "ticket_status": "in_progress",
        },
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_html = review_page_response.text
    review_csrf_token = extract_csrf_token(review_html)

    assert review_page_response.status_code == 200
    assert "End Work" in review_html
    assert f'formaction="/jobs/{active_job_id}/end"' in review_html
    assert 'name="return_to" value="review"' in review_html
    assert "Accept and Submit" not in review_html

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={
            "csrf_token": review_csrf_token,
            "return_to": "review",
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "summary_notes": "Ready to end from review.",
            "work_location": "remote",
            "ticket_status": "in_progress",
        },
        follow_redirects=False,
    )

    assert end_response.status_code == 303
    assert end_response.headers["location"] == f"/review/{active_job_id}"
    with database.SessionLocal() as database_session:
        ended_job = database_session.get(Job, active_job_id)
        assert ended_job is not None
        assert ended_job.status == JobStatus.READY_FOR_REVIEW
        assert ended_job.summary_notes == "Ready to end from review."


def test_mobile_active_job_page_locks_selected_autotask_client(authenticated_client: TestClient) -> None:
    """The active mobile card renders selected Autotask clients as read-only."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    updated_mobile_page_response = authenticated_client.get("/home")
    page_html = updated_mobile_page_response.text

    assert 'data-locked-client-field' in page_html
    assert "AUTOTASK SELECTED" not in page_html
    assert "Autotask selected" not in page_html
    assert 'class="metric-card client-name-card"' in page_html
    assert f'id="active-client-name-{active_job_id}"' not in page_html
    assert 'class="end-client-name"' in page_html
    assert 'class="end-autotask-company-id"' in page_html
    assert 'class="rounded-start-time-form active-time-step-controls"' in page_html
    rounded_start_form_open = re.search(
        r'<form(?=[^>]*class="rounded-start-time-form active-time-step-controls")[^>]*>',
        page_html,
    )
    assert rounded_start_form_open is not None
    assert "data-page-loading-form" not in rounded_start_form_open.group(0)
    assert "data-loading-message" not in rounded_start_form_open.group(0)
    assert f'action="/jobs/{active_job_id}/start-time"' in page_html
    assert f'formaction="/jobs/{active_job_id}/start-time/adjust"' in page_html
    assert 'data-active-time-form' in page_html
    assert 'data-active-time-kind="start"' in page_html
    assert 'name="rounded_start_time"' in page_html
    assert 'class="time-field-input rounded-start-time-display"' in page_html
    assert 'class="rounded-stop-time-form active-time-step-controls"' in page_html
    rounded_stop_form_open = re.search(
        r'<form(?=[^>]*class="rounded-stop-time-form active-time-step-controls")[^>]*>',
        page_html,
    )
    assert rounded_stop_form_open is not None
    assert "data-page-loading-form" not in rounded_stop_form_open.group(0)
    assert "data-loading-message" not in rounded_stop_form_open.group(0)
    assert f'action="/jobs/{active_job_id}/stop-time"' in page_html
    assert f'formaction="/jobs/{active_job_id}/stop-time/adjust"' in page_html
    assert 'data-active-time-kind="stop"' in page_html
    assert 'name="rounded_stop_time"' in page_html
    assert 'class="time-field-input rounded-stop-time-display"' in page_html
    assert 'data-rounded-stop-display' in page_html
    assert 'data-rounded-start-utc=' in page_html
    assert 'data-initial-rounded-stop-utc=' in page_html
    assert re.search(r'data-rounded-start-utc="[^"]+\+00:00"', page_html)
    assert re.search(r'data-initial-rounded-stop-utc="[^"]+\+00:00"', page_html)
    assert 'name="delta_minutes"' in page_html
    assert 'data-active-time-delta="-15"' in page_html
    assert 'data-active-time-delta="15"' in page_html
    assert 'value="-15"' in page_html
    assert 'value="15"' in page_html
    assert "Duration:" in page_html
    assert "data-duration-display" in page_html
    assert 'class="work-location-switch"' in page_html
    assert 'data-work-location-toggle' in page_html
    assert 'name="work_location"' in page_html
    assert 'value="remote"' in page_html
    assert 'value="on_site"' in page_html
    assert "<dt>Work type</dt>" not in page_html
    assert 'class="segmented-toggle work-location-toggle"' not in page_html
    assert 'data-active-ticket-picker' in page_html
    assert f'data-ticket-select-url="/jobs/{active_job_id}/ticket"' in page_html
    assert 'data-auto-load-ticket-options="true"' not in page_html
    assert 'data-active-ticket-lookup-button' not in page_html
    assert "Find tickets" not in page_html
    assert "Click this box to load open tickets." in page_html
    assert page_html.index("<dt>Client name</dt>") < page_html.index("<h3>Open tickets</h3>")
    assert page_html.index(f'id="active-ticket-form-{active_job_id}"') < page_html.index("<h3>Open tickets</h3>")
    assert 'class="secondary-button active-save-button"' not in page_html
    assert "Save Active Changes" not in page_html
    assert "submit-notes-button" not in page_html
    assert 'class="summary-action-row recording-control-stack"' in page_html
    assert page_html.index("Summary notes") < page_html.index(">Record<")
    assert "Stop Recording" not in page_html
    assert "Record Notes" not in page_html
    assert "Record Audio" not in page_html
    assert "Autotask ticket number" not in page_html
    assert 'class="active-ticket-number"' in page_html
    assert 'pattern="[Tt][0-9]{8}\\.[0-9]{4}"' not in page_html
    assert 'pattern="[Tt][0-9]{8}\\\\.[0-9]{4}"' not in page_html
    assert page_html.index('value="-15"') < page_html.index('class="time-field-input rounded-start-time-display"')
    assert page_html.index('class="time-field-input rounded-start-time-display"') < page_html.index('value="15"')
    assert page_html.index("<dt>Rounded start</dt>") < page_html.index("<dt>Rounded stop</dt>")
    assert page_html.index("<dt>Rounded stop</dt>") < page_html.index("data-duration-display")
    assert 'class="duration-inline duration-centered"' in page_html
    assert page_html.index("<dt>Rounded stop</dt>") < page_html.index('class="metric-card work-location-card"')
    assert page_html.index("data-duration-display") < page_html.index('class="metric-card work-location-card"')


def test_mobile_active_job_locked_autotask_company_rejects_form_tampering(authenticated_client: TestClient) -> None:
    """Mobile form handlers preserve an already selected active-job company."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    tampered_save_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "ticket_number": "T20260616.9999",
            "client_name": "Wrong Client",
            "autotask_company_id": "2002",
        },
        follow_redirects=False,
    )
    assert tampered_save_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.ACTIVE
        assert active_job.client_name == "Acme Services"
        assert active_job.autotask_company_id == 1001
        assert active_job.ticket_number is None

    tampered_end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Wrong Client", "autotask_company_id": "2002"},
        follow_redirects=False,
    )
    assert tampered_end_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.ACTIVE
        assert active_job.client_name == "Acme Services"
        assert active_job.autotask_company_id == 1001

    valid_end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert valid_end_response.status_code == 303

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.status == JobStatus.READY_FOR_REVIEW
        assert reviewed_job.client_name == "Acme Services"
        assert reviewed_job.autotask_company_id == 1001


def test_review_save_does_not_require_ticket_number(authenticated_client: TestClient) -> None:
    """Review edits can be saved while leaving the ticket number blank."""

    mobile_page_response = authenticated_client.get("/home")
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

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)
    assert "data-review-autosave-form" in review_page_response.text
    assert "data-review-autosave-status" in review_page_response.text
    assert f'formaction="/review/{active_job_id}/save"' not in review_page_response.text

    save_response = authenticated_client.post(
        f"/review/{active_job_id}/save",
        data={
            "csrf_token": review_csrf_token,
            "ticket_number": "",
            "ticket_status": "complete",
            "job_date": "2026-06-16",
            "start_time": "08:00",
            "end_time": "08:15",
            "summary_notes": "Editable without ticket during save.",
        },
        follow_redirects=False,
    )
    assert save_response.status_code == 303

    autosave_response = authenticated_client.post(
        f"/review/{active_job_id}/save",
        headers={"Accept": "application/json"},
        data={
            "csrf_token": review_csrf_token,
            "ticket_number": "",
            "ticket_status": "follow_up",
            "job_date": "2026-06-16",
            "start_time": "08:00",
            "end_time": "08:15",
            "summary_notes": "Autosaved without ticket during review.",
        },
    )
    assert autosave_response.status_code == 200
    autosave_payload = autosave_response.json()
    assert autosave_payload["job_id"] == active_job_id
    assert autosave_payload["ticket_status"] == "follow_up"
    assert autosave_payload["summary_notes"] == "Remote. Autosaved without ticket during review."
    assert autosave_payload["job_date"] == "2026-06-16"
    assert autosave_payload["start_time"] == "8:00 am"
    assert autosave_payload["end_time"] == "8:15 am"
    assert autosave_payload["duration_label"] == "15 Minutes"

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.status == JobStatus.READY_FOR_REVIEW
        assert reviewed_job.ticket_number is None
        assert reviewed_job.summary_notes == "Autosaved without ticket during review."


def test_review_detail_shows_active_rounded_stop_without_ending_job(authenticated_client: TestClient) -> None:
    """Active review detail should display the WIP rounded stop preview without applying it as an end time."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    rounded_start = datetime(2026, 6, 16, 12, 0)
    rounded_stop_preview = datetime(2026, 6, 16, 12, 30)
    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id
        active_job.rounded_start_utc = rounded_start
        active_job.rounded_end_utc = rounded_stop_preview
        active_job.local_work_date = local_date_for(rounded_start)
        active_job.summary_notes = "Active review notes."
        database_session.commit()

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_html = review_page_response.text

    assert review_page_response.status_code == 200
    assert re.search(r'<input(?=[^>]*name="end_time")(?=[^>]*value="8:30 am")', review_html)
    assert "Duration:" in review_html
    assert "30 Minutes" in review_html
    assert "data-duration-display" in review_html
    assert 'class="duration-inline duration-centered review-duration-row"' in review_html
    assert review_html.index('name="end_time"') < review_html.index('name="ticket_status"')
    assert review_html.index('name="end_time"') < review_html.index("data-duration-display")
    assert review_html.index("data-duration-display") < review_html.index('name="ticket_status"')
    assert 'class="review-ticket-status-field"' in review_html

    review_csrf_token = extract_csrf_token(review_html)
    autosave_response = authenticated_client.post(
        f"/review/{active_job_id}/save",
        headers={"Accept": "application/json"},
        data={
            "csrf_token": review_csrf_token,
            "ticket_number": "",
            "ticket_status": "follow_up",
            "job_date": "2026-06-16",
            "start_time": "8:00 am",
            "end_time": "8:45 am",
            "summary_notes": "Changed active review notes.",
        },
    )

    assert autosave_response.status_code == 200
    autosave_payload = autosave_response.json()
    assert autosave_payload["end_time"] == "8:30 am"
    assert autosave_payload["duration_label"] == "30 Minutes"
    assert autosave_payload["ticket_status"] == "follow_up"
    assert autosave_payload["summary_notes"] == "Remote. Changed active review notes."

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.ACTIVE
        assert active_job.rounded_end_utc == rounded_stop_preview
        assert active_job.summary_notes == "Changed active review notes."


def test_review_summary_prefix_is_editable_and_updates_work_location(authenticated_client: TestClient) -> None:
    """Review saves the visible Autotask summary prefix back into work_location."""

    mobile_page_response = authenticated_client.get("/home")
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
        json={"summary_notes": "Original remote work notes."},
    )
    assert text_response.status_code == 200

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_html = review_page_response.text
    review_csrf_token = extract_csrf_token(review_html)
    assert "Remote. Original remote work notes." in review_html
    assert 'class="review-location-chip review-location-remote"' in review_html
    assert "Remote" in review_html
    assert 'data-review-work-location-toggle' in review_html
    assert 'name="work_location"' in review_html

    save_response = authenticated_client.post(
        f"/review/{active_job_id}/save",
        headers={"Accept": "application/json"},
        data={
            "csrf_token": review_csrf_token,
            "ticket_status": "follow_up",
            "job_date": "2026-06-16",
            "start_time": "08:00",
            "end_time": "08:15",
            "summary_notes": "On-Site. replaced the access point onsite.",
        },
    )

    assert save_response.status_code == 200
    assert save_response.json()["summary_notes"] == "On-Site. replaced the access point onsite."

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.summary_notes == "replaced the access point onsite."
        assert reviewed_job.description_text == "replaced the access point onsite."
        assert reviewed_job.work_location == WorkLocation.ON_SITE

    updated_review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    updated_review_html = updated_review_page_response.text
    assert 'class="review-location-chip review-location-on_site"' in updated_review_html
    assert "On-Site. replaced the access point onsite." in updated_review_html


def test_review_save_active_job_without_stop_time(authenticated_client: TestClient) -> None:
    """Active jobs can be saved in review without submitting an end time."""

    mobile_page_response = authenticated_client.get("/home")
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
        active_job_rounded_start = active_job.rounded_start_utc
        active_job_local_date = local_date_for(active_job_rounded_start)
        assert active_job.rounded_end_utc is None
        active_job.rounded_end_utc = active_job_rounded_start + timedelta(minutes=15)
        database_session.commit()

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)
    active_job_display_start = format_local_time(active_job_rounded_start)
    active_job_tentative_stop = format_local_time(active_job_rounded_start + timedelta(minutes=15))

    assert 'type="time"' not in review_page_response.text
    assert f'value="{active_job_display_start}"' in review_page_response.text
    assert f'value="{active_job_tentative_stop}"' in review_page_response.text
    assert " am" in active_job_display_start or " pm" in active_job_display_start

    save_response = authenticated_client.post(
        f"/review/{active_job_id}/save",
        data={
            "csrf_token": review_csrf_token,
            "ticket_status": "complete",
            "job_date": active_job_local_date.isoformat(),
            "start_time": active_job_display_start,
            "summary_notes": "Active job saved without stop values.",
        },
        follow_redirects=False,
    )
    assert save_response.status_code == 303

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.status == JobStatus.ACTIVE
        assert reviewed_job.rounded_end_utc == (active_job_rounded_start + timedelta(minutes=15)).replace(tzinfo=None)
        assert reviewed_job.client_name is None
        assert reviewed_job.summary_notes == "Active job saved without stop values."
        assert reviewed_job.ticket_number is None


def test_review_rejects_cross_day_time_edits(authenticated_client: TestClient) -> None:
    """Review edits use one job date and reject times that would span days."""

    mobile_page_response = authenticated_client.get("/home")
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

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)
    invalid_save_response = authenticated_client.post(
        f"/review/{active_job_id}/save",
        headers={"Accept": "application/json"},
        data={
            "csrf_token": review_csrf_token,
            "ticket_status": "complete",
            "job_date": "2026-06-16",
            "start_time": "11:00 pm",
            "end_time": "10:45 pm",
            "summary_notes": "This edit should be rejected.",
        },
    )

    assert invalid_save_response.status_code == 400
    assert invalid_save_response.json()["detail"] == "End time must be after start time on the same job date."

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.summary_notes != "This edit should be rejected."


def test_review_ticket_lookup_returns_open_tickets_for_job_client(authenticated_client: TestClient) -> None:
    """Review can request open Autotask ticket options using the selected company."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.autotask_company_id == 1001

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    ticket_lookup_response = authenticated_client.get(f"/review/{active_job_id}/tickets")

    assert ticket_lookup_response.status_code == 200
    response_payload = ticket_lookup_response.json()
    assert response_payload["client_name"] == "Acme Services"
    assert response_payload["autotask_company_id"] == 1001
    assert response_payload["tickets"][0]["ticket_number"] == "T20260616.0001"
    assert response_payload["tickets"][0]["company_name"] == "Acme Services"
    assert response_payload["tickets"][0]["description"] == "Mock ticket description for Acme Services."
    assert response_payload["tickets"][0]["work_location_label"] == "Remote"
    assert response_payload["tickets"][0]["work_location_class"] == "ticket-location-remote"


def test_review_detail_can_select_client_when_identity_is_empty(authenticated_client: TestClient) -> None:
    """Blank active jobs opened in Review can save a first Autotask client selection."""

    mobile_page_response = authenticated_client.get("/home")
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

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_html = review_page_response.text
    review_csrf_token = extract_csrf_token(review_html)
    assert 'data-review-company-input' in review_html
    assert 'data-review-client-save-url=' in review_html
    assert 'data-ticket-client-label' in review_html
    assert "Client name is required before open tickets can load." in review_html

    typed_only_client_response = authenticated_client.post(
        f"/review/{active_job_id}/client",
        headers={"X-CSRF-Token": review_csrf_token},
        json={"client_name": "Typed Only Client"},
    )
    assert typed_only_client_response.status_code == 400
    assert "Select a client from Autotask search results" in typed_only_client_response.json()["detail"]

    mismatched_client_response = authenticated_client.post(
        f"/review/{active_job_id}/client",
        headers={"X-CSRF-Token": review_csrf_token},
        json={"client_name": "Wrong Client", "autotask_company_id": "1001"},
    )
    assert mismatched_client_response.status_code == 400
    assert "Select a client from Autotask search results" in mismatched_client_response.json()["detail"]

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        active_job_date = str(active_job.local_work_date)
        active_start_time = format_local_time(active_job.rounded_start_utc)
        assert active_job.client_name is None
        assert active_job.autotask_company_id is None

    generic_review_save_response = authenticated_client.post(
        f"/review/{active_job_id}/save",
        headers={"Accept": "application/json"},
        data={
            "csrf_token": review_csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "ticket_status": "in_progress",
            "job_date": active_job_date,
            "start_time": active_start_time,
            "summary_notes": "Generic review save must not set client identity.",
        },
    )
    assert generic_review_save_response.status_code == 200

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.client_name is None
        assert active_job.autotask_company_id is None

    save_client_response = authenticated_client.post(
        f"/review/{active_job_id}/client",
        headers={"X-CSRF-Token": review_csrf_token},
        json={"client_name": "Acme Services", "autotask_company_id": "1001"},
    )

    assert save_client_response.status_code == 200
    assert save_client_response.json() == {
        "job_id": active_job_id,
        "client_name": "Acme Services",
        "autotask_company_id": 1001,
    }
    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.client_name == "Acme Services"
        assert active_job.autotask_company_id == 1001
        client_event = database_session.query(AuditEvent).filter_by(action="job.review.client_selected").one()
        assert client_event.job_id == active_job_id
        assert client_event.details["autotask_company_selected"] is True

    ticket_lookup_response = authenticated_client.get(f"/review/{active_job_id}/tickets")
    assert ticket_lookup_response.status_code == 200
    assert ticket_lookup_response.json()["tickets"][0]["company_name"] == "Acme Services"

    tampered_client_response = authenticated_client.post(
        f"/review/{active_job_id}/client",
        headers={"X-CSRF-Token": review_csrf_token},
        json={"client_name": "Wrong Client", "autotask_company_id": "2002"},
    )
    assert tampered_client_response.status_code == 400
    assert "Client identity is already selected" in tampered_client_response.json()["detail"]

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.client_name == "Acme Services"
        assert active_job.autotask_company_id == 1001


def test_selected_ticket_title_drives_review_heading_and_hides_lookup(authenticated_client: TestClient) -> None:
    """Selecting an Autotask ticket stores the title and locks review identity fields."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    assert "Unassigned Ticket" in review_page_response.text
    assert "data-ticket-picker" in review_page_response.text
    review_csrf_token = extract_csrf_token(review_page_response.text)

    select_ticket_response = authenticated_client.post(
        f"/review/{active_job_id}/ticket",
        headers={"X-CSRF-Token": review_csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    assert select_ticket_response.status_code == 200
    assert select_ticket_response.json() == {
        "ticket_number": "T20260616.0001",
        "ticket_title": "Mock open ticket for Acme Services",
        "ticket_description": "Mock ticket description for Acme Services.",
        "ticket_status": "in_progress",
        "ticket_status_label": "In Progress",
    }

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.ticket_number == "T20260616.0001"
        assert reviewed_job.ticket_status == TicketStatus.IN_PROGRESS
        assert reviewed_job.ticket_title == "Mock open ticket for Acme Services"
        assert reviewed_job.ticket_description == "Mock ticket description for Acme Services."
        assert reviewed_job.client_name == "Acme Services"
        assert reviewed_job.autotask_company_id == 1001

    updated_review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    updated_review_html = updated_review_page_response.text
    assert "Mock open ticket for Acme Services" in updated_review_html
    assert "Mock ticket description for Acme Services." in updated_review_html
    assert "Unassigned Ticket" not in updated_review_html
    assert "data-ticket-picker" not in updated_review_html
    assert 'class="readonly-field-value" data-review-ticket-number-display' in updated_review_html
    assert "T20260616.0001" in updated_review_html
    assert '<span class="metric-label readonly-field-title">Ticket number</span>' in updated_review_html
    assert '<span class="metric-label readonly-field-title">Client name</span>' in updated_review_html
    assert re.search(r'<input(?=[^>]*name="ticket_number")(?=[^>]*type="hidden")', updated_review_html)
    assert re.search(r'<input(?=[^>]*name="client_name")(?=[^>]*type="hidden")', updated_review_html)
    assert not re.search(r'<input(?=[^>]*name="ticket_number")(?!(?=[^>]*type="hidden"))', updated_review_html)
    assert not re.search(r'<input(?=[^>]*name="client_name")(?!(?=[^>]*type="hidden"))', updated_review_html)

    tampered_save_response = authenticated_client.post(
        f"/review/{active_job_id}/save",
        data={
            "csrf_token": review_csrf_token,
            "ticket_number": "T20260616.9999",
            "ticket_title": "Wrong ticket title",
            "ticket_description": "Wrong ticket description",
            "ticket_status": "complete",
            "client_name": "Wrong Client",
            "autotask_company_id": "2002",
            "job_date": "2026-06-16",
            "start_time": "08:00",
            "end_time": "08:15",
            "summary_notes": "Review save must not rewrite read-only identity fields.",
        },
        follow_redirects=False,
    )
    assert tampered_save_response.status_code == 303

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.ticket_number == "T20260616.0001"
        assert reviewed_job.ticket_title == "Mock open ticket for Acme Services"
        assert reviewed_job.ticket_description == "Mock ticket description for Acme Services."
        assert reviewed_job.client_name == "Acme Services"
        assert reviewed_job.autotask_company_id == 1001
        assert reviewed_job.summary_notes == "Review save must not rewrite read-only identity fields."


def test_ticket_notes_endpoint_returns_safe_selected_ticket_notes(authenticated_client: TestClient) -> None:
    """Selected ticket notes should load through the authenticated server route."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    select_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    assert select_ticket_response.status_code == 200

    notes_response = authenticated_client.get(f"/review/{active_job_id}/ticket-notes")

    assert notes_response.status_code == 200
    payload = notes_response.json()
    assert payload["ticket_number"] == "T20260616.0001"
    assert payload["ticket_title"] == "Mock open ticket for Acme Services"
    assert len(payload["notes"]) == 2
    assert payload["notes"][0]["note_id"] == 91002
    assert payload["notes"][0]["title"] == "Technician update"
    assert payload["notes"][0]["description"] == "Previous technician confirmed the device was reachable from the LAN."
    assert payload["notes"][0]["preview"] == "Previous technician confirmed the device was reachable from the LAN."
    assert payload["notes"][0]["created_by"] == "Previous Technician"
    assert payload["notes"][0]["created_at"] == "Jun 16, 2026 9:30 am"
    assert payload["notes"][1]["title"] == "Mock ticket note for T20260616.0001"
    assert payload["notes"][1]["created_by"] == "Customer Contact"


def test_ticket_time_entries_endpoint_returns_safe_selected_ticket_time_entries(authenticated_client: TestClient) -> None:
    """Selected ticket time entries should load through the authenticated server route."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    select_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    assert select_ticket_response.status_code == 200

    time_entries_response = authenticated_client.get(f"/review/{active_job_id}/ticket-time-entries")

    assert time_entries_response.status_code == 200
    payload = time_entries_response.json()
    assert payload["ticket_number"] == "T20260616.0001"
    assert payload["ticket_title"] == "Mock open ticket for Acme Services"
    assert len(payload["time_entries"]) == 2
    assert payload["time_entries"][0]["time_entry_id"] == 81002
    assert payload["time_entries"][0]["resource_name"] == "Test Technician"
    assert payload["time_entries"][0]["display_range"] == "06/29/2026 01:30 PM - 02:15 PM (0.7500 hours)"
    assert payload["time_entries"][0]["summary_notes"] == "Remote. Confirmed backup job status and verified customer access."
    assert payload["time_entries"][1]["resource_name"] == "Prior Engineer"


def test_ticket_notes_endpoint_stays_empty_until_ticket_is_selected(authenticated_client: TestClient) -> None:
    """The ticket-notes route should not query notes for a job without a ticket."""

    mobile_page_response = authenticated_client.get("/home")
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

    notes_response = authenticated_client.get(f"/review/{active_job_id}/ticket-notes")

    assert notes_response.status_code == 200
    assert notes_response.json() == {"ticket_number": "", "ticket_title": "", "notes": []}


def test_ticket_time_entries_endpoint_stays_empty_until_ticket_is_selected(authenticated_client: TestClient) -> None:
    """The ticket-time-entries route should not query entries for a job without a ticket."""

    mobile_page_response = authenticated_client.get("/home")
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

    time_entries_response = authenticated_client.get(f"/review/{active_job_id}/ticket-time-entries")

    assert time_entries_response.status_code == 200
    assert time_entries_response.json() == {"ticket_number": "", "ticket_title": "", "time_entries": []}


def test_ticket_description_card_stays_visible_without_description(authenticated_client: TestClient) -> None:
    """Selected tickets without Autotask descriptions still show a context card."""

    mobile_page_response = authenticated_client.get("/home")
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
        active_job.ticket_number = "T20260616.9999"
        active_job.ticket_title = "Ticket without description"
        active_job.ticket_description = None
        active_job.ticket_status = TicketStatus.IN_PROGRESS
        active_job.client_name = "Acme Services"
        active_job.autotask_company_id = 1001
        database_session.commit()

    home_response = authenticated_client.get("/home")
    assert home_response.status_code == 200
    assert "No description exists for this ticket." in home_response.text
    assert (
        '<dd class="active-ticket-description-display" data-active-ticket-description-display>'
        "No description exists for this ticket."
    ) in home_response.text
    active_description_card = re.search(
        r'<div\s+class="metric-card ticket-description-card (?P<classes>[^"]*)"[^>]*data-active-ticket-description-card',
        home_response.text,
        re.S,
    )
    assert active_description_card is not None
    assert "is-hidden" not in active_description_card.group("classes")

    review_response = authenticated_client.get(f"/review/{active_job_id}")
    assert review_response.status_code == 200
    assert "No description exists for this ticket." in review_response.text
    review_description_card = re.search(
        r'<section\s+class="ticket-description-card readonly-context-card (?P<classes>[^"]*)"[^>]*data-review-ticket-description-card',
        review_response.text,
        re.S,
    )
    assert review_description_card is not None
    assert "is-hidden" not in review_description_card.group("classes")


def test_review_accept_still_requires_ticket_number(authenticated_client: TestClient) -> None:
    """Review save path is permissive, but submission still requires a ticket number."""

    mobile_page_response = authenticated_client.get("/home")
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

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)

    accept_response = authenticated_client.post(
        f"/review/{active_job_id}/accept",
        data={
            "csrf_token": review_csrf_token,
            "ticket_number": "",
            "ticket_status": "complete",
            "job_date": "2026-06-16",
            "start_time": "08:00",
            "end_time": "08:15",
            "summary_notes": "Needs ticket to submit.",
        },
        follow_redirects=False,
    )
    assert accept_response.status_code == 303

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.status == JobStatus.READY_FOR_REVIEW
        assert reviewed_job.autotask_external_id is None


def test_mobile_active_job_save_button_updates_client_and_summary(authenticated_client: TestClient) -> None:
    """Active job save on mobile stores edited client and summary before completion."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Holdings",
            "autotask_company_id": "1002",
            "summary_notes": "Saved from mobile active form",
            "work_location": "on_site",
        },
        follow_redirects=False,
    )
    assert save_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.client_name == "Acme Holdings"
        assert active_job.autotask_company_id == 1002
        assert active_job.summary_notes == "Saved from mobile active form"
        assert active_job.work_location == WorkLocation.ON_SITE
        assert active_job.ticket_number is None
        assert active_job.ticket_title is None

    updated_mobile_page_response = authenticated_client.get("/home")
    updated_mobile_html = updated_mobile_page_response.text
    assert "data-active-ticket-picker" in updated_mobile_html
    assert "On-Site Saved from mobile active form" not in updated_mobile_html


def test_mobile_active_job_background_save_returns_ticket_lookup_context(authenticated_client: TestClient) -> None:
    """Background active saves return JSON for in-place open-ticket loading."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        headers={"Accept": "application/json"},
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "summary_notes": "Save before loading tickets.",
            "work_location": "remote",
        },
    )

    assert save_response.status_code == 200
    response_payload = save_response.json()
    assert response_payload["client_name"] == "Acme Services"
    assert response_payload["autotask_company_id"] == 1001
    assert response_payload["ticket_number"] is None
    assert response_payload["work_location"] == "remote"

    ticket_lookup_response = authenticated_client.get(f"/review/{active_job_id}/tickets")
    assert ticket_lookup_response.status_code == 200
    assert ticket_lookup_response.json()["tickets"][0]["ticket_number"] == "T20260616.0001"


def test_mobile_audio_stream_requires_csrf(authenticated_client: TestClient) -> None:
    """The WebSocket audio stream validates CSRF before accepting audio bytes."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    with authenticated_client.websocket_connect(f"/jobs/{active_job_id}/description/audio/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "csrf_token": "not-the-session-token",
                "content_type": "audio/webm",
                "filename": "recording.webm",
            }
        )
        error_payload = websocket.receive_json()
        assert error_payload["type"] == "error"
        assert "CSRF" in error_payload["detail"]
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_mobile_audio_stream_transcribes_chunks(authenticated_client: TestClient) -> None:
    """Chunked WebSocket audio is transcribed and saved on finish."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    with authenticated_client.websocket_connect(f"/jobs/{active_job_id}/description/audio/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "csrf_token": csrf_token,
                "content_type": "audio/webm",
                "filename": "recording.webm",
            }
        )
        ready_payload = websocket.receive_json()
        assert ready_payload["type"] == "ready"

        websocket.send_bytes(b"first audio chunk")
        websocket.send_bytes(b"second audio chunk")
        websocket.send_json({"type": "finish"})

        final_payload = None
        for _message_number in range(10):
            received_payload = websocket.receive_json()
            if received_payload["type"] == "final":
                final_payload = received_payload
                break

        assert final_payload is not None
        assert final_payload["summary_notes"] == "Mock transcript from streamed-recording.webm. Replace this text during review."
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.summary_notes == "Mock transcript from streamed-recording.webm. Replace this text during review."
        assert active_job.transcription_status == TranscriptionStatus.SUCCEEDED
        stream_started_event = database_session.query(AuditEvent).filter_by(action="job.description.audio_stream_started").one()
        stream_transcribed_event = database_session.query(AuditEvent).filter_by(action="job.description.audio_stream_transcribed").one()
        assert stream_started_event.job_id == active_job_id
        assert stream_transcribed_event.job_id == active_job_id
        assert stream_transcribed_event.details["chunk_count"] == 2


def test_review_detail_record_button_only_for_unsubmitted_jobs(authenticated_client: TestClient) -> None:
    """Review detail shows recording only until the job has a submitted Autotask entry."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "summary_notes": "Ready to review.",
        },
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    assert review_page_response.status_code == 200
    assert "data-review-record-button" in review_page_response.text
    assert ">Record</span>" in review_page_response.text
    assert "Record Audio" not in review_page_response.text
    assert 'class="summary-action-row review-summary-action-row recording-control-stack"' in review_page_response.text
    assert 'class="review-action-stack"' in review_page_response.text
    assert 'class="button-pair-row review-action-row"' in review_page_response.text

    submitted_job_id, _review_csrf_token = create_submitted_mock_job(authenticated_client)
    submitted_review_page_response = authenticated_client.get(f"/review/{submitted_job_id}")
    assert submitted_review_page_response.status_code == 200
    assert "data-review-record-button" not in submitted_review_page_response.text


def test_review_audio_stream_transcribes_unsubmitted_job(authenticated_client: TestClient) -> None:
    """The shared audio stream can update a review job before Autotask submission."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "summary_notes": "Original review notes.",
        },
        follow_redirects=False,
    )
    assert end_response.status_code == 303
    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)

    with authenticated_client.websocket_connect(f"/jobs/{active_job_id}/description/audio/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "csrf_token": review_csrf_token,
                "content_type": "audio/webm",
                "filename": "review-recording.webm",
            }
        )
        ready_payload = websocket.receive_json()
        assert ready_payload["type"] == "ready"

        websocket.send_bytes(b"review audio chunk")
        websocket.send_json({"type": "finish"})

        final_payload = None
        for _message_number in range(10):
            received_payload = websocket.receive_json()
            if received_payload["type"] == "final":
                final_payload = received_payload
                break

        assert final_payload is not None
        assert final_payload["summary_notes"] == "Mock transcript from streamed-recording.webm. Replace this text during review."
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.status == JobStatus.READY_FOR_REVIEW
        assert reviewed_job.summary_notes == "Mock transcript from streamed-recording.webm. Replace this text during review."
        assert reviewed_job.transcription_status == TranscriptionStatus.SUCCEEDED


def test_submitted_job_audio_stream_is_blocked(authenticated_client: TestClient) -> None:
    """Submitted Autotask jobs must not accept later audio transcript changes."""

    submitted_job_id, review_csrf_token = create_submitted_mock_job(authenticated_client)

    with authenticated_client.websocket_connect(f"/jobs/{submitted_job_id}/description/audio/stream") as websocket:
        websocket.send_json(
            {
                "type": "start",
                "csrf_token": review_csrf_token,
                "content_type": "audio/webm",
                "filename": "submitted-recording.webm",
            }
        )
        error_payload = websocket.receive_json()
        assert error_payload["type"] == "error"
        assert "Submitted Autotask jobs" in error_payload["detail"]
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_mobile_active_job_ticket_number_update(authenticated_client: TestClient) -> None:
    """The active ticket picker endpoint persists a server-verified Autotask ticket."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id
        assert active_job.ticket_number is None

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    select_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0002"},
    )
    assert select_ticket_response.status_code == 200
    assert select_ticket_response.json() == {
        "ticket_number": "T20260616.0002",
        "ticket_title": "Mock follow-up ticket for Acme Services",
        "ticket_description": "Mock follow-up description for Acme Services.",
        "ticket_status": "in_progress",
        "ticket_status_label": "Follow Up",
    }

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        assert active_job.ticket_number == "T20260616.0002"
        assert active_job.ticket_title == "Mock follow-up ticket for Acme Services"
        assert active_job.ticket_description == "Mock follow-up description for Acme Services."
        assert active_job.ticket_status == TicketStatus.IN_PROGRESS

    updated_mobile_page_response = authenticated_client.get("/home")
    updated_mobile_html = updated_mobile_page_response.text
    assert "data-active-ticket-picker" not in updated_mobile_html
    assert '<dt>Ticket number</dt>' in updated_mobile_html
    assert '<dt>Ticket name</dt>' in updated_mobile_html
    assert "T20260616.0002" in updated_mobile_html
    assert "Mock follow-up ticket for Acme Services" in updated_mobile_html
    assert "Mock follow-up description for Acme Services." in updated_mobile_html
    assert "data-active-ticket-title-card" in updated_mobile_html
    assert "data-active-ticket-description-card" in updated_mobile_html


def test_mobile_active_ticket_status_is_editable(authenticated_client: TestClient) -> None:
    """Work in Progress ticket status should autosave with active-job edits."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    active_mobile_response = authenticated_client.get("/home")
    assert active_mobile_response.status_code == 200
    active_mobile_html = active_mobile_response.text
    assert 'data-active-ticket-status-input' in active_mobile_html
    assert 'name="ticket_status"' in active_mobile_html

    save_status_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        headers={"Accept": "application/json"},
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "ticket_status": "waiting_customer",
        },
    )

    assert save_status_response.status_code == 200
    assert save_status_response.json()["ticket_status"] == "waiting_customer"
    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.ticket_status == TicketStatus.WAITING_CUSTOMER


def test_mobile_active_job_date_is_editable(authenticated_client: TestClient) -> None:
    """Work in Progress exposes an editable local job date and persists it."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id
        original_local_start_time = format_local_time(active_job.rounded_start_utc)

    active_mobile_response = authenticated_client.get("/home")
    active_mobile_html = active_mobile_response.text
    assert "Started" not in active_mobile_html
    assert "Job date" in active_mobile_html
    assert 'data-active-job-date-input' in active_mobile_html
    assert f'form="active-ticket-form-{active_job_id}"' in active_mobile_html

    save_date_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        headers={"Accept": "application/json"},
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "job_date": "2026-06-20",
            "ticket_status": "follow_up",
        },
    )

    assert save_date_response.status_code == 200
    assert save_date_response.json()["job_date"] == "2026-06-20"
    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.ACTIVE
        assert active_job.local_work_date == date(2026, 6, 20)
        assert local_date_for(active_job.rounded_start_utc) == date(2026, 6, 20)
        assert format_local_time(active_job.rounded_start_utc) == original_local_start_time

    updated_active_mobile_response = authenticated_client.get("/home")
    assert 'class="date-input-shell"' in updated_active_mobile_response.text
    assert '<span class="date-relative-label" data-date-weekday-label></span>' in updated_active_mobile_response.text

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.status == JobStatus.READY_FOR_REVIEW
        assert reviewed_job.local_work_date == date(2026, 6, 20)


def test_mobile_service_call_start_populates_active_job(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clicking a service call starts a job from server-resolved Autotask data."""

    monkeypatch.setattr(
        "job_logger.routes.mobile.now_utc",
        lambda: datetime(2026, 6, 28, 13, 0, tzinfo=UTC),
    )

    mobile_page_response = authenticated_client.get("/home")
    mobile_html = mobile_page_response.text
    csrf_token = extract_csrf_token(mobile_html)

    assert "Service calls" in mobile_html
    assert 'data-service-call-date-previous' in mobile_html
    assert 'data-service-call-date-button' in mobile_html
    assert 'data-service-call-date-next' in mobile_html
    assert 'data-service-call-date-input' in mobile_html
    assert "Loading service calls..." in mobile_html
    assert 'data-service-call-url="/home/service-calls"' in mobile_html
    assert "Mock onsite service call" not in mobile_html
    assert "Scheduled Service Client" not in mobile_html
    assert "Mock open ticket for Scheduled Service Client" not in mobile_html
    assert "T20260616.0001 - Mock open ticket for Scheduled Service Client" not in mobile_html

    service_calls_response = authenticated_client.get("/home/service-calls?date=2026-06-20")
    assert service_calls_response.status_code == 200
    service_calls_payload = service_calls_response.json()
    assert service_calls_payload["active_job_slots_available"] is True
    assert service_calls_payload["selected_date"] == "2026-06-20"
    assert service_calls_payload["previous_date"] == "2026-06-19"
    assert service_calls_payload["next_date"] == "2026-06-21"
    assert service_calls_payload["date_label"] == "June 20th (Saturday)"
    assert "No service calls are scheduled for" in service_calls_payload["empty_message"]
    assert service_calls_payload["service_calls"][0] == {
        "service_call_ticket_id": 6101,
        "client_name": "Scheduled Service Client",
        "ticket_title": "Mock open ticket for Scheduled Service Client",
        "scheduled_time_range": "12:00pm-1:00pm",
        "work_location_label": "On-Site",
        "work_location_class": "service-call-location-on_site",
        "ticket_status_label": "New",
    }
    assert service_calls_payload["service_calls"][1]["work_location_class"] == "service-call-location-remote"

    start_response = authenticated_client.post(
        "/jobs/start/service-call",
        data={"csrf_token": csrf_token, "service_call_ticket_id": "6101", "service_call_date": "2026-06-20"},
        follow_redirects=False,
    )
    assert start_response.status_code == 303
    assert start_response.headers["location"] == "/home"

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        assert active_job.client_name == "Scheduled Service Client"
        assert active_job.autotask_company_id == 1001
        assert active_job.ticket_number == "T20260616.0001"
        assert active_job.ticket_title == "Mock open ticket for Scheduled Service Client"
        assert active_job.ticket_description == "Mock ticket description from scheduled service call."
        assert active_job.ticket_status == TicketStatus.IN_PROGRESS
        assert active_job.work_location == WorkLocation.ON_SITE
        start_audit_event = database_session.query(AuditEvent).filter_by(action="job.started").one()
        assert start_audit_event.details["source"] == "autotask_service_call"
        assert start_audit_event.details["service_call_id"] == 6001
        assert start_audit_event.details["service_call_ticket_id"] == 6101
        assert start_audit_event.details["service_call_date"] == "2026-06-20"
        assert start_audit_event.details["autotask_ticket_status_label"] == "New"
        assert start_audit_event.details["ticket_status_source"] == "local_selection_default"
        assert "autotask_ticket_status_changed_to_in_progress" not in start_audit_event.details

    updated_mobile_page_response = authenticated_client.get("/home")
    updated_mobile_html = updated_mobile_page_response.text
    assert "T20260616.0001" in updated_mobile_html
    assert "Mock open ticket for Scheduled Service Client" in updated_mobile_html
    assert "Mock ticket description from scheduled service call." in updated_mobile_html
    assert "data-active-ticket-picker" not in updated_mobile_html


def test_mobile_service_call_start_rejects_unlisted_selection(authenticated_client: TestClient) -> None:
    """Crafted service-call IDs must not create jobs from unverified browser data."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post(
        "/jobs/start/service-call",
        data={"csrf_token": csrf_token, "service_call_ticket_id": "9999"},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        assert get_active_job(database_session) is None


def test_completed_local_ticket_filters_service_call_options(authenticated_client: TestClient) -> None:
    """A local Complete time entry should hide its matching service-call ticket."""

    completed_at_utc = datetime(2026, 6, 20, 13, 0, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        database_session.add(
            Job(
                status=JobStatus.READY_FOR_REVIEW,
                web_user_id=user.id,
                ticket_number="T20260616.0001",
                ticket_title="Completed service call ticket",
                ticket_status=TicketStatus.COMPLETE,
                client_name="Scheduled Service Client",
                summary_notes="Completed locally in review.",
                description_text="Completed locally in review.",
                raw_start_utc=completed_at_utc,
                raw_end_utc=completed_at_utc + timedelta(minutes=30),
                rounded_start_utc=completed_at_utc,
                rounded_end_utc=completed_at_utc + timedelta(minutes=30),
                local_work_date=local_date_for(completed_at_utc),
                work_location=WorkLocation.REMOTE,
                transcription_status=TranscriptionStatus.NOT_REQUESTED,
                idempotency_key="completed-service-call-filter-test",
            )
        )
        database_session.commit()

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    service_calls_response = authenticated_client.get("/home/service-calls?date=2026-06-20")

    assert service_calls_response.status_code == 200
    service_call_ids = [
        service_call["service_call_ticket_id"]
        for service_call in service_calls_response.json()["service_calls"]
    ]
    assert service_call_ids == [6102]

    filtered_start_response = authenticated_client.post(
        "/jobs/start/service-call",
        data={"csrf_token": csrf_token, "service_call_ticket_id": "6101", "service_call_date": "2026-06-20"},
        follow_redirects=False,
    )

    assert filtered_start_response.status_code == 303
    with database.SessionLocal() as database_session:
        active_jobs = list(database_session.scalars(select(Job).where(Job.status == JobStatus.ACTIVE)))
        assert active_jobs == []


def test_mobile_service_call_date_labels(authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Service-call day navigation should label relative and calendar dates clearly."""

    monkeypatch.setattr(
        "job_logger.routes.mobile.now_utc",
        lambda: datetime(2026, 6, 20, 13, 0, tzinfo=UTC),
    )

    first_response = authenticated_client.get("/home/service-calls?date=2026-06-01")
    second_response = authenticated_client.get("/home/service-calls?date=2026-06-02")
    third_response = authenticated_client.get("/home/service-calls?date=2026-06-03")
    eleventh_response = authenticated_client.get("/home/service-calls?date=2026-06-11")
    today_response = authenticated_client.get("/home/service-calls?date=2026-06-20")
    yesterday_response = authenticated_client.get("/home/service-calls?date=2026-06-19")
    tomorrow_response = authenticated_client.get("/home/service-calls?date=2026-06-21")
    outside_week_response = authenticated_client.get("/home/service-calls?date=2026-06-25")
    invalid_response = authenticated_client.get("/home/service-calls?date=not-a-date")

    for response in (
        first_response,
        second_response,
        third_response,
        eleventh_response,
        today_response,
        yesterday_response,
        tomorrow_response,
        outside_week_response,
    ):
        assert response.status_code == 200

    assert first_response.json()["date_label"] == "June 1st (Monday)"
    assert second_response.json()["date_label"] == "June 2nd (Tuesday)"
    assert third_response.json()["date_label"] == "June 3rd (Wednesday)"
    assert eleventh_response.json()["date_label"] == "June 11th (Thursday)"
    assert today_response.json()["date_label"] == "Today (Saturday)"
    assert yesterday_response.json()["date_label"] == "Yesterday (Friday)"
    assert tomorrow_response.json()["date_label"] == "Tomorrow (Sunday)"
    assert outside_week_response.json()["date_label"] == "June 25th (Thursday)"
    assert invalid_response.status_code == 400
    assert invalid_response.json()["detail"] == "Selected service-call date is invalid."


def test_mobile_selected_ticket_title_drives_review_heading(authenticated_client: TestClient) -> None:
    """Tickets selected on mobile keep their Autotask title through review."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    select_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    assert select_ticket_response.status_code == 200

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_html = review_page_response.text

    assert "Mock open ticket for Acme Services" in review_html
    assert "Unassigned Ticket" not in review_html


def test_mobile_active_job_delete_discards_open_job_with_audit(authenticated_client: TestClient) -> None:
    """The mobile delete action removes only an active in-progress job."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    active_page_response = authenticated_client.get("/home")
    assert "<span data-delete-entry-label>Delete</span>" in active_page_response.text
    assert "Delete time entry" not in active_page_response.text
    assert "Delete this time entry? This removes the in-progress entry without sending it to review." in active_page_response.text
    assert 'class="primary-button end-work-button"' in active_page_response.text
    assert 'class="danger-outline-button"' in active_page_response.text

    delete_response = authenticated_client.post(
        f"/jobs/{active_job_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/home"

    with database.SessionLocal() as database_session:
        assert database_session.get(Job, active_job_id) is None
        delete_audit_event = database_session.query(AuditEvent).filter_by(action="job.active.deleted").one()
        assert delete_audit_event.job_id is None
        assert delete_audit_event.details["job_id"] == active_job_id
        assert delete_audit_event.details["job_status"] == "active"


def test_mobile_active_job_ticket_update_preserves_client_name(authenticated_client: TestClient) -> None:
    """Selecting a ticket should preserve a verified Autotask client and lock it."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "North Bay"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.client_name is None
        assert active_job.autotask_company_id is None

    save_verified_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_verified_client_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.client_name == "Acme Services"
        assert active_job.autotask_company_id == 1001

    save_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    assert save_ticket_response.status_code == 200

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.ticket_number == "T20260616.0001"
        assert active_job.ticket_title == "Mock open ticket for Acme Services"
        assert active_job.client_name == "Acme Services"
        assert active_job.autotask_company_id == 1001

    updated_mobile_page_response = authenticated_client.get("/home")
    page_html = updated_mobile_page_response.text
    assert 'data-locked-client-field' in page_html
    assert "Acme Services" in page_html
    assert f'id="active-client-name-{active_job_id}"' not in page_html

    tampered_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Wrong Client"},
        follow_redirects=False,
    )
    assert tampered_client_response.status_code == 303

    tampered_company_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1002"},
        follow_redirects=False,
    )
    assert tampered_company_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.ACTIVE
        assert active_job.ticket_number == "T20260616.0001"
        assert active_job.client_name == "Acme Services"
        assert active_job.autotask_company_id == 1001

    tampered_end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={
            "csrf_token": csrf_token,
            "client_name": "Wrong Client",
            "autotask_company_id": "1001",
            "summary_notes": "Attempted end with changed client.",
            "work_location": "remote",
            "ticket_status": "in_progress",
        },
        follow_redirects=False,
    )
    assert tampered_end_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.ACTIVE
        assert active_job.client_name == "Acme Services"


def test_mobile_active_job_rounded_start_can_be_adjusted(authenticated_client: TestClient) -> None:
    """The active job rounded start time can be incremented in 15-minute steps."""

    mobile_page_response = authenticated_client.get("/home")
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


def test_mobile_active_job_rounded_start_can_be_set_from_time_input(authenticated_client: TestClient) -> None:
    """The editable Work in Progress start time saves through the active-job route."""

    mobile_page_response = authenticated_client.get("/home")
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

    save_response = authenticated_client.post(
        f"/jobs/{active_job_id}/start-time",
        headers={"Accept": "application/json"},
        data={"csrf_token": csrf_token, "job_date": "2026-06-16", "rounded_start_time": "9:07 am"},
    )

    assert save_response.status_code == 200
    assert save_response.json()["rounded_start_time"] == "9:00 am"
    assert save_response.json()["job_date"] == "2026-06-16"
    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert format_local_time(active_job.rounded_start_utc) == "9:00 am"
        assert active_job.local_work_date == date(2026, 6, 16)
        audit_event = database_session.query(AuditEvent).filter_by(action="job.rounded_start.set").one()
        assert audit_event.job_id == active_job_id


def test_mobile_active_job_rounded_start_rejects_selector_payload(authenticated_client: TestClient) -> None:
    """The active rounded-start route accepts bounded deltas, not arbitrary selector values."""

    mobile_page_response = authenticated_client.get("/home")
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
        original_start = active_job.rounded_start_utc

    adjust_response = authenticated_client.post(
        f"/jobs/{active_job_id}/start-time/adjust",
        data={"csrf_token": csrf_token, "rounded_start_time": "12:00"},
        follow_redirects=False,
    )
    assert adjust_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.rounded_start_utc == original_start
        adjustment_audit_events = database_session.query(AuditEvent).filter_by(action="job.rounded_start.adjusted").all()
        assert adjustment_audit_events == []


def test_mobile_active_job_rounded_stop_can_be_adjusted_and_used_on_end(authenticated_client: TestClient) -> None:
    """A manually adjusted active rounded stop is used when the job ends."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    rounded_start = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id
        active_job.rounded_start_utc = rounded_start
        active_job.rounded_end_utc = rounded_start + timedelta(minutes=15)
        active_job.local_work_date = rounded_start.date()
        database_session.commit()

    adjust_response = authenticated_client.post(
        f"/jobs/{active_job_id}/stop-time/adjust",
        data={"csrf_token": csrf_token, "delta_minutes": 15},
        follow_redirects=False,
    )
    assert adjust_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.status == JobStatus.ACTIVE
        assert active_job.rounded_end_utc == (rounded_start + timedelta(minutes=30)).replace(tzinfo=None)
        adjustment_audit_event = database_session.query(AuditEvent).filter_by(action="job.rounded_stop.adjusted").one()
        assert adjustment_audit_event.job_id == active_job_id

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    with database.SessionLocal() as database_session:
        ended_job = database_session.get(Job, active_job_id)
        assert ended_job is not None
        assert ended_job.status == JobStatus.READY_FOR_REVIEW
        assert ended_job.rounded_end_utc == (rounded_start + timedelta(minutes=30)).replace(tzinfo=None)


def test_mobile_active_job_rounded_stop_can_be_set_from_time_input(authenticated_client: TestClient) -> None:
    """The editable Work in Progress stop time saves as a rounded stop override."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    rounded_start = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id
        active_job.rounded_start_utc = rounded_start
        active_job.rounded_end_utc = None
        active_job.local_work_date = local_date_for(rounded_start)
        database_session.commit()

    save_response = authenticated_client.post(
        f"/jobs/{active_job_id}/stop-time",
        headers={"Accept": "application/json"},
        data={"csrf_token": csrf_token, "job_date": "2026-06-16", "rounded_stop_time": "9:07 am"},
    )

    assert save_response.status_code == 200
    assert save_response.json()["rounded_stop_time"] == "9:15 am"
    assert save_response.json()["rounded_stop_overridden"] is True
    assert save_response.json()["duration_label"] == "1.25 Hours"
    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert format_local_time(active_job.rounded_end_utc) == "9:15 am"
        audit_event = database_session.query(AuditEvent).filter_by(action="job.rounded_stop.set").one()
        assert audit_event.job_id == active_job_id


def test_mobile_active_job_rounded_stop_rejects_time_before_start(authenticated_client: TestClient) -> None:
    """The editable active stop time must stay after the rounded start time."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    rounded_start = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id
        active_job.rounded_start_utc = rounded_start
        active_job.rounded_end_utc = None
        active_job.local_work_date = local_date_for(rounded_start)
        database_session.commit()

    save_response = authenticated_client.post(
        f"/jobs/{active_job_id}/stop-time",
        headers={"Accept": "application/json"},
        data={"csrf_token": csrf_token, "job_date": "2026-06-16", "rounded_stop_time": "7:45 am"},
    )

    assert save_response.status_code == 400
    assert "after rounded start" in save_response.json()["detail"]
    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.rounded_end_utc is None
        audit_events = database_session.query(AuditEvent).filter_by(action="job.rounded_stop.set").all()
        assert audit_events == []


def test_mobile_active_job_rounded_stop_rejects_selector_payload(authenticated_client: TestClient) -> None:
    """The active rounded-stop route accepts bounded deltas, not arbitrary selector values."""

    mobile_page_response = authenticated_client.get("/home")
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
        assert active_job.rounded_end_utc is None

    adjust_response = authenticated_client.post(
        f"/jobs/{active_job_id}/stop-time/adjust",
        data={"csrf_token": csrf_token, "rounded_stop_time": "12:00"},
        follow_redirects=False,
    )
    assert adjust_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.rounded_end_utc is None
        adjustment_audit_events = database_session.query(AuditEvent).filter_by(action="job.rounded_stop.adjusted").all()
        assert adjustment_audit_events == []


def test_mobile_end_job_rounds_live_stop_up_for_technician(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ending work without an override rounds the stop upward at submit time."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    rounded_start = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id
        active_job.rounded_start_utc = rounded_start
        active_job.rounded_end_utc = None
        active_job.local_work_date = rounded_start.date()
        database_session.commit()

    monkeypatch.setattr("job_logger.services.jobs.now_utc", lambda: datetime(2026, 6, 16, 12, 8, tzinfo=UTC))

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    with database.SessionLocal() as database_session:
        ended_job = database_session.get(Job, active_job_id)
        assert ended_job is not None
        assert ended_job.status == JobStatus.READY_FOR_REVIEW
        assert ended_job.rounded_end_utc == datetime(2026, 6, 16, 12, 15)


def test_review_detail_delete_time_entry_removes_job_and_attempts(authenticated_client: TestClient) -> None:
    """A selected unsubmitted review job can be deleted from the detail view."""

    mobile_page_response = authenticated_client.get("/home")
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
        json={"summary_notes": "Delete workflow test notes"},
    )
    assert text_response.status_code == 200
    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
        },
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    select_ticket_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket",
        headers={"X-CSRF-Token": csrf_token},
        json={"ticket_number": "T20260616.0001"},
    )
    assert select_ticket_response.status_code == 200

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)
    assert "Delete time entry" in review_page_response.text
    assert 'data-confirm-message="This will permanently remove this local time entry and related debug history. Continue?"' in review_page_response.text
    assert "onsubmit=\"return confirm" not in review_page_response.text
    assert "Force purge job" not in review_page_response.text
    assert "Rejection reason" not in review_page_response.text
    assert f'action="/review/{active_job_id}/reject"' not in review_page_response.text

    with database.SessionLocal() as database_session:
        job = database_session.get(Job, active_job_id)
        assert job is not None
        assert job.status == JobStatus.READY_FOR_REVIEW
        # failed_attempt is non-success submission history that should be removed
        # together with the unsubmitted review job during local time-entry deletion.
        failed_attempt = SubmissionAttempt(
            job_id=active_job_id,
            provider="mock",
            idempotency_key=job.idempotency_key,
            succeeded=False,
            safe_error="Safe test failure before successful submission.",
            request_snapshot={},
        )
        database_session.add(failed_attempt)
        database_session.commit()
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


def test_review_detail_delete_time_entry_allows_active_job(authenticated_client: TestClient) -> None:
    """Active jobs can be explicitly deleted from the review detail endpoint."""

    mobile_page_response = authenticated_client.get("/home")
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
    assert purge_response.headers["location"] == "/review"

    with database.SessionLocal() as database_session:
        assert database_session.get(Job, active_job_id) is None


def test_manual_summary_carries_to_review_on_completion(authenticated_client: TestClient) -> None:
    """Text typed in the mobile summary field persists when work is ended."""

    mobile_page_response = authenticated_client.get("/home")
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

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={
            "csrf_token": csrf_token,
            "client_name": "Acme Services",
            "autotask_company_id": "1001",
            "summary_notes": "Prepared and repaired the UPS with two-hour follow up",
        },
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    assert "Prepared and repaired the UPS with two-hour follow up" in review_page_response.text

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.summary_notes == "Prepared and repaired the UPS with two-hour follow up"
        assert reviewed_job.client_name == "Acme Services"


def test_mobile_allows_two_active_jobs(authenticated_client: TestClient) -> None:
    """Only two jobs can remain active at the same time."""

    mobile_page_response = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    first_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert first_response.status_code == 303

    second_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert second_response.status_code == 303

    third_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert third_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_jobs = database_session.query(Job).where(Job.status == JobStatus.ACTIVE).all()
        assert len(active_jobs) == 2
        active_slots = {job.job_slot for job in active_jobs if job.job_slot is not None}
        assert active_slots == {1, 2}
        assert all(job.client_name is None for job in active_jobs)
        assert all(job.ticket_number is None for job in active_jobs)
