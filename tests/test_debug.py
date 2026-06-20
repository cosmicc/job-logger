"""Tests for Autotask troubleshooting diagnostics pages."""

from __future__ import annotations

import gzip
import json
import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from job_logger import database
from job_logger.enums import JobStatus, TicketStatus, TranscriptionStatus, WorkLocation
from job_logger.models import AuditEvent, Job, SubmissionAttempt
from job_logger.services.jobs import get_active_job
from job_logger.time_utils import format_local_display
from job_logger.version import APP_VERSION
from tests.conftest import extract_csrf_token, login_as_super_admin, login_as_web_user


def _seed_full_backup_data() -> str:
    """Create representative rows for diagnostics backup and restore tests."""

    created_at_utc = datetime(2026, 6, 19, 14, 30, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        job = Job(
            status=JobStatus.READY_FOR_REVIEW,
            ticket_number="T20260619.0001",
            ticket_title="Backup test ticket",
            client_name="Backup Client",
            autotask_company_id=1001,
            ticket_status=TicketStatus.IN_PROGRESS,
            summary_notes="Verified full backup and restore.",
            description_text="Verified full backup and restore.",
            work_location=WorkLocation.REMOTE,
            raw_start_utc=created_at_utc,
            raw_end_utc=created_at_utc,
            rounded_start_utc=created_at_utc,
            rounded_end_utc=created_at_utc,
            transcription_provider="mock",
            transcription_status=TranscriptionStatus.SUCCEEDED,
            autotask_provider="mock",
            idempotency_key="job-backup-test",
            created_at_utc=created_at_utc,
            updated_at_utc=created_at_utc,
        )
        database_session.add(job)
        database_session.flush()
        database_session.add(
            SubmissionAttempt(
                job_id=job.id,
                provider="mock",
                idempotency_key=job.idempotency_key,
                succeeded=True,
                external_id="mock-time-entry-backup-test",
                request_snapshot={"ticket_number": job.ticket_number},
                created_at_utc=created_at_utc,
            )
        )
        database_session.add(
            AuditEvent(
                job_id=job.id,
                actor="admin",
                action="backup.seeded",
                details={"purpose": "backup round trip"},
                created_at_utc=created_at_utc,
            )
        )
        database_session.commit()
        return job.id


def _add_temporary_job() -> str:
    """Add a row that should disappear after a full restore."""

    created_at_utc = datetime(2026, 6, 19, 15, 45, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        job = Job(
            status=JobStatus.ACTIVE,
            client_name="Temporary Client",
            raw_start_utc=created_at_utc,
            rounded_start_utc=created_at_utc,
            work_location=WorkLocation.ON_SITE,
            transcription_status=TranscriptionStatus.NOT_REQUESTED,
            idempotency_key="job-temporary-test",
            created_at_utc=created_at_utc,
            updated_at_utc=created_at_utc,
        )
        database_session.add(job)
        database_session.commit()
        return job.id


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


def test_debug_routes_are_super_admin_only(client: TestClient) -> None:
    """Managed web users must not see or access debug diagnostics."""

    login_as_web_user(client)
    mobile_response = client.get("/mobile")
    assert mobile_response.status_code == 200
    assert 'href="/debug"' not in mobile_response.text

    forbidden_routes = (
        ("GET", "/debug"),
        ("GET", "/debug/logs/login-failures"),
        ("POST", "/debug/autotask/test"),
        ("POST", "/debug/backup"),
        ("POST", "/debug/restore"),
    )
    for method, path in forbidden_routes:
        response = client.request(method, path, follow_redirects=False)
        assert response.status_code == 403

    login_as_super_admin(client)
    users_response = client.get("/users")
    assert users_response.status_code == 200
    assert 'href="/debug"' in users_response.text


def test_openapi_schema_route_is_disabled(client: TestClient) -> None:
    """The app should not expose generated API schema metadata."""

    response = client.get("/openapi.json")

    assert response.status_code == 404


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

    login_as_super_admin(authenticated_client)
    debug_response = authenticated_client.get("/debug")
    assert debug_response.status_code == 200
    assert "Autotask debug" in debug_response.text
    assert "Application version" in debug_response.text
    assert APP_VERSION in debug_response.text
    assert attempt_id in debug_response.text
    assert attempt_display_timestamp in debug_response.text
    assert attempt_iso_timestamp not in debug_response.text
    assert "mock-time-entry" in debug_response.text


def test_debug_route_tests_autotask_api(super_admin_client: TestClient) -> None:
    """The debug page can run the safe Autotask API connectivity check."""

    debug_page_response = super_admin_client.get("/debug")
    debug_csrf_token = extract_csrf_token(debug_page_response.text)

    test_response = super_admin_client.post(
        "/debug/autotask/test",
        data={"csrf_token": debug_csrf_token},
        follow_redirects=False,
    )
    assert test_response.status_code == 303

    debug_result_response = super_admin_client.get("/debug")

    assert debug_result_response.status_code == 200
    assert "Last Autotask API test" in debug_result_response.text
    assert "Mock Autotask provider is available" in debug_result_response.text


def test_debug_full_backup_download_and_restore_round_trip(super_admin_client: TestClient) -> None:
    """Diagnostics can download and restore a full Job Logger data snapshot."""

    original_job_id = _seed_full_backup_data()

    debug_page_response = super_admin_client.get("/debug")
    assert debug_page_response.status_code == 200
    assert "Full data backup" in debug_page_response.text
    csrf_token = extract_csrf_token(debug_page_response.text)

    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))

    assert backup_response.status_code == 200
    assert backup_response.headers["cache-control"] == "no-store"
    assert "job-logger-full-backup" in backup_response.headers["content-disposition"]
    assert payload["format"] == "job_logger.full_backup"
    assert payload["table_counts"]["jobs"] == 1
    assert payload["table_counts"]["submission_attempts"] == 1
    assert payload["table_counts"]["audit_events"] >= 1
    assert payload["tables"]["jobs"][0]["ticket_number"] == "T20260619.0001"
    assert any(row["action"] == "backup.seeded" for row in payload["tables"]["audit_events"])

    temporary_job_id = _add_temporary_job()

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-full-backup.json.gz",
                backup_response.content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )
    assert restore_response.status_code == 303
    assert restore_response.headers["location"] == "/debug#full-backup"

    restored_page_response = super_admin_client.get("/debug")
    assert restored_page_response.status_code == 200
    assert "Full data restore completed." in restored_page_response.text

    with database.SessionLocal() as database_session:
        assert database_session.scalar(select(func.count(Job.id))) == 1
        assert database_session.get(Job, original_job_id) is not None
        assert database_session.get(Job, temporary_job_id) is None
        assert database_session.scalar(select(func.count(SubmissionAttempt.id))) == 1
        actions = list(database_session.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at_utc)))
        assert "backup.seeded" in actions
        assert "debug.full_backup.restored" in actions
        assert "debug.full_backup.downloaded" not in actions


def test_debug_restore_requires_confirmation(super_admin_client: TestClient) -> None:
    """Restore must not replace data unless the operator types RESTORE."""

    _seed_full_backup_data()
    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post("/debug/backup", data={"csrf_token": csrf_token})
    temporary_job_id = _add_temporary_job()

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "restore"},
        files={
            "backup_file": (
                "job-logger-full-backup.json.gz",
                backup_response.content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    assert restore_response.headers["location"] == "/debug#full-backup"
    with database.SessionLocal() as database_session:
        assert database_session.scalar(select(func.count(Job.id))) == 2
        assert database_session.get(Job, temporary_job_id) is not None

    result_page_response = super_admin_client.get("/debug")
    assert "Type RESTORE to confirm full data restore." in result_page_response.text


def test_debug_backup_download_requires_csrf(super_admin_client: TestClient) -> None:
    """Full backup downloads are sensitive and require CSRF protection."""

    response = super_admin_client.post("/debug/backup", data={}, follow_redirects=False)

    assert response.status_code == 403
