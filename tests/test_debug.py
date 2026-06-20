"""Tests for Autotask troubleshooting diagnostics pages."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from job_logger import database
from job_logger.models import SubmissionAttempt
from job_logger.services.jobs import get_active_job
from job_logger.time_utils import format_local_display
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


def test_failed_login_writes_sanitized_log_and_debug_window(client: TestClient) -> None:
    """Failed app logins should be visible in diagnostics without raw passwords."""

    login_page_response = client.get("/login")
    csrf_token = extract_csrf_token(login_page_response.text)
    failed_password = "bad-password"
    failed_response = client.post(
        "/login",
        headers={
            "X-Real-IP": "198.51.100.7",
            "X-Forwarded-For": "203.0.113.9, 10.0.0.2",
            "X-Forwarded-Proto": "https",
            "User-Agent": "Failed Login Test",
        },
        data={
            "csrf_token": csrf_token,
            "username": "bad-user",
            "password": failed_password,
        },
        follow_redirects=False,
    )
    assert failed_response.status_code == 303

    log_path = Path(os.environ["LOGIN_FAILURE_LOG_PATH"])
    log_text = log_path.read_text(encoding="utf-8")
    assert failed_password not in log_text

    log_payload = json.loads(log_text.strip())
    assert log_payload["username"] == "bad-user"
    assert log_payload["client_ip"] == "198.51.100.7"
    assert log_payload["x_real_ip"] == "198.51.100.7"
    assert log_payload["x_forwarded_for"] == "203.0.113.9, 10.0.0.2"
    assert log_payload["forwarded_proto"] == "https"
    assert log_payload["host"] == "testserver"
    assert log_payload["method"] == "POST"
    assert log_payload["path"] == "/login"
    assert log_payload["reason"] == "invalid_credentials"
    assert log_payload["username_length"] == len("bad-user")
    assert log_payload["username_truncated"] is False
    assert log_payload["password_supplied"] is True
    assert log_payload["password_length"] == len(failed_password)
    assert log_payload["user_agent"] == "Failed Login Test"
    assert log_payload["lockout_applied"] is False
    assert "created_at_utc" in log_payload

    login_page_response = client.get("/login")
    csrf_token = extract_csrf_token(login_page_response.text)
    success_response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "username": "admin",
            "password": "test-password",
        },
        follow_redirects=False,
    )
    assert success_response.status_code == 303

    debug_response = client.get("/debug")
    assert debug_response.status_code == 200
    assert "Login failures" in debug_response.text
    assert "bad-user" in debug_response.text
    assert "198.51.100.7" in debug_response.text
    assert "203.0.113.9, 10.0.0.2" in debug_response.text
    assert "Failed Login Test" in debug_response.text
    assert "Invalid Credentials" in debug_response.text
    assert ">12<" in debug_response.text
    assert os.environ["LOGIN_FAILURE_LOG_PATH"] in debug_response.text
    assert failed_password not in debug_response.text

    download_response = client.get("/debug/logs/login-failures")
    assert download_response.status_code == 200
    assert "web_login_failed" in download_response.text
    assert "job-logger-login-failures.log" in download_response.headers["content-disposition"]
    assert download_response.headers["cache-control"] == "no-store"
    assert failed_password not in download_response.text


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
            "job_date": "2026-06-16",
            "start_time": "08:00",
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
        attempt_id = attempts[0].id
        attempt_iso_timestamp = attempts[0].created_at_utc.isoformat()
        attempt_display_timestamp = format_local_display(attempts[0].created_at_utc)

    debug_response = authenticated_client.get("/debug")
    assert debug_response.status_code == 200
    assert "Autotask debug" in debug_response.text
    assert "Application version" in debug_response.text
    assert APP_VERSION in debug_response.text
    assert attempt_id in debug_response.text
    assert attempt_display_timestamp in debug_response.text
    assert attempt_iso_timestamp not in debug_response.text
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
