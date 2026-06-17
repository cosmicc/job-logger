"""Tests for Autotask troubleshooting diagnostics pages."""

from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from job_logger import database
from job_logger.models import SubmissionAttempt
from job_logger.services.jobs import get_active_job
from job_logger.version import APP_VERSION
from tests.conftest import extract_csrf_token


def test_application_version_matches_package_metadata() -> None:
    """The displayed runtime version should match packaging metadata."""

    # pyproject_version is read from source metadata so future version bumps do
    # not accidentally update diagnostics without updating the built package.
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject_version = tomllib.loads(pyproject_path.read_text()).get("project", {}).get("version")
    assert pyproject_version == APP_VERSION


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
            "client_name": "Debug Client",
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

    description_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "Checked connection diagnostics for one test submission."},
    )
    assert description_response.status_code == 200

    end_response = authenticated_client.post(
        f"/jobs/{active_job_id}/end",
        data={"csrf_token": csrf_token, "client_name": "Debug Client"},
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
    assert "Application version" in debug_response.text
    assert APP_VERSION in debug_response.text
    assert attempts[0].id in debug_response.text
    assert "mock-time-entry" in debug_response.text


def test_debug_route_tests_autotask_api(authenticated_client: TestClient) -> None:
    """The debug page can run the safe Autotask API connectivity check."""

    debug_page_response = authenticated_client.get("/debug")
    debug_csrf_token = extract_csrf_token(debug_page_response.text)

    test_response = authenticated_client.post(
        "/debug/autotask/test",
        data={"csrf_token": debug_csrf_token},
        follow_redirects=False,
    )
    assert test_response.status_code == 303

    debug_result_response = authenticated_client.get("/debug")

    assert debug_result_response.status_code == 200
    assert "Last Autotask API test" in debug_result_response.text
    assert "Mock Autotask provider is available" in debug_result_response.text
