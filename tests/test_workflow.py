"""End-to-end tests for the local job workflow in mock provider mode."""

from __future__ import annotations

import re
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from job_logger import database
from job_logger.enums import JobStatus, TranscriptionStatus, WorkLocation
from job_logger.models import AuditEvent, Job, SubmissionAttempt
from job_logger.services.autotask import AutotaskConnectivityResult
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
            "client_name": "Acme Energy",
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
        "ticket_title": "Mock open ticket for Acme Energy",
        "ticket_description": "Mock ticket description for Acme Energy.",
    }

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Acme Energy", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    assert "Mock open ticket for Acme Energy" in review_page_response.text
    review_csrf_token = extract_csrf_token(review_page_response.text)

    accept_response = authenticated_client.post(
        f"/review/{active_job_id}/accept",
        data={
            "csrf_token": review_csrf_token,
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


def test_start_work_blocks_when_autotask_is_unavailable(authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The mandatory Autotask dependency must be healthy before new work starts."""

    def failed_connectivity_check() -> AutotaskConnectivityResult:
        """Return a deterministic failed dependency result for start gating."""

        return AutotaskConnectivityResult(
            provider="autotask",
            available=False,
            summary="Autotask API check failed with HTTP 401.",
            tips=("Verify the API user credentials.",),
            checked_operations=("configuration", "companies"),
        )

    monkeypatch.setattr("job_logger.routes.mobile.test_cached_autotask_connectivity_for_start", failed_connectivity_check)
    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token, "client_name": "Blocked Client"},
        follow_redirects=False,
    )

    assert start_response.status_code == 303
    with database.SessionLocal() as database_session:
        assert get_active_job(database_session) is None


def test_active_job_completion_requires_client_name(authenticated_client: TestClient) -> None:
    """Jobs without a client name cannot be moved from active to review."""

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


def test_mobile_autotask_company_lookup_returns_options(authenticated_client: TestClient) -> None:
    """Authenticated mobile users can query safe Autotask company options."""

    response = authenticated_client.get("/autotask/companies?query=Acme")

    assert response.status_code == 200
    response_payload = response.json()
    assert response_payload["companies"][0]["company_id"] == 1001
    assert response_payload["companies"][0]["company_name"] == "Acme Services"


def test_mobile_job_start_ignores_prestart_client_and_ticket_fields(authenticated_client: TestClient) -> None:
    """Starting work creates a blank job even if stale form fields are posted."""

    mobile_page_response = authenticated_client.get("/mobile")
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
        assert active_job.work_location == WorkLocation.REMOTE

    active_mobile_page_response = authenticated_client.get("/mobile")
    active_mobile_html = active_mobile_page_response.text
    assert "Open tickets" in active_mobile_html
    assert "Find tickets" in active_mobile_html
    assert "Choose a client, then find open tickets." in active_mobile_html
    assert 'data-active-ticket-picker' in active_mobile_html
    assert 'data-auto-load-ticket-options="true"' not in active_mobile_html
    assert active_mobile_html.index('<span class="metric-label">Client name</span>') < active_mobile_html.index("<h3>Open tickets</h3>")


def test_mobile_active_job_page_locks_selected_autotask_client(authenticated_client: TestClient) -> None:
    """The active mobile card renders selected Autotask clients as read-only."""

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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Acme Services", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    updated_mobile_page_response = authenticated_client.get("/mobile")
    page_html = updated_mobile_page_response.text

    assert 'data-locked-client-field' in page_html
    assert "AUTOTASK SELECTED" not in page_html
    assert "Autotask selected" not in page_html
    assert 'class="metric-card client-name-card"' in page_html
    assert f'id="active-client-name-{active_job_id}"' not in page_html
    assert 'class="end-client-name"' in page_html
    assert 'class="end-autotask-company-id"' in page_html
    assert 'class="rounded-start-time-form active-time-step-controls"' in page_html
    assert 'name="rounded_start_time"' not in page_html
    assert 'class="time-field-input rounded-start-time-display"' in page_html
    assert 'name="delta_minutes"' in page_html
    assert 'value="-15"' in page_html
    assert 'value="15"' in page_html
    assert 'class="work-location-switch"' in page_html
    assert 'data-work-location-toggle' in page_html
    assert 'name="work_location"' in page_html
    assert 'value="remote"' in page_html
    assert 'value="on_site"' in page_html
    assert "<dt>Work type</dt>" not in page_html
    assert 'class="segmented-toggle work-location-toggle"' not in page_html
    assert 'data-active-ticket-picker' in page_html
    assert f'data-ticket-select-url="/jobs/{active_job_id}/ticket"' in page_html
    assert 'data-auto-load-ticket-options="true"' in page_html
    assert 'data-active-ticket-lookup-button' in page_html
    assert "Find tickets" in page_html
    assert page_html.index("<dt>Client name</dt>") < page_html.index("<h3>Open tickets</h3>")
    assert page_html.index(f'id="active-ticket-form-{active_job_id}"') < page_html.index("<h3>Open tickets</h3>")
    assert 'class="secondary-button active-save-button"' in page_html
    assert "submit-notes-button" not in page_html
    assert page_html.index("Summary notes") < page_html.index("Save Active Changes") < page_html.index("Record Audio")
    assert "Record Notes" not in page_html
    assert "Autotask ticket number" not in page_html
    assert 'class="active-ticket-number"' in page_html
    assert 'pattern="[Tt][0-9]{8}\\.[0-9]{4}"' not in page_html
    assert 'pattern="[Tt][0-9]{8}\\\\.[0-9]{4}"' not in page_html
    assert re.search(r">\s*\+15\s*</button>", page_html)
    assert re.search(r">\s*-15\s*</button>", page_html)


def test_mobile_active_job_locked_autotask_company_rejects_form_tampering(authenticated_client: TestClient) -> None:
    """Mobile form handlers preserve an already selected active-job company."""

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

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Review Save Client"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)

    save_response = authenticated_client.post(
        f"/review/{active_job_id}/save",
        data={
            "csrf_token": review_csrf_token,
            "ticket_number": "",
            "ticket_status": "complete",
            "start_date": "2026-06-16",
            "start_time": "08:00",
            "end_date": "2026-06-16",
            "end_time": "08:15",
            "summary_notes": "Editable without ticket during save.",
        },
        follow_redirects=False,
    )
    assert save_response.status_code == 303

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.status == JobStatus.READY_FOR_REVIEW
        assert reviewed_job.ticket_number is None
        assert reviewed_job.summary_notes == "Editable without ticket during save."


def test_review_save_active_job_without_stop_time(authenticated_client: TestClient) -> None:
    """Active jobs can be saved in review without end date or end time."""

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
        active_job_local_start = active_job.rounded_start_utc.astimezone(ZoneInfo("America/Detroit"))
        assert active_job.rounded_end_utc is None

    review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    review_csrf_token = extract_csrf_token(review_page_response.text)

    save_response = authenticated_client.post(
        f"/review/{active_job_id}/save",
        data={
            "csrf_token": review_csrf_token,
            "ticket_status": "complete",
            "start_date": active_job_local_start.date().isoformat(),
            "start_time": active_job_local_start.strftime("%H:%M"),
            "summary_notes": "Active job saved without stop values.",
        },
        follow_redirects=False,
    )
    assert save_response.status_code == 303

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.status == JobStatus.ACTIVE
        assert reviewed_job.rounded_end_utc is None
        assert reviewed_job.client_name is None
        assert reviewed_job.summary_notes == "Active job saved without stop values."
        assert reviewed_job.ticket_number is None


def test_review_ticket_lookup_returns_open_tickets_for_job_client(authenticated_client: TestClient) -> None:
    """Review can request open Autotask ticket options using the selected company."""

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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Ticket Lookup Client", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.autotask_company_id == 1001

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Ticket Lookup Client", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert end_response.status_code == 303

    ticket_lookup_response = authenticated_client.get(f"/review/{active_job_id}/tickets")

    assert ticket_lookup_response.status_code == 200
    response_payload = ticket_lookup_response.json()
    assert response_payload["client_name"] == "Ticket Lookup Client"
    assert response_payload["autotask_company_id"] == 1001
    assert response_payload["tickets"][0]["ticket_number"] == "T20260616.0001"
    assert response_payload["tickets"][0]["company_name"] == "Ticket Lookup Client"
    assert response_payload["tickets"][0]["description"] == "Mock ticket description for Ticket Lookup Client."


def test_selected_ticket_title_drives_review_heading_and_hides_lookup(authenticated_client: TestClient) -> None:
    """Selecting an Autotask ticket stores the title and locks review identity fields."""

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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Ticket Title Client", "autotask_company_id": "1001"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Ticket Title Client", "autotask_company_id": "1001"},
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
        "ticket_title": "Mock open ticket for Ticket Title Client",
        "ticket_description": "Mock ticket description for Ticket Title Client.",
    }

    with database.SessionLocal() as database_session:
        reviewed_job = database_session.get(Job, active_job_id)
        assert reviewed_job is not None
        assert reviewed_job.ticket_number == "T20260616.0001"
        assert reviewed_job.ticket_title == "Mock open ticket for Ticket Title Client"
        assert reviewed_job.ticket_description == "Mock ticket description for Ticket Title Client."
        assert reviewed_job.client_name == "Ticket Title Client"
        assert reviewed_job.autotask_company_id == 1001

    updated_review_page_response = authenticated_client.get(f"/review/{active_job_id}")
    updated_review_html = updated_review_page_response.text
    assert "Mock open ticket for Ticket Title Client" in updated_review_html
    assert "Mock ticket description for Ticket Title Client." in updated_review_html
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
            "start_date": "2026-06-16",
            "start_time": "08:00",
            "end_date": "2026-06-16",
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
        assert reviewed_job.ticket_title == "Mock open ticket for Ticket Title Client"
        assert reviewed_job.ticket_description == "Mock ticket description for Ticket Title Client."
        assert reviewed_job.client_name == "Ticket Title Client"
        assert reviewed_job.autotask_company_id == 1001
        assert reviewed_job.summary_notes == "Review save must not rewrite read-only identity fields."


def test_review_accept_still_requires_ticket_number(authenticated_client: TestClient) -> None:
    """Review save path is permissive, but submission still requires a ticket number."""

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

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Review Accept Client"},
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
            "start_date": "2026-06-16",
            "start_time": "08:00",
            "end_date": "2026-06-16",
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

    save_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "client_name": "Mobile Review Client",
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
        assert active_job.client_name == "Mobile Review Client"
        assert active_job.autotask_company_id == 1002
        assert active_job.summary_notes == "Saved from mobile active form"
        assert active_job.work_location == WorkLocation.ON_SITE
        assert active_job.ticket_number is None
        assert active_job.ticket_title is None

    updated_mobile_page_response = authenticated_client.get("/mobile")
    updated_mobile_html = updated_mobile_page_response.text
    assert "data-active-ticket-picker" in updated_mobile_html
    assert "On-Site Saved from mobile active form" not in updated_mobile_html


def test_mobile_active_job_background_save_returns_ticket_lookup_context(authenticated_client: TestClient) -> None:
    """Background active saves return JSON for in-place open-ticket loading."""

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

    save_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        headers={"Accept": "application/json"},
        data={
            "csrf_token": csrf_token,
            "client_name": "Background Save Client",
            "autotask_company_id": "1001",
            "summary_notes": "Save before loading tickets.",
            "work_location": "remote",
        },
    )

    assert save_response.status_code == 200
    response_payload = save_response.json()
    assert response_payload["client_name"] == "Background Save Client"
    assert response_payload["autotask_company_id"] == 1001
    assert response_payload["ticket_number"] is None
    assert response_payload["work_location"] == "remote"

    ticket_lookup_response = authenticated_client.get(f"/review/{active_job_id}/tickets")
    assert ticket_lookup_response.status_code == 200
    assert ticket_lookup_response.json()["tickets"][0]["ticket_number"] == "T20260616.0001"


def test_mobile_audio_stream_requires_csrf(authenticated_client: TestClient) -> None:
    """The WebSocket audio stream validates CSRF before accepting audio bytes."""

    mobile_page_response = authenticated_client.get("/mobile")
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

    mobile_page_response = authenticated_client.get("/mobile")
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


def test_mobile_active_job_ticket_number_update(authenticated_client: TestClient) -> None:
    """The active ticket picker endpoint persists a server-verified Autotask ticket."""

    mobile_page_response = authenticated_client.get("/mobile")
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
        data={"csrf_token": csrf_token, "client_name": "Mobile Ticket Client", "autotask_company_id": "1001"},
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
        "ticket_title": "Mock open ticket for Mobile Ticket Client",
        "ticket_description": "Mock ticket description for Mobile Ticket Client.",
    }

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        assert active_job.ticket_number == "T20260616.0001"
        assert active_job.ticket_title == "Mock open ticket for Mobile Ticket Client"
        assert active_job.ticket_description == "Mock ticket description for Mobile Ticket Client."

    updated_mobile_page_response = authenticated_client.get("/mobile")
    updated_mobile_html = updated_mobile_page_response.text
    assert "data-active-ticket-picker" not in updated_mobile_html
    assert '<dt>Ticket number</dt>' in updated_mobile_html
    assert '<dt>Ticket name</dt>' in updated_mobile_html
    assert "T20260616.0001" in updated_mobile_html
    assert "Mock open ticket for Mobile Ticket Client" in updated_mobile_html
    assert "Mock ticket description for Mobile Ticket Client." in updated_mobile_html
    assert "data-active-ticket-title-card" in updated_mobile_html
    assert "data-active-ticket-description-card" in updated_mobile_html


def test_mobile_selected_ticket_title_drives_review_heading(authenticated_client: TestClient) -> None:
    """Tickets selected on mobile keep their Autotask title through review."""

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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "Mobile Heading Client", "autotask_company_id": "1001"},
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

    assert "Mock open ticket for Mobile Heading Client" in review_html
    assert "Unassigned Ticket" not in review_html


def test_mobile_active_job_delete_discards_open_job_with_audit(authenticated_client: TestClient) -> None:
    """The mobile delete action removes only an active in-progress job."""

    mobile_page_response = authenticated_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_page_response.text)

    start_response = authenticated_client.post("/jobs/start", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = get_active_job(database_session)
        assert active_job is not None
        active_job_id = active_job.id

    delete_response = authenticated_client.post(
        f"/jobs/{active_job_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/mobile"

    with database.SessionLocal() as database_session:
        assert database_session.get(Job, active_job_id) is None
        delete_audit_event = database_session.query(AuditEvent).filter_by(action="job.active.deleted").one()
        assert delete_audit_event.job_id is None
        assert delete_audit_event.details["job_id"] == active_job_id
        assert delete_audit_event.details["job_status"] == "active"


def test_mobile_active_job_ticket_update_preserves_client_name(authenticated_client: TestClient) -> None:
    """Selecting a ticket from the active card should not erase the client."""

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

    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={"csrf_token": csrf_token, "client_name": "North Bay"},
        follow_redirects=False,
    )
    assert save_client_response.status_code == 303

    with database.SessionLocal() as database_session:
        active_job = database_session.get(Job, active_job_id)
        assert active_job is not None
        assert active_job.client_name == "North Bay"

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
        assert active_job.ticket_title == "Mock open ticket for North Bay"
        assert active_job.client_name == "North Bay"


def test_mobile_active_job_rounded_start_can_be_adjusted(authenticated_client: TestClient) -> None:
    """The active job rounded start time can be incremented in 15-minute steps."""

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


def test_mobile_active_job_rounded_start_rejects_selector_payload(authenticated_client: TestClient) -> None:
    """The active rounded-start route accepts bounded deltas, not arbitrary selector values."""

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
    save_client_response = authenticated_client.post(
        f"/jobs/{active_job_id}/ticket-number",
        data={
            "csrf_token": csrf_token,
            "client_name": "Test Client",
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
