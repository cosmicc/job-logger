"""Tests for Autotask troubleshooting diagnostics pages."""

from __future__ import annotations

import gzip
import json
import os
import re
import tomllib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from job_logger import database
from job_logger.config import settings
from job_logger.enums import JobStatus, ThemeMode, TicketStatus, TranscriptionStatus, WorkLocation
from job_logger.models import (
    AuditEvent,
    CloudflareIPBlock,
    Job,
    LoginAttempt,
    LoginFailureCounter,
    SubmissionAttempt,
    UserPreference,
    WebAuthnCredential,
    WebUser,
)
from job_logger.routes import debug as debug_routes
from job_logger.services import app_health_monitor, database_diagnostics, pushover, system_health
from job_logger.services.backups import (
    AUTOMATIC_BACKUP_FILENAME_PREFIX,
    AUTOMATIC_BACKUP_FILENAME_SUFFIX,
    AUTOMATIC_BACKUP_TRIGGER_STARTUP,
    automatic_backup_filename,
    create_automatic_backup,
    list_automatic_backup_files,
    run_automatic_backup_once,
)
from job_logger.services.cloudflare_blocks import create_cloudflare_ip_block, ip_is_allowlisted
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


def test_debug_routes_require_debug_access(client: TestClient) -> None:
    """Ordinary managed web users must not see or access debug diagnostics."""

    login_as_web_user(client)
    mobile_response = client.get("/home")
    assert mobile_response.status_code == 200
    assert 'href="/debug"' not in mobile_response.text

    forbidden_routes = (
        ("GET", "/debug"),
        ("GET", "/debug/logs/login-failures"),
        ("GET", "/debug/logs/login-successes"),
        ("POST", "/debug/autotask/test"),
        ("POST", "/debug/sessions/logout-web-users"),
        ("POST", "/debug/login-failures/hide"),
        ("POST", "/debug/cloudflare-blocks/block"),
        ("POST", "/debug/cloudflare-blocks/unblock"),
        ("POST", "/debug/backup"),
        ("POST", "/debug/restore"),
        ("POST", "/debug/automatic-backups/download"),
        ("POST", "/debug/automatic-backups/restore"),
    )
    for method, path in forbidden_routes:
        response = client.request(method, path, follow_redirects=False)
        assert response.status_code == 403

    login_as_super_admin(client)
    users_response = client.get("/users")
    assert users_response.status_code == 200
    assert 'href="/debug"' in users_response.text
    debug_response = client.get("/debug")
    assert debug_response.status_code == 200
    assert 'class="secondary-link-button" href="/review"' not in debug_response.text


def test_managed_admin_can_use_debug_without_super_admin_permissions(client: TestClient) -> None:
    """A checked managed admin should get Diagnostics but no other super-admin access."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.is_admin = True
        database_session.commit()

    login_as_web_user(client)
    home_response = client.get("/home")
    assert home_response.status_code == 200
    assert 'href="/debug"' in home_response.text
    assert "<span>Diag</span>" in home_response.text
    assert ">Debug</a>" not in home_response.text
    assert 'data-mobile-debug-link' in home_response.text
    assert 'href="/users"' not in home_response.text
    assert 'data-mobile-users-link' not in home_response.text
    assert 'href="/config"' in home_response.text
    assert 'data-mobile-config-link' in home_response.text

    debug_response = client.get("/debug")
    assert debug_response.status_code == 200
    assert "Session controls" in debug_response.text
    assert "Managed admins are included because they are managed web users." in debug_response.text

    csrf_token = extract_csrf_token(debug_response.text)
    autotask_response = client.post(
        "/debug/autotask/test",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert autotask_response.status_code == 303
    assert autotask_response.headers["location"] == "/debug"

    with database.SessionLocal() as database_session:
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "debug.autotask_api.tested")
        )
        assert audit_event is not None
        assert audit_event.actor == "tech"


def test_debug_can_force_managed_web_users_to_sign_in_again(client: TestClient) -> None:
    """The diagnostics page should invalidate only managed web-user sessions."""

    login_as_web_user(client)
    assert client.get("/home").status_code == 200

    with TestClient(client.app) as admin_client:
        login_as_super_admin(admin_client)
        debug_response = admin_client.get("/debug")
        assert debug_response.status_code == 200
        assert "Session controls" in debug_response.text
        assert 'id="session-controls" class="table-panel session-controls-card"' in debug_response.text
        assert 'class="debug-test-form session-controls-form"' in debug_response.text
        assert "Log out web users" in debug_response.text
        csrf_token = extract_csrf_token(debug_response.text)
        logout_response = admin_client.post(
            "/debug/sessions/logout-web-users",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert logout_response.status_code == 303
        assert logout_response.headers["location"] == "/debug#session-controls"

        admin_still_signed_in_response = admin_client.get("/debug")
        assert admin_still_signed_in_response.status_code == 200
        assert "Signed out 1 web users. They must sign in again." in admin_still_signed_in_response.text

    web_home_response = client.get("/home", follow_redirects=False)
    assert web_home_response.status_code == 303
    assert web_home_response.headers["location"] == "/login"

    login_response = client.get("/login")
    assert "Your session was signed out by an administrator. Sign in again." in login_response.text

    login_as_web_user(client)
    assert client.get("/home").status_code == 200

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        assert user.sessions_invalidated_at_utc is not None
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "debug.web_user_sessions.invalidated")
        )
        assert audit_event is not None
        assert audit_event.details["affected_user_count"] == 1


def test_debug_page_shows_disk_space_monitor(super_admin_client: TestClient, monkeypatch) -> None:
    """Diagnostics should render app-visible disk usage with warning styling."""

    snapshot = system_health.DebugDiskUsageSnapshot(
        severity="warning",
        status_label="Disk space nearing full",
        warning_free_display="1000.0 MB",
        critical_free_display="250.0 MB",
        volumes=(
            system_health.DebugDiskUsageVolume(
                label="Backup directory",
                configured_path="/data/backups",
                measured_path="/data/backups",
                total_display="100.0 GB",
                used_display="88.6 GB",
                free_display="11.4 GB",
                used_percent=88.6,
                used_percent_display="88.6%",
                severity="warning",
                status_label="Nearing full",
            ),
        ),
    )
    monkeypatch.setattr(debug_routes, "_collect_disk_usage_snapshot", lambda: snapshot)

    response = super_admin_client.get("/debug")

    assert response.status_code == 200
    assert 'id="disk-space"' in response.text
    assert "disk-space-card disk-space-warning" in response.text
    assert "Disk space nearing full" in response.text
    assert "Warning under 1000.0 MB free" in response.text
    assert "critical under 250.0 MB free" in response.text
    assert "Used percentage is informational only" in response.text
    assert "Backup directory" in response.text
    assert "88.6 GB / 100.0 GB (88.6%)" in response.text
    assert "/data/backups" in response.text
    assert 'class="disk-meter disk-meter-warning"' in response.text
    assert 'value="88.6"' in response.text


def test_debug_page_shows_database_connectivity_card(super_admin_client: TestClient) -> None:
    """Diagnostics should show safe database status and pool details."""

    response = super_admin_client.get("/debug")

    assert response.status_code == 200
    assert 'id="database-health"' in response.text
    assert "Database" in response.text
    assert "Query latency" in response.text
    assert "Connected" in response.text
    assert "Backend" in response.text
    assert "sqlite" in response.text
    assert "Driver" in response.text
    assert "pysqlite" in response.text
    assert "Migration revision" in response.text
    assert "Not recorded" in response.text
    assert "Pool class" in response.text
    assert "StaticPool" in response.text
    assert "Checked out" in response.text
    assert "DATABASE_URL" not in response.text
    assert "postgresql://" not in response.text
    assert "job_logger_password" not in response.text


def test_database_diagnostics_snapshot_uses_safe_sqlite_metadata() -> None:
    """Database diagnostics should avoid URL details while measuring connectivity."""

    snapshot = database_diagnostics.collect_database_diagnostics_snapshot()

    assert snapshot.available is True
    assert snapshot.status_label == "Connected"
    assert snapshot.latency_display.endswith(" ms")
    assert snapshot.backend_display == "sqlite"
    assert snapshot.driver_display == "pysqlite"
    assert snapshot.migration_revision == "Not recorded"
    assert snapshot.pool.class_name == "StaticPool"
    assert snapshot.pool.configured_limit_display == "n/a"
    assert snapshot.latency_ms is not None
    assert snapshot.pool.pressure_percent is None


def test_database_diagnostics_snapshot_handles_failed_probe_safely(monkeypatch) -> None:
    """Database diagnostics should not surface raw connection errors."""

    class FakeDialect:
        """Minimal SQLAlchemy dialect metadata used by the snapshot."""

        name = "postgresql"
        driver = "psycopg"

    class FakePool:
        """Minimal pool metrics exposed without endpoint details."""

        @staticmethod
        def size() -> int:
            return 5

        @staticmethod
        def checkedin() -> int:
            return 2

        @staticmethod
        def checkedout() -> int:
            return 1

        @staticmethod
        def overflow() -> int:
            return 0

    class FailingEngine:
        """Engine stub that fails before yielding connection details."""

        dialect = FakeDialect()
        pool = FakePool()

        @staticmethod
        def connect() -> None:
            raise SQLAlchemyError("could not connect to secret-db.internal")

    monkeypatch.setattr(database_diagnostics.database, "engine", FailingEngine())

    snapshot = database_diagnostics.collect_database_diagnostics_snapshot()

    rendered_values = [
        snapshot.status_label,
        snapshot.latency_display,
        snapshot.backend_display,
        snapshot.driver_display,
        snapshot.migration_revision,
        snapshot.pool.class_name,
        snapshot.pool.size_display,
        snapshot.pool.checked_in_display,
        snapshot.pool.checked_out_display,
        snapshot.pool.overflow_display,
    ]
    assert snapshot.available is False
    assert snapshot.severity == "critical"
    assert snapshot.status_label == "Needs attention"
    assert snapshot.latency_display == "Unavailable"
    assert snapshot.latency_ms is None
    assert snapshot.migration_revision == "Unavailable"
    assert "secret-db.internal" not in " ".join(rendered_values)


def test_debug_disk_usage_serializer_ignores_used_percentage(tmp_path: Path, monkeypatch) -> None:
    """Disk diagnostics should measure an existing parent and alert on free space only."""

    configured_path = tmp_path / "logs" / "future"
    observed_paths: list[Path] = []

    def fake_disk_usage(path: Path) -> SimpleNamespace:
        observed_paths.append(path)
        gibibyte = 1024 * 1024 * 1024
        return SimpleNamespace(
            total=100 * gibibyte,
            used=96 * gibibyte,
            free=4 * gibibyte,
        )

    monkeypatch.setattr(system_health.shutil, "disk_usage", fake_disk_usage)

    volume = system_health._serialize_disk_usage_volume("Missing child", str(configured_path))

    assert observed_paths == [tmp_path]
    assert volume.configured_path == str(configured_path)
    assert volume.measured_path == str(tmp_path)
    assert volume.total_display == "100.0 GB"
    assert volume.used_display == "96.0 GB"
    assert volume.free_display == "4.0 GB"
    assert volume.used_percent == 96.0
    assert volume.used_percent_display == "96.0%"
    assert volume.severity == "ok"
    assert volume.status_label == "OK"


def test_disk_health_marks_stale_backup_mount_unavailable_without_raising(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A stale backup mount should degrade health instead of breaking requests."""

    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    application_settings = replace(
        settings,
        automatic_backup_dir=str(backup_directory),
    )
    original_exists = Path.exists

    def stale_backup_path_exists(path: Path) -> bool:
        if path == backup_directory:
            raise OSError(116, "Stale file handle")
        return original_exists(path)

    monkeypatch.setattr(system_health, "settings", application_settings)
    monkeypatch.setattr(Path, "exists", stale_backup_path_exists)

    snapshot = system_health.collect_disk_usage_snapshot()

    assert snapshot.severity == "critical"
    assert snapshot.status_label == "Storage unavailable"
    assert len(snapshot.volumes) == 2
    backup_volume = next(volume for volume in snapshot.volumes if volume.label == "Backup directory")
    assert backup_volume.available is False
    assert backup_volume.status_label == "Unavailable"
    assert backup_volume.configured_path == str(backup_directory)


def test_review_stays_available_when_backup_storage_probe_fails(
    super_admin_client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An authenticated workflow page should survive a stale backup mount."""

    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    application_settings = replace(
        settings,
        automatic_backup_dir=str(backup_directory),
    )
    original_exists = Path.exists

    def stale_backup_path_exists(path: Path) -> bool:
        if path == backup_directory:
            raise OSError(116, "Stale file handle")
        return original_exists(path)

    monkeypatch.setattr(system_health, "settings", application_settings)
    monkeypatch.setattr(Path, "exists", stale_backup_path_exists)

    response = super_admin_client.get("/review")

    assert response.status_code == 200
    assert "Review" in response.text
    assert 'health-alert-button-critical' in response.text


def test_debug_page_explains_unavailable_storage_without_usage_meter(
    super_admin_client: TestClient,
    monkeypatch,
) -> None:
    """Diagnostics should explain an unreadable path without fake usage data."""

    unavailable_snapshot = system_health.DebugDiskUsageSnapshot(
        severity="critical",
        status_label="Storage unavailable",
        warning_free_display="1000.0 MB",
        critical_free_display="250.0 MB",
        volumes=(
            system_health.DebugDiskUsageVolume(
                label="Backup directory",
                configured_path="/data/backups",
                measured_path="/data/backups",
                total_display="Unavailable",
                used_display="Unavailable",
                free_display="Unavailable",
                used_percent=0.0,
                used_percent_display="Unavailable",
                severity="critical",
                status_label="Unavailable",
                available=False,
            ),
        ),
    )
    monkeypatch.setattr(debug_routes, "_collect_disk_usage_snapshot", lambda: unavailable_snapshot)

    response = super_admin_client.get("/debug")

    assert response.status_code == 200
    assert "Storage unavailable" in response.text
    assert "Usage is temporarily unavailable." in response.text
    assert 'class="disk-meter' not in response.text


def test_debug_disk_usage_thresholds_use_strict_free_space_boundaries() -> None:
    """Warning and critical disk states should use configurable strict MB thresholds."""

    application_settings = replace(
        settings,
        app_health_disk_warning_free_mb=1000,
        app_health_disk_critical_free_mb=250,
    )
    mebibyte = 1024 * 1024

    assert system_health._disk_usage_severity(
        1000 * mebibyte,
        application_settings=application_settings,
    ) == ("ok", "OK")
    assert system_health._disk_usage_severity(
        999 * mebibyte,
        application_settings=application_settings,
    ) == ("warning", "Nearing full")
    assert system_health._disk_usage_severity(
        250 * mebibyte,
        application_settings=application_settings,
    ) == ("warning", "Nearing full")
    assert system_health._disk_usage_severity(
        249 * mebibyte,
        application_settings=application_settings,
    ) == ("critical", "Critical")


def test_debug_disk_usage_combines_paths_on_same_storage() -> None:
    """Diagnostics should combine monitored paths with identical used and total space."""

    gibibyte = 1024 * 1024 * 1024
    first_volume = system_health.DebugDiskUsageVolume(
        label="App filesystem",
        configured_path="/",
        measured_path="/",
        total_display="100.0 GB",
        used_display="40.0 GB",
        free_display="60.0 GB",
        used_percent=40.0,
        used_percent_display="40.0%",
        severity="ok",
        status_label="OK",
        total_bytes=100 * gibibyte,
        used_bytes=40 * gibibyte,
        free_bytes=60 * gibibyte,
        configured_paths=("App filesystem: /",),
        measured_paths=("/",),
    )
    second_volume = system_health.DebugDiskUsageVolume(
        label="Backup directory",
        configured_path="/data/backups",
        measured_path="/data/backups",
        total_display="100.0 GB",
        used_display="40.0 GB",
        free_display="60.0 GB",
        used_percent=40.0,
        used_percent_display="40.0%",
        severity="ok",
        status_label="OK",
        total_bytes=100 * gibibyte,
        used_bytes=40 * gibibyte,
        free_bytes=60 * gibibyte,
        configured_paths=("Backup directory: /data/backups",),
        measured_paths=("/data/backups",),
    )
    separate_volume = system_health.DebugDiskUsageVolume(
        label="Backup directory",
        configured_path="/backups",
        measured_path="/backups",
        total_display="50.0 GB",
        used_display="10.0 GB",
        free_display="40.0 GB",
        used_percent=20.0,
        used_percent_display="20.0%",
        severity="ok",
        status_label="OK",
        total_bytes=50 * gibibyte,
        used_bytes=10 * gibibyte,
        free_bytes=40 * gibibyte,
        configured_paths=("Backup directory: /backups",),
        measured_paths=("/backups",),
    )

    combined_volumes = system_health._combine_disk_usage_volumes(
        (first_volume, second_volume, separate_volume)
    )

    assert len(combined_volumes) == 2
    assert combined_volumes[0].label == "App filesystem, Backup directory"
    assert combined_volumes[0].configured_paths == (
        "App filesystem: /",
        "Backup directory: /data/backups",
    )
    assert combined_volumes[1].label == "Backup directory"


def test_app_health_snapshot_includes_degraded_disk_state(monkeypatch) -> None:
    """The shared health snapshot should alert on warning or critical disk state."""

    disk_snapshot = system_health.DebugDiskUsageSnapshot(
        severity="warning",
        status_label="Disk space nearing full",
        volumes=(),
    )
    monkeypatch.setattr(system_health, "collect_disk_usage_snapshot", lambda: disk_snapshot)
    system_health.reset_cached_autotask_health()

    health_snapshot = system_health.collect_app_health_snapshot()

    assert health_snapshot.degraded is True
    assert len(health_snapshot.issues) == 1
    assert health_snapshot.issues[0].code == "disk-space"
    assert health_snapshot.issues[0].label == "Disk space nearing full"


def test_app_health_snapshot_includes_database_latency_pool_and_status(monkeypatch) -> None:
    """Shared health should classify database status, latency, and pool pressure."""

    healthy_disk_snapshot = system_health.DebugDiskUsageSnapshot(
        severity="ok",
        status_label="Disk space OK",
        volumes=(),
    )
    monkeypatch.setattr(system_health, "collect_disk_usage_snapshot", lambda: healthy_disk_snapshot)
    system_health.reset_cached_autotask_health()
    high_pressure_pool = database_diagnostics.DebugDatabasePoolSnapshot(
        class_name="QueuePool",
        size_display="5",
        checked_in_display="0",
        checked_out_display="9",
        overflow_display="4",
        configured_limit_display="10",
        timeout_display="30.0s",
        recycle_display="1800s",
        size=5,
        checked_in=0,
        checked_out=9,
        overflow=4,
        configured_limit=10,
    )
    slow_database_snapshot = database_diagnostics.DebugDatabaseSnapshot(
        available=True,
        status_label="Connected",
        latency_display="333.0 ms",
        backend_display="postgresql",
        driver_display="psycopg",
        migration_revision="abc123",
        pool=high_pressure_pool,
        latency_ms=333.0,
    )

    health_snapshot = system_health.collect_app_health_snapshot(database_snapshot=slow_database_snapshot)

    issue_codes = {issue.code: issue for issue in health_snapshot.issues}
    assert issue_codes["database-latency"].severity == "warning"
    assert issue_codes["database-pool-pressure"].severity == "warning"
    assert "333.0 ms" in issue_codes["database-latency"].summary
    assert "90.0%" in issue_codes["database-pool-pressure"].summary

    unavailable_database_snapshot = database_diagnostics.DebugDatabaseSnapshot(
        available=False,
        status_label="Needs attention",
        latency_display="Unavailable",
        backend_display="postgresql",
        driver_display="psycopg",
        migration_revision="Unavailable",
        pool=high_pressure_pool,
        latency_ms=None,
    )

    unavailable_health = system_health.collect_app_health_snapshot(database_snapshot=unavailable_database_snapshot)

    assert unavailable_health.severity == "critical"
    assert unavailable_health.issues[0].code == "database-status"
    assert unavailable_health.issues[0].label == "Database unavailable"


def test_app_health_snapshot_includes_active_login_lockout(super_admin_client: TestClient, monkeypatch) -> None:
    """Login-protection lockouts should appear as warning health issues."""

    healthy_disk_snapshot = system_health.DebugDiskUsageSnapshot(
        severity="ok",
        status_label="Disk space OK",
        volumes=(),
    )
    healthy_pool = database_diagnostics.DebugDatabasePoolSnapshot(
        class_name="StaticPool",
        size_display="n/a",
        checked_in_display="n/a",
        checked_out_display="n/a",
        overflow_display="n/a",
        configured_limit_display="n/a",
        timeout_display="n/a",
        recycle_display="n/a",
    )
    healthy_database_snapshot = database_diagnostics.DebugDatabaseSnapshot(
        available=True,
        status_label="Connected",
        latency_display="1.0 ms",
        backend_display="sqlite",
        driver_display="pysqlite",
        migration_revision="Not recorded",
        pool=healthy_pool,
        latency_ms=1.0,
    )
    monkeypatch.setattr(debug_routes, "_collect_disk_usage_snapshot", lambda: healthy_disk_snapshot)
    monkeypatch.setattr(debug_routes, "collect_database_diagnostics_snapshot", lambda: healthy_database_snapshot)
    monkeypatch.setattr(system_health, "collect_disk_usage_snapshot", lambda: healthy_disk_snapshot)
    system_health.reset_cached_autotask_health()

    with database.SessionLocal() as database_session:
        database_session.add(
            LoginFailureCounter(
                client_ip="198.51.100.20",
                username="locked-user",
                failed_count=settings.cloudflare_auto_block_failed_login_attempts,
                last_failed_at_utc=datetime.now(UTC),
            )
        )
        database_session.commit()

    response = super_admin_client.get("/debug")

    assert response.status_code == 200
    assert "diagnostics-health-banner-warning" in response.text
    assert "Login protection active" in response.text
    assert "active local login lockout" in response.text

    with database.SessionLocal() as database_session:
        health_snapshot = system_health.collect_app_health_snapshot(
            database_session=database_session,
            database_snapshot=healthy_database_snapshot,
        )

    issue_codes = {issue.code: issue for issue in health_snapshot.issues}
    assert issue_codes["login-protection"].severity == "warning"


def test_app_health_pushover_notifications_fire_on_degrade_change_and_restore(monkeypatch) -> None:
    """Pushover notifications should avoid repeats and announce recovery."""

    sent_notifications: list[tuple[str, str, int]] = []

    def fake_send(title: str, message: str, *, priority: int, application_settings) -> bool:
        sent_notifications.append((title, message, priority))
        return True

    monkeypatch.setattr(app_health_monitor, "send_pushover_notification", fake_send)
    notification_state = app_health_monitor.HealthNotificationState()
    warning_snapshot = system_health.AppHealthSnapshot(
        issues=(
            system_health.AppHealthIssue(
                code="disk-space",
                label="Disk space nearing full",
                severity="warning",
                summary="Disk space nearing full",
            ),
        )
    )
    critical_snapshot = system_health.AppHealthSnapshot(
        issues=(
            system_health.AppHealthIssue(
                code="database-status",
                label="Database unavailable",
                severity="critical",
                summary="Database connectivity is unavailable.",
            ),
        )
    )
    healthy_snapshot = system_health.AppHealthSnapshot(issues=())
    notification_settings = replace(
        settings,
        pushover_enabled=True,
        pushover_user_key="user-key",
        pushover_app_key="app-key",
    )

    assert app_health_monitor.notify_if_health_changed(
        warning_snapshot,
        notification_state,
        application_settings=notification_settings,
    ) == "degraded"
    assert app_health_monitor.notify_if_health_changed(
        warning_snapshot,
        notification_state,
        application_settings=notification_settings,
    ) is None
    assert app_health_monitor.notify_if_health_changed(
        critical_snapshot,
        notification_state,
        application_settings=notification_settings,
    ) == "changed"
    assert app_health_monitor.notify_if_health_changed(
        healthy_snapshot,
        notification_state,
        application_settings=notification_settings,
    ) == "restored"

    assert [title for title, _message, _priority in sent_notifications] == [
        "Job Logger health degraded",
        "Job Logger health changed",
        "Job Logger health restored",
    ]
    assert sent_notifications[0][2] == 0
    assert sent_notifications[1][2] == 1
    assert "Database unavailable" in sent_notifications[1][1]
    assert "passing again" in sent_notifications[2][1]


def test_pushover_notifications_do_not_send_in_dev_build(monkeypatch) -> None:
    """DEV_BUILD should suppress Pushover even when credentials are configured."""

    def fail_post(*_args, **_kwargs):
        raise AssertionError("DEV_BUILD should not send Pushover notifications.")

    monkeypatch.setattr(pushover.httpx, "post", fail_post)
    notification_settings = replace(
        settings,
        dev_build=True,
        pushover_enabled=True,
        pushover_user_key="user-key",
        pushover_app_key="app-key",
    )

    assert pushover.send_pushover_notification(
        "Job Logger health degraded",
        "Database unavailable",
        application_settings=notification_settings,
    ) is False


def test_cached_health_alert_is_visible_to_all_authenticated_users(client: TestClient, monkeypatch) -> None:
    """Cached degraded health should link every signed-in user to Help status."""

    healthy_disk_snapshot = system_health.DebugDiskUsageSnapshot(
        severity="ok",
        status_label="Disk space OK",
        volumes=(),
    )
    monkeypatch.setattr(system_health, "collect_disk_usage_snapshot", lambda: healthy_disk_snapshot)
    system_health.record_autotask_api_failure(
        "Autotask API access failed.",
        operation="Autotask company lookup",
    )

    login_as_web_user(client)
    non_admin_response = client.get("/home")
    assert non_admin_response.status_code == 200
    assert "has-health-alert" in non_admin_response.text
    assert 'data-health-alert-button' in non_admin_response.text
    assert 'data-desktop-health-alert-indicator' in non_admin_response.text
    assert 'data-mobile-health-alert-indicator' in non_admin_response.text
    assert 'data-desktop-health-alert-link' in non_admin_response.text
    assert 'data-mobile-health-alert-link' in non_admin_response.text
    assert 'href="/help#operational-status"' in non_admin_response.text
    assert "health-alert-button-critical" in non_admin_response.text
    assert 'href="/debug"' not in non_admin_response.text
    assert 'role="img"' not in non_admin_response.text
    assert 'aria-label="View operational status: application health is critical."' in non_admin_response.text
    assert "Autotask API needs attention" not in non_admin_response.text

    login_as_super_admin(client)
    admin_response = client.get("/users")
    assert admin_response.status_code == 200
    assert "has-health-alert" in admin_response.text
    assert 'data-health-alert-button' in admin_response.text
    assert 'data-desktop-health-alert-indicator' in admin_response.text
    assert 'data-mobile-health-alert-indicator' in admin_response.text
    assert 'data-desktop-health-alert-link' in admin_response.text
    assert 'data-mobile-health-alert-link' in admin_response.text
    assert 'href="/help#operational-status"' in admin_response.text
    assert "health-alert-button-critical" in admin_response.text
    assert 'href="/debug"' in admin_response.text
    assert "View operational status: application health is critical." in admin_response.text

    system_health.record_autotask_api_failure(
        "Autotask ticket lookup failed.",
        operation="Autotask ticket lookup",
    )
    system_health.record_autotask_api_success(operation="Autotask company lookup")
    still_degraded_response = client.get("/users")
    assert still_degraded_response.status_code == 200
    assert "data-health-alert-button" in still_degraded_response.text

    system_health.record_autotask_api_success(operation="Autotask ticket lookup")
    cleared_response = client.get("/users")
    assert cleared_response.status_code == 200
    assert "data-health-alert-button" not in cleared_response.text


def test_warning_health_alert_uses_warning_link_style(authenticated_client: TestClient, monkeypatch) -> None:
    """Warning-only app health should use the yellow status link treatment."""

    warning_disk_snapshot = system_health.DebugDiskUsageSnapshot(
        severity="warning",
        status_label="Disk space warning",
        volumes=(),
    )
    monkeypatch.setattr(system_health, "collect_disk_usage_snapshot", lambda: warning_disk_snapshot)

    response = authenticated_client.get("/home")

    assert response.status_code == 200
    assert "has-health-alert" in response.text
    assert 'href="/help#operational-status"' in response.text
    assert "health-alert-button-warning" in response.text
    assert "health-alert-button-critical" not in response.text
    assert 'aria-label="View operational status: application health is warning."' in response.text
    assert "Disk space warning" not in response.text


def test_managed_admin_sees_same_cached_health_alert_link(client: TestClient) -> None:
    """Managed users marked Admin should see the same app-health Help link."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.is_admin = True
        database_session.commit()

    system_health.record_autotask_api_failure(
        "Autotask API access failed.",
        operation="Autotask ticket lookup",
    )

    login_as_web_user(client)
    response = client.get("/home")

    assert response.status_code == 200
    assert "has-health-alert" in response.text
    assert 'data-health-alert-button' in response.text
    assert 'data-desktop-health-alert-indicator' in response.text
    assert 'data-mobile-health-alert-indicator' in response.text
    assert 'data-desktop-health-alert-link' in response.text
    assert 'data-mobile-health-alert-link' in response.text
    assert 'href="/help#operational-status"' in response.text
    assert 'href="/debug"' in response.text


def test_openapi_schema_route_is_disabled(client: TestClient) -> None:
    """The app should not expose generated API schema metadata."""

    response = client.get("/openapi.json")

    assert response.status_code == 404


def test_failed_login_writes_sanitized_database_row_and_debug_window(client: TestClient) -> None:
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

    with database.SessionLocal() as database_session:
        failed_attempt = database_session.scalar(select(LoginAttempt).where(LoginAttempt.succeeded.is_(False)))
        assert failed_attempt is not None
        assert failed_attempt.username == "bad-user"
        assert failed_attempt.client_ip == "203.0.113.9"
        assert failed_attempt.enforcement_client_ip == "198.51.100.7"
        assert failed_attempt.x_real_ip == "198.51.100.7"
        assert failed_attempt.x_forwarded_for == "203.0.113.9, 10.0.0.2"
        assert failed_attempt.forwarded_proto == "https"
        assert failed_attempt.host == "testserver"
        assert failed_attempt.method == "POST"
        assert failed_attempt.path == "/login"
        assert failed_attempt.reason == "invalid_credentials"
        assert failed_attempt.username_length == len("bad-user")
        assert failed_attempt.username_truncated is False
        assert failed_attempt.password_supplied is True
        assert failed_attempt.password_length == len(failed_password)
        assert failed_attempt.user_agent == "Failed Login Test"
        assert failed_attempt.failed_count == 1
        assert failed_attempt.max_attempts == 5
        assert failed_attempt.lockout_applied is False
        assert failed_password not in " ".join(str(value) for value in vars(failed_attempt).values())

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
    with database.SessionLocal() as database_session:
        success_attempt = database_session.scalar(select(LoginAttempt).where(LoginAttempt.succeeded.is_(True)))
        assert success_attempt is not None
        assert success_attempt.event == "web_login_succeeded"
        assert success_attempt.username == "admin"
        assert success_attempt.user_kind == "super_admin"
        assert success_attempt.authentication_method == "password"
        assert "test-password" not in " ".join(str(value) for value in vars(success_attempt).values())

    debug_response = client.get("/debug")
    assert debug_response.status_code == 200
    assert "Successful logins" in debug_response.text
    assert "Login failures" in debug_response.text
    assert "admin" in debug_response.text
    assert 'class="status-chip login-account-chip login-account-super-admin">Super admin</span>' in debug_response.text
    assert 'class="status-chip login-method-chip login-method-password">Password</span>' in debug_response.text
    assert "bad-user" in debug_response.text
    assert "198.51.100.7" in debug_response.text
    assert "203.0.113.9, 10.0.0.2" in debug_response.text
    assert "Enforcement IP" in debug_response.text
    assert re.search(r'<td class="login-client-ip-cell">\s*203\.0\.113\.9', debug_response.text)
    assert "login-details-button" in debug_response.text
    assert "Extra info" in debug_response.text
    assert "Failed Login Test" in debug_response.text
    assert "Invalid Credentials" in debug_response.text
    assert ">12<" in debug_response.text
    assert "1 / 5" in debug_response.text
    assert 'aria-label="Hide failed-login row"' in debug_response.text
    assert 'aria-label="Block IP at Cloudflare"' in debug_response.text
    assert "Cloudflare Blocked IPs" in debug_response.text
    assert "Newest database records first" in debug_response.text
    assert "Download JSONL" in debug_response.text
    assert "LOGIN_FAILURE_LOG_PATH" not in debug_response.text
    assert "LOGIN_SUCCESS_LOG_PATH" not in debug_response.text
    assert failed_password not in debug_response.text

    download_response = client.get("/debug/logs/login-failures")
    assert download_response.status_code == 200
    assert "web_login_failed" in download_response.text
    assert "job-logger-login-failures.jsonl" in download_response.headers["content-disposition"]
    assert download_response.headers["cache-control"] == "no-store"
    assert failed_password not in download_response.text
    log_payload = json.loads(download_response.text.strip())
    assert log_payload["username"] == "bad-user"
    assert log_payload["created_at_utc"]

    success_download_response = client.get("/debug/logs/login-successes")
    assert success_download_response.status_code == 200
    assert "web_login_succeeded" in success_download_response.text
    assert "job-logger-login-successes.jsonl" in success_download_response.headers["content-disposition"]
    assert success_download_response.headers["cache-control"] == "no-store"

    entry_id_match = re.search(r'name="entry_id" value="([a-f0-9-]{36})"', debug_response.text)
    assert entry_id_match is not None
    hide_response = client.post(
        "/debug/login-failures/hide",
        data={
            "csrf_token": extract_csrf_token(debug_response.text),
            "entry_id": entry_id_match.group(1),
            "client_ip": "203.0.113.9",
            "created_at_utc": log_payload["created_at_utc"],
        },
        follow_redirects=False,
    )
    assert hide_response.status_code == 303
    assert hide_response.headers["location"] == "/debug#login-failures"

    hidden_debug_response = client.get("/debug")
    assert "bad-user" not in hidden_debug_response.text
    hidden_download_payload = json.loads(client.get("/debug/logs/login-failures").text.strip())
    assert hidden_download_payload["username"] == "bad-user"
    assert hidden_download_payload["hidden_from_debug"] is True
    assert hidden_download_payload["created_at_utc"] == log_payload["created_at_utc"]
    with database.SessionLocal() as database_session:
        hidden_attempt = database_session.scalar(select(LoginAttempt).where(LoginAttempt.id == entry_id_match.group(1)))
        assert hidden_attempt is not None
        assert hidden_attempt.hidden_at_utc is not None
        assert hidden_attempt.client_ip == "203.0.113.9"


def test_cloudflare_ip_block_allowlist_matches_ips_and_cidrs() -> None:
    """Trusted IPs and CIDRs should be protected from app-managed blocks."""

    cloudflare_settings = replace(
        settings,
        cloudflare_ip_block_allowlist="198.51.100.20, 203.0.113.0/24",
    )

    assert ip_is_allowlisted("198.51.100.20", cloudflare_settings)
    assert ip_is_allowlisted("203.0.113.44", cloudflare_settings)
    assert not ip_is_allowlisted("198.51.100.21", cloudflare_settings)


def test_create_cloudflare_ip_block_sends_zone_access_rule_payload(monkeypatch) -> None:
    """Cloudflare blocks should be zone-level IP Access Rules with block mode."""

    cloudflare_settings = replace(
        settings,
        cloudflare_ip_blocking_enabled=True,
        cloudflare_api_token="test-token",
        cloudflare_zone_id="test-zone",
    )
    captured_request = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"success": True, "result": {"id": "rule-123"}}

    def fake_post(url, *, headers, json, timeout):
        captured_request["url"] = url
        captured_request["headers"] = headers
        captured_request["json"] = json
        captured_request["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("job_logger.services.cloudflare_blocks.httpx.post", fake_post)

    result = create_cloudflare_ip_block(
        "203.0.113.44",
        note="Job Logger manual block",
        application_settings=cloudflare_settings,
    )

    assert result.rule_id == "rule-123"
    assert captured_request["url"].endswith("/zones/test-zone/firewall/access_rules/rules")
    assert captured_request["headers"]["Authorization"] == "Bearer test-token"
    assert captured_request["json"] == {
        "mode": "block",
        "configuration": {"target": "ip", "value": "203.0.113.44"},
        "notes": "Job Logger manual block",
    }


def test_failed_login_auto_blocks_cloudflare_ip_after_five_consecutive_failures(
    client: TestClient,
    monkeypatch,
) -> None:
    """Five consecutive local login failures from one IP should create an app-managed block."""

    created_blocks: list[tuple[str, str, str, int | None]] = []

    def fake_create_app_cloudflare_block(
        database_session: Session,
        ip_address: str,
        *,
        source: str,
        reason: str,
        failure_count: int | None = None,
        application_settings=settings,
    ) -> CloudflareIPBlock:
        created_blocks.append((ip_address, source, reason, failure_count))
        block = CloudflareIPBlock(
            ip_address=ip_address,
            cloudflare_rule_id="cf-auto-rule",
            source=source,
            reason=reason,
            failure_count=failure_count,
            notes="Job Logger automatic block",
        )
        database_session.add(block)
        database_session.flush()
        return block

    monkeypatch.setattr(
        "job_logger.services.login_protection.cloudflare_ip_blocking_configured",
        lambda application_settings=settings: True,
    )
    monkeypatch.setattr(
        "job_logger.services.login_protection.create_app_cloudflare_block",
        fake_create_app_cloudflare_block,
    )

    for _ in range(5):
        login_page_response = client.get("/login")
        csrf_token = extract_csrf_token(login_page_response.text)
        failed_response = client.post(
            "/login",
            headers={"X-Forwarded-For": "198.51.100.55", "User-Agent": "Auto Block Test"},
            data={"csrf_token": csrf_token, "username": "bad-user", "password": "bad-password"},
            follow_redirects=False,
        )
        assert failed_response.status_code == 303

    assert created_blocks == [
        ("198.51.100.55", "automatic", "5 consecutive failed local app login attempts", 5)
    ]
    with database.SessionLocal() as database_session:
        counter = database_session.scalar(
            select(LoginFailureCounter).where(
                LoginFailureCounter.client_ip == "198.51.100.55",
                LoginFailureCounter.username == "bad-user",
            )
        )
        assert counter is not None
        assert counter.failed_count == 5
        block = database_session.scalar(select(CloudflareIPBlock))
        assert block is not None
        assert block.ip_address == "198.51.100.55"
        assert block.cloudflare_rule_id == "cf-auto-rule"
        assert block.source == "automatic"
        assert block.reason == "5 consecutive failed local app login attempts"
        audit_event = database_session.scalar(select(AuditEvent).where(AuditEvent.action == "debug.cloudflare_ip_block.created"))
        assert audit_event is not None
        assert audit_event.details["reason"] == "5 consecutive failed local app login attempts"
        assert audit_event.details["failure_count"] == 5

    with database.SessionLocal() as database_session:
        latest_failure = database_session.scalar(
            select(LoginAttempt)
            .where(LoginAttempt.succeeded.is_(False))
            .order_by(desc(LoginAttempt.created_at_utc))
            .limit(1)
        )
        assert latest_failure is not None
        assert latest_failure.failed_count == 5
        assert latest_failure.max_attempts == 5


def test_cloudflare_auto_block_uses_enforcement_ip_not_display_xff(
    client: TestClient,
    monkeypatch,
) -> None:
    """Spoofed XFF display data should not control the Cloudflare block target."""

    created_blocks: list[str] = []

    def fake_create_app_cloudflare_block(
        database_session: Session,
        ip_address: str,
        *,
        source: str,
        reason: str,
        failure_count: int | None = None,
        application_settings=settings,
    ) -> CloudflareIPBlock:
        created_blocks.append(ip_address)
        block = CloudflareIPBlock(
            ip_address=ip_address,
            cloudflare_rule_id="cf-enforcement-rule",
            source=source,
            reason=reason,
            failure_count=failure_count,
            notes="Job Logger automatic block",
        )
        database_session.add(block)
        database_session.flush()
        return block

    monkeypatch.setattr(
        "job_logger.services.login_protection.cloudflare_ip_blocking_configured",
        lambda application_settings=settings: True,
    )
    monkeypatch.setattr(
        "job_logger.services.login_protection.create_app_cloudflare_block",
        fake_create_app_cloudflare_block,
    )

    for _ in range(5):
        login_page_response = client.get("/login")
        csrf_token = extract_csrf_token(login_page_response.text)
        failed_response = client.post(
            "/login",
            headers={
                "X-Real-IP": "198.51.100.70",
                "X-Forwarded-For": "203.0.113.250",
            },
            data={"csrf_token": csrf_token, "username": "admin", "password": "bad-password"},
            follow_redirects=False,
        )
        assert failed_response.status_code == 303

    assert created_blocks == ["198.51.100.70"]
    with database.SessionLocal() as database_session:
        latest_failure = database_session.scalar(
            select(LoginAttempt)
            .where(LoginAttempt.succeeded.is_(False))
            .order_by(desc(LoginAttempt.created_at_utc))
            .limit(1)
        )
        assert latest_failure is not None
        assert latest_failure.client_ip == "203.0.113.250"
        assert latest_failure.enforcement_client_ip == "198.51.100.70"

    login_as_super_admin(client)
    debug_response = client.get("/debug")
    assert debug_response.status_code == 200
    assert 'name="ip_address" value="198.51.100.70"' in debug_response.text
    assert 'name="ip_address" value="203.0.113.250"' not in debug_response.text


def test_local_login_lockout_blocks_before_password_verification(client: TestClient) -> None:
    """The app should locally block more attempts after the failed-login threshold."""

    for _ in range(5):
        login_page_response = client.get("/login")
        csrf_token = extract_csrf_token(login_page_response.text)
        failed_response = client.post(
            "/login",
            headers={"X-Real-IP": "198.51.100.80"},
            data={"csrf_token": csrf_token, "username": "admin", "password": "bad-password"},
            follow_redirects=False,
        )
        assert failed_response.status_code == 303

    login_page_response = client.get("/login")
    csrf_token = extract_csrf_token(login_page_response.text)
    locked_response = client.post(
        "/login",
        headers={"X-Real-IP": "198.51.100.80"},
        data={"csrf_token": csrf_token, "username": "admin", "password": "test-password"},
        follow_redirects=True,
    )
    assert locked_response.status_code == 200
    assert "Too many failed sign-in attempts" in locked_response.text
    assert client.get("/users", follow_redirects=False).headers["location"] == "/login"

    with database.SessionLocal() as database_session:
        latest_failure = database_session.scalar(
            select(LoginAttempt)
            .where(LoginAttempt.succeeded.is_(False))
            .order_by(desc(LoginAttempt.created_at_utc))
            .limit(1)
        )
        assert latest_failure is not None
        assert latest_failure.reason == "local_lockout"
        assert latest_failure.lockout_applied is True
        assert latest_failure.failed_count == 5
        assert latest_failure.password_length == len("test-password")
        assert "test-password" not in " ".join(str(value) for value in vars(latest_failure).values())

    with database.SessionLocal() as database_session:
        counter = database_session.scalar(
            select(LoginFailureCounter).where(
                LoginFailureCounter.client_ip == "198.51.100.80",
                LoginFailureCounter.username == "admin",
            )
        )
        assert counter is not None
        assert counter.failed_count == 5
        counter.last_failed_at_utc = datetime.now(UTC) - timedelta(minutes=16)
        database_session.commit()

    login_page_response = client.get("/login")
    csrf_token = extract_csrf_token(login_page_response.text)
    unlocked_response = client.post(
        "/login",
        headers={"X-Real-IP": "198.51.100.80"},
        data={"csrf_token": csrf_token, "username": "admin", "password": "test-password"},
        follow_redirects=False,
    )
    assert unlocked_response.status_code == 303
    assert unlocked_response.headers["location"] == "/users"


def test_successful_login_resets_consecutive_failures_before_auto_block(
    client: TestClient,
    monkeypatch,
) -> None:
    """A successful login before the threshold should reset that IP's failed count."""

    def fail_create_app_cloudflare_block(*args, **kwargs):
        raise AssertionError("Cloudflare block should not be created after a reset.")

    monkeypatch.setattr(
        "job_logger.services.login_protection.cloudflare_ip_blocking_configured",
        lambda application_settings=settings: True,
    )
    monkeypatch.setattr(
        "job_logger.services.login_protection.create_app_cloudflare_block",
        fail_create_app_cloudflare_block,
    )

    for _ in range(4):
        login_page_response = client.get("/login")
        csrf_token = extract_csrf_token(login_page_response.text)
        failed_response = client.post(
            "/login",
            headers={"X-Forwarded-For": "198.51.100.60"},
            data={"csrf_token": csrf_token, "username": "admin", "password": "bad-password"},
            follow_redirects=False,
        )
        assert failed_response.status_code == 303

    login_page_response = client.get("/login")
    csrf_token = extract_csrf_token(login_page_response.text)
    success_response = client.post(
        "/login",
        headers={"X-Forwarded-For": "198.51.100.60"},
        data={"csrf_token": csrf_token, "username": "admin", "password": "test-password"},
        follow_redirects=False,
    )
    assert success_response.status_code == 303

    with database.SessionLocal() as database_session:
        counter = database_session.scalar(
            select(LoginFailureCounter).where(
                LoginFailureCounter.client_ip == "198.51.100.60",
                LoginFailureCounter.username == "admin",
            )
        )
        assert counter is not None
        assert counter.failed_count == 0

    client.cookies.clear()
    login_page_response = client.get("/login")
    csrf_token = extract_csrf_token(login_page_response.text)
    failed_response = client.post(
        "/login",
        headers={"X-Forwarded-For": "198.51.100.60"},
        data={"csrf_token": csrf_token, "username": "bad-user", "password": "bad-password"},
        follow_redirects=False,
    )
    assert failed_response.status_code == 303

    with database.SessionLocal() as database_session:
        counter = database_session.scalar(
            select(LoginFailureCounter).where(
                LoginFailureCounter.client_ip == "198.51.100.60",
                LoginFailureCounter.username == "bad-user",
            )
        )
        assert counter is not None
        assert counter.failed_count == 1
        assert database_session.scalar(select(CloudflareIPBlock)) is None


def test_debug_cloudflare_block_buttons_create_and_remove_app_managed_block(
    client: TestClient,
    monkeypatch,
) -> None:
    """The failed-login row block toggle should create and remove app-managed blocks."""

    login_page_response = client.get("/login")
    csrf_token = extract_csrf_token(login_page_response.text)
    failed_response = client.post(
        "/login",
        headers={"X-Forwarded-For": "203.0.113.20", "User-Agent": "Manual Block Test"},
        data={"csrf_token": csrf_token, "username": "bad-user", "password": "bad-password"},
        follow_redirects=False,
    )
    assert failed_response.status_code == 303

    login_page_response = client.get("/login")
    csrf_token = extract_csrf_token(login_page_response.text)
    success_response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "admin", "password": "test-password"},
        follow_redirects=False,
    )
    assert success_response.status_code == 303

    deleted_rule_ids: list[str] = []
    created_blocks: list[tuple[str, str]] = []

    def fake_cloudflare_ip_blocking_configured() -> bool:
        return True

    def fake_create_app_cloudflare_block(
        database_session: Session,
        ip_address: str,
        *,
        source: str,
        reason: str,
        failure_count: int | None = None,
        application_settings=settings,
    ) -> CloudflareIPBlock:
        created_blocks.append((ip_address, reason))
        block = CloudflareIPBlock(
            ip_address=ip_address,
            cloudflare_rule_id=f"cf-manual-rule-{len(created_blocks)}",
            source=source,
            reason=reason,
            failure_count=failure_count,
            notes="Job Logger manual block",
        )
        database_session.add(block)
        database_session.flush()
        return block

    def fake_remove_app_cloudflare_block(database_session: Session, block: CloudflareIPBlock) -> None:
        deleted_rule_ids.append(block.cloudflare_rule_id)
        database_session.delete(block)

    monkeypatch.setattr(debug_routes, "cloudflare_ip_blocking_configured", fake_cloudflare_ip_blocking_configured)
    monkeypatch.setattr(debug_routes, "create_app_cloudflare_block", fake_create_app_cloudflare_block)
    monkeypatch.setattr(debug_routes, "remove_app_cloudflare_block", fake_remove_app_cloudflare_block)

    initial_response = client.get("/debug")
    assert initial_response.status_code == 200
    assert 'aria-label="Block IP at Cloudflare"' in initial_response.text
    assert 'class="cloudflare-manual-block-form"' in initial_response.text
    assert 'name="reason"' in initial_response.text
    block_response = client.post(
        "/debug/cloudflare-blocks/block",
        data={
            "csrf_token": extract_csrf_token(initial_response.text),
            "ip_address": "203.0.113.20",
            "reason": "Diagnostics failed-login row block: invalid credentials for bad-user",
            "redirect_fragment": "login-failures",
        },
        follow_redirects=False,
    )
    assert block_response.status_code == 303
    assert block_response.headers["location"] == "/debug#login-failures"
    assert created_blocks == [
        ("203.0.113.20", "Diagnostics failed-login row block: invalid credentials for bad-user")
    ]
    with database.SessionLocal() as database_session:
        block = database_session.scalar(select(CloudflareIPBlock))
        assert block is not None
        assert block.ip_address == "203.0.113.20"
        assert block.cloudflare_rule_id == "cf-manual-rule-1"
        assert block.source == "manual"
        assert block.reason == "Diagnostics failed-login row block: invalid credentials for bad-user"
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "debug.cloudflare_ip_block.created")
        )
        assert audit_event is not None
        assert audit_event.details["reason"] == "Diagnostics failed-login row block: invalid credentials for bad-user"

    blocked_response = client.get("/debug")
    assert "Cloudflare Blocked IPs" in blocked_response.text
    assert "cf-manual-rule-1" in blocked_response.text
    assert "Diagnostics failed-login row block: invalid credentials for bad-user" in blocked_response.text
    assert 'aria-label="Unblock IP at Cloudflare"' in blocked_response.text

    unblock_response = client.post(
        "/debug/cloudflare-blocks/unblock",
        data={"csrf_token": extract_csrf_token(blocked_response.text), "ip_address": "203.0.113.20"},
        follow_redirects=False,
    )
    assert unblock_response.status_code == 303
    assert unblock_response.headers["location"] == "/debug#cloudflare-blocked-ips"
    assert deleted_rule_ids == ["cf-manual-rule-1"]
    with database.SessionLocal() as database_session:
        assert database_session.scalar(select(CloudflareIPBlock)) is None

    manual_debug_response = client.get("/debug")
    manual_block_response = client.post(
        "/debug/cloudflare-blocks/block",
        data={
            "csrf_token": extract_csrf_token(manual_debug_response.text),
            "ip_address": "203.0.113.21",
            "reason": "Operator reported credential stuffing",
            "redirect_fragment": "cloudflare-blocked-ips",
        },
        follow_redirects=False,
    )
    assert manual_block_response.status_code == 303
    assert manual_block_response.headers["location"] == "/debug#cloudflare-blocked-ips"
    assert created_blocks[-1] == ("203.0.113.21", "Operator reported credential stuffing")
    with database.SessionLocal() as database_session:
        block = database_session.scalar(select(CloudflareIPBlock))
        assert block is not None
        assert block.ip_address == "203.0.113.21"
        assert block.reason == "Operator reported credential stuffing"


def test_debug_login_pagination(super_admin_client: TestClient) -> None:
    """Diagnostics should page database-backed login tables."""

    created_at = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)

    with database.SessionLocal() as database_session:
        for index in range(12):
            database_session.add(
                LoginAttempt(
                    succeeded=False,
                    event="web_login_failed",
                    created_at_utc=created_at + timedelta(seconds=index),
                    client_ip=f"198.51.100.{index}",
                    enforcement_client_ip=f"198.51.100.{index}",
                    direct_client_ip="testclient",
                    forwarded_proto="https",
                    host="testserver",
                    username=f"failure-{index}",
                    username_length=len(f"failure-{index}"),
                    username_truncated=False,
                    password_supplied=True,
                    password_length=8,
                    user_agent="Pagination Test",
                    method="POST",
                    path="/login",
                    reason="invalid_credentials",
                )
            )
            database_session.add(
                LoginAttempt(
                    succeeded=True,
                    event="web_login_succeeded",
                    created_at_utc=created_at + timedelta(seconds=index),
                    client_ip=f"203.0.113.{index}",
                    enforcement_client_ip=f"203.0.113.{index}",
                    direct_client_ip="testclient",
                    forwarded_proto="https",
                    host="testserver",
                    username=f"success-{index}",
                    user_kind="web_user",
                    web_user_id=f"user-{index}",
                    authentication_method="passkey" if index % 2 else "password",
                    user_agent="Pagination Test",
                    method="POST",
                    path="/login",
                )
            )
        database_session.commit()

    debug_response = super_admin_client.get("/debug?success_page=2&failure_page=2")
    assert debug_response.status_code == 200
    assert "12 retained, 7 per page" in debug_response.text
    assert "Page 2 of 2" in debug_response.text
    assert 'class="status-chip login-method-chip login-method-password">Password</span>' in debug_response.text
    assert 'class="status-chip login-method-chip login-method-passkey">Passkey</span>' in debug_response.text
    assert "failure-4" in debug_response.text
    assert "failure-1" in debug_response.text
    assert "failure-0" in debug_response.text
    assert "success-5" in debug_response.text
    assert "success-4" in debug_response.text
    assert "success-1" in debug_response.text
    assert "success-0" in debug_response.text
    assert "failure-5" not in debug_response.text
    assert "failure-11" not in debug_response.text
    assert "success-6" not in debug_response.text
    assert "success-11" not in debug_response.text
    assert "Application Log" not in debug_response.text

    stylesheet = (Path(__file__).resolve().parents[1] / "job_logger" / "static" / "app.css").read_text(encoding="utf-8")
    phone_stylesheet = (
        Path(__file__).resolve().parents[1] / "job_logger" / "static" / "phone.css"
    ).read_text(encoding="utf-8")
    desktop_stylesheet = (
        Path(__file__).resolve().parents[1] / "job_logger" / "static" / "desktop.css"
    ).read_text(encoding="utf-8")
    assert ".login-attempt-window" in stylesheet
    assert "max-height: 430px;" not in stylesheet
    assert ".diagnostics-seven-row-window {\n  min-height: 360px;\n  max-height: none;" in stylesheet
    assert ".debug-scroll-table-wrap" in stylesheet
    assert ".debug-submission-table {\n  width: 100%;\n  min-width: 920px;" in stylesheet
    assert ".automatic-backup-table {\n  width: 100%;\n  min-width: 920px;" in stylesheet
    assert ".automatic-backup-header" in stylesheet
    assert ".debug-scroll-table-wrap" in phone_stylesheet
    assert "overscroll-behavior-x: contain;" in phone_stylesheet
    assert ".automatic-backup-header {\n  gap: 6px;" in phone_stylesheet
    assert ".login-account-super-admin" in stylesheet
    assert "background: var(--warning-soft);" in stylesheet
    assert ".login-details-button" in stylesheet
    assert ".login-attempt-extra" in stylesheet
    assert "position: absolute;" in stylesheet
    assert "width: min(760px, calc(100vw - 96px));" in stylesheet
    assert "max-height: min(420px, calc(100vh - 160px));" in stylesheet
    assert ".disk-space-card.disk-space-warning" in stylesheet
    assert ".disk-space-card.disk-space-critical" in stylesheet
    assert ".disk-meter-critical" in stylesheet
    assert ".database-health-grid" in stylesheet
    assert ".database-health-card.database-health-critical" in stylesheet
    assert ".session-controls-card .debug-panel-body {\n  height: 100%;\n}" in stylesheet
    assert ".session-controls-layout {\n  display: flex;\n  min-height: 100%;" in stylesheet
    assert ".session-controls-form {\n  display: flex;\n  width: 100%;" in stylesheet
    assert ".session-controls-form .danger-button {\n  width: min(100%, 260px);\n  min-height: 44px;" in stylesheet
    assert ".debug-shell {\n  display: grid;\n  gap: 12px;" in stylesheet
    assert ".debug-shell > .review-header {\n  margin-bottom: 0;" in stylesheet
    assert (
        ".debug-shell {\n"
        "    grid-template-columns: repeat(2, minmax(0, 1fr));\n"
        "    align-items: stretch;\n"
        "  }"
    ) in desktop_stylesheet
    assert ".debug-shell > #disk-space {\n    grid-column: 1;\n    grid-row: 2;\n  }" in desktop_stylesheet
    assert (
        ".debug-shell > #session-controls {\n"
        "    grid-column: 2;\n"
        "    grid-row: 2;\n"
        "    align-self: stretch;\n"
        "    height: 100%;\n"
        "  }"
    ) in desktop_stylesheet
    assert ".debug-shell > #database-health {\n    grid-row: 3;\n  }" in desktop_stylesheet


def test_debug_paginates_cloudflare_blocked_ips(super_admin_client: TestClient) -> None:
    """Diagnostics should limit Cloudflare blocked IP rows to 10 per page."""

    created_at = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        for index in range(12):
            database_session.add(
                CloudflareIPBlock(
                    ip_address=f"198.51.100.{index}",
                    cloudflare_rule_id=f"cf-page-rule-{index:03d}",
                    source="automatic",
                    reason=f"pagination test block {index}",
                    failure_count=index,
                    notes="Job Logger pagination test block",
                    created_at_utc=created_at + timedelta(minutes=index),
                    updated_at_utc=created_at + timedelta(minutes=index),
                )
            )
        database_session.commit()

    debug_response = super_admin_client.get("/debug?cloudflare_blocks_page=2")

    assert debug_response.status_code == 200
    assert "Cloudflare Blocked IPs" in debug_response.text
    assert "12 retained, 10 per page" in debug_response.text
    assert "Page 2 of 2" in debug_response.text
    cloudflare_section = re.search(
        r'id="cloudflare-blocked-ips".*?id="autotask-submission-attempts"',
        debug_response.text,
        flags=re.DOTALL,
    )
    assert cloudflare_section is not None
    cloudflare_html = cloudflare_section.group(0)
    assert cloudflare_html.count('class="login-cloudflare-rule-cell"') == 2
    assert "cf-page-rule-001" in cloudflare_html
    assert "cf-page-rule-000" in cloudflare_html
    assert "cf-page-rule-011" not in cloudflare_html
    assert "cf-page-rule-010" not in cloudflare_html


def test_debug_paginates_autotask_submission_attempts(super_admin_client: TestClient) -> None:
    """Diagnostics should limit Autotask submission attempts to 7 rows per page."""

    job_id = _add_temporary_job()
    created_at = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        for index in range(12):
            database_session.add(
                SubmissionAttempt(
                    job_id=job_id,
                    provider="mock",
                    idempotency_key=f"submission-page-test-{index}",
                    succeeded=True,
                    external_id=f"mock-entry-{index}",
                    request_snapshot={"index": index},
                    created_at_utc=created_at + timedelta(minutes=index),
                )
            )
        database_session.commit()

    debug_response = super_admin_client.get("/debug?attempt_page=2")

    assert debug_response.status_code == 200
    assert "Autotask submission attempts" in debug_response.text
    assert "12 retained, 7 per page" in debug_response.text
    assert "Page 2 of 2" in debug_response.text
    assert "mock-entry-4" in debug_response.text
    assert "mock-entry-1" in debug_response.text
    assert "mock-entry-0" in debug_response.text
    assert "mock-entry-5" not in debug_response.text
    assert "mock-entry-11" not in debug_response.text
    assert "mock-entry-10" not in debug_response.text
    assert "Show request snapshots for this page" in debug_response.text
    assert "&#34;index&#34;: 4" in debug_response.text
    assert "&#34;index&#34;: 1" in debug_response.text
    assert "&#34;index&#34;: 5" not in debug_response.text
    assert "&#34;index&#34;: 11" not in debug_response.text


def test_debug_route_shows_autotask_attempts(authenticated_client: TestClient) -> None:
    """Authenticated users should see submission attempts and connection diagnostics."""

    start_page_response = authenticated_client.get("/home")
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

    description_response = authenticated_client.post(
        f"/jobs/{active_job_id}/description/text",
        headers={"X-CSRF-Token": csrf_token},
        json={"summary_notes": "Checked connection diagnostics for one test submission."},
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
    assert "Diagnostics - Job Logger" in debug_response.text
    assert "<h1>Diagnostics</h1>" in debug_response.text
    assert (
        "Monitor storage, database connectivity, login activity, Cloudflare blocks, "
        "Autotask connectivity, submission history, and backups."
        in debug_response.text
    )
    assert "Autotask debug" not in debug_response.text
    assert "Review provider configuration and the most recent submission attempts." not in debug_response.text
    assert "Application version" in debug_response.text
    assert APP_VERSION in debug_response.text
    assert debug_response.text.index("Disk space") < debug_response.text.index("Database")
    assert debug_response.text.index("Database") < debug_response.text.index("Session controls")
    assert debug_response.text.index("Session controls") < debug_response.text.index("Successful logins")
    assert debug_response.text.index("Successful logins") < debug_response.text.index("Login failures")
    assert debug_response.text.index("Login failures") < debug_response.text.index("Cloudflare Blocked IPs")
    assert debug_response.text.index("Cloudflare Blocked IPs") < debug_response.text.index("Autotask submission attempts")
    assert debug_response.text.index("Autotask submission attempts") < debug_response.text.index("Autotask configuration snapshot")
    assert debug_response.text.index("Autotask configuration snapshot") < debug_response.text.index("Test Autotask API")
    assert debug_response.text.index("Autotask configuration snapshot") < debug_response.text.index("Full data backup")
    assert debug_response.text.index("Full data backup") < debug_response.text.index("Automatic database backups")
    assert "Application Log" not in debug_response.text
    assert 'class="autotask-config-list"' in debug_response.text
    assert "Time entry type" not in debug_response.text
    assert "Status mapping IDs" not in debug_response.text
    assert "Use Test Autotask API to verify the mandatory Autotask dependency" not in debug_response.text
    assert 'class="backup-meta-grid"' in debug_response.text
    assert "Restore scope" in debug_response.text
    assert "Validated restores replace all Job Logger database tables with the backup contents." in debug_response.text
    assert "Restore confirmation" not in debug_response.text
    assert '<div class="debug-scroll-table-wrap debug-submission-table-wrap diagnostics-seven-row-window">' in debug_response.text
    assert '<table class="debug-submission-table">' in debug_response.text
    assert "1 retained, 7 per page" in debug_response.text
    assert "<th>User</th>" in debug_response.text
    assert "Test Technician" in debug_response.text
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


def test_automatic_backup_retention_keeps_hourly_and_recent_daily_backups(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """Automatic backups should retain recent hourly files and three daily snapshots."""

    _seed_full_backup_data()
    backup_times = (
        datetime(2026, 6, 17, 16, 0, tzinfo=UTC),
        datetime(2026, 6, 18, 16, 0, tzinfo=UTC),
        datetime(2026, 6, 19, 16, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 10, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 11, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 13, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 14, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 15, 0, tzinfo=UTC),
        datetime(2026, 6, 20, 16, 0, tzinfo=UTC),
    )

    with database.SessionLocal() as database_session:
        for backup_time in backup_times:
            create_automatic_backup(database_session, tmp_path, now=backup_time)

    available_backups = list_automatic_backup_files(tmp_path)
    available_names = {backup_file.filename for backup_file in available_backups}
    expected_names = {
        automatic_backup_filename(datetime(2026, 6, 18, 16, 0, tzinfo=UTC)),
        automatic_backup_filename(datetime(2026, 6, 19, 16, 0, tzinfo=UTC)),
        automatic_backup_filename(datetime(2026, 6, 20, 11, 0, tzinfo=UTC)),
        automatic_backup_filename(datetime(2026, 6, 20, 12, 0, tzinfo=UTC)),
        automatic_backup_filename(datetime(2026, 6, 20, 13, 0, tzinfo=UTC)),
        automatic_backup_filename(datetime(2026, 6, 20, 14, 0, tzinfo=UTC)),
        automatic_backup_filename(datetime(2026, 6, 20, 15, 0, tzinfo=UTC)),
        automatic_backup_filename(datetime(2026, 6, 20, 16, 0, tzinfo=UTC)),
    }

    assert available_names == expected_names
    assert automatic_backup_filename(datetime(2026, 6, 17, 16, 0, tzinfo=UTC)) not in available_names
    assert automatic_backup_filename(datetime(2026, 6, 20, 10, 0, tzinfo=UTC)) not in available_names
    assert [backup_file.created_at_utc for backup_file in available_backups] == sorted(
        [backup_file.created_at_utc for backup_file in available_backups],
        reverse=True,
    )


def test_debug_lists_and_restores_automatic_backups(super_admin_client: TestClient) -> None:
    """The super-admin debug page should restore retained automatic backup files."""

    original_job_id = _seed_full_backup_data()
    backup_result = run_automatic_backup_once(settings, trigger=AUTOMATIC_BACKUP_TRIGGER_STARTUP)
    short_backup_name = backup_result.backup_file.filename.removeprefix(
        AUTOMATIC_BACKUP_FILENAME_PREFIX
    ).removesuffix(AUTOMATIC_BACKUP_FILENAME_SUFFIX)

    debug_page_response = super_admin_client.get("/debug")
    assert debug_page_response.status_code == 200
    assert "Automatic database backups" in debug_page_response.text
    assert 'class="review-header automatic-backup-header"' in debug_page_response.text
    assert "Retention" in debug_page_response.text
    assert "Newest 6 hourly backups, plus one daily backup for today and each of the prior 2 days." in debug_page_response.text
    assert backup_result.backup_file.filename in debug_page_response.text
    assert f'title="{backup_result.backup_file.filename}">{short_backup_name}</span>' in debug_page_response.text
    assert '<col class="automatic-backup-file-col">' in debug_page_response.text
    assert '<col class="automatic-backup-source-col">' in debug_page_response.text
    assert '<div class="debug-scroll-table-wrap automatic-backup-table-wrap">' in debug_page_response.text
    assert "<th>Source</th>" in debug_page_response.text
    assert "Startup" in debug_page_response.text
    assert '/debug/automatic-backups/download' in debug_page_response.text
    assert '/debug/automatic-backups/restore' in debug_page_response.text
    csrf_token = extract_csrf_token(debug_page_response.text)

    with database.SessionLocal() as database_session:
        backup_event = database_session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "debug.automatic_backup.created")
            .order_by(AuditEvent.created_at_utc.desc())
        )
        assert backup_event is not None
        assert backup_event.details["filename"] == backup_result.backup_file.filename
        assert backup_event.details["trigger"] == AUTOMATIC_BACKUP_TRIGGER_STARTUP

    temporary_job_id = _add_temporary_job()
    restore_response = super_admin_client.post(
        "/debug/automatic-backups/restore",
        data={
            "csrf_token": csrf_token,
            "filename": backup_result.backup_file.filename,
            "confirmation": "RESTORE",
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    assert restore_response.headers["location"] == "/debug#automatic-backups"

    restored_page_response = super_admin_client.get("/debug")
    assert restored_page_response.status_code == 200
    assert "Automatic backup restore completed." in restored_page_response.text
    with database.SessionLocal() as database_session:
        assert database_session.scalar(select(func.count(Job.id))) == 1
        assert database_session.get(Job, original_job_id) is not None
        assert database_session.get(Job, temporary_job_id) is None
        actions = list(database_session.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at_utc)))
        assert "backup.seeded" in actions
        assert "debug.automatic_backup.restored" in actions


def test_debug_downloads_automatic_backup(super_admin_client: TestClient) -> None:
    """Automatic backups should be individually downloadable from diagnostics."""

    automatic_backup_dir = Path(os.environ["AUTOMATIC_BACKUP_DIR"])
    _seed_full_backup_data()
    with database.SessionLocal() as database_session:
        backup_result = create_automatic_backup(
            database_session,
            automatic_backup_dir,
            now=datetime(2026, 6, 20, 16, 0, tzinfo=UTC),
        )

    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    download_response = super_admin_client.post(
        "/debug/automatic-backups/download",
        data={"csrf_token": csrf_token, "filename": backup_result.backup_file.filename},
    )

    assert download_response.status_code == 200
    assert download_response.content == backup_result.backup_file.path.read_bytes()
    assert download_response.headers["cache-control"] == "no-store"
    assert backup_result.backup_file.filename in download_response.headers["content-disposition"]
    payload = json.loads(gzip.decompress(download_response.content).decode("utf-8"))
    assert payload["format"] == "job_logger.full_backup"

    with database.SessionLocal() as database_session:
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "debug.automatic_backup.downloaded")
        )
        assert audit_event is not None
        assert audit_event.details["filename"] == backup_result.backup_file.filename


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


def test_debug_restore_defaults_direct_submit_for_legacy_preference_backups(
    super_admin_client: TestClient,
) -> None:
    """Restore v1.0.2 preference rows by defaulting the v1.1.0 workflow option off."""

    with database.SessionLocal() as database_session:
        database_session.add(
            UserPreference(
                principal_key="web_user:legacy-direct-submit-test",
                theme=ThemeMode.LIGHT,
                submit_from_work_in_progress=True,
            )
        )
        database_session.commit()

    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    for row in payload["tables"]["user_preferences"]:
        row.pop("submit_from_work_in_progress", None)
        row.pop("allow_navigation_on_full_web", None)
    payload["schema"]["user_preferences"].remove("submit_from_work_in_progress")
    payload["schema"]["user_preferences"].remove("allow_navigation_on_full_web")
    legacy_backup_content = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-v1.0.2-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        restored_preference = database_session.scalar(
            select(UserPreference).where(UserPreference.principal_key == "web_user:legacy-direct-submit-test")
        )
        assert restored_preference is not None
        assert restored_preference.theme == ThemeMode.LIGHT
        assert restored_preference.submit_from_work_in_progress is False
        assert restored_preference.allow_navigation_on_full_web is False


def test_debug_restore_defaults_missing_web_session_invalidation_column(
    super_admin_client: TestClient,
) -> None:
    """Restore backups that predate managed-user session invalidation cutoffs."""

    invalidation_time = datetime(2026, 6, 21, 13, 30, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.sessions_invalidated_at_utc = invalidation_time
        database_session.commit()

    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    for row in payload["tables"]["web_users"]:
        row.pop("sessions_invalidated_at_utc", None)
    payload["schema"]["web_users"].remove("sessions_invalidated_at_utc")
    legacy_backup_content = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-pre-session-invalidation-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        restored_user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert restored_user is not None
        assert restored_user.sessions_invalidated_at_utc is None


def test_debug_restore_defaults_missing_web_user_default_role_column(
    super_admin_client: TestClient,
) -> None:
    """Restore backups that predate per-user default service-desk roles."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.autotask_default_service_desk_role_id = 8
        database_session.commit()

    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    for row in payload["tables"]["web_users"]:
        row.pop("autotask_default_service_desk_role_id", None)
    payload["schema"]["web_users"].remove("autotask_default_service_desk_role_id")
    legacy_backup_content = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-pre-default-role-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        restored_user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert restored_user is not None
        assert restored_user.autotask_default_service_desk_role_id is None


def test_debug_restore_defaults_missing_web_user_last_login_column(
    super_admin_client: TestClient,
) -> None:
    """Restore backups that predate managed-user last-login metadata."""

    last_login_at_utc = datetime(2026, 6, 23, 13, 30, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.last_login_at_utc = last_login_at_utc
        database_session.commit()

    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    for row in payload["tables"]["web_users"]:
        row.pop("last_login_at_utc", None)
    payload["schema"]["web_users"].remove("last_login_at_utc")
    legacy_backup_content = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-pre-last-login-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        restored_user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert restored_user is not None
        assert restored_user.last_login_at_utc is None


def test_debug_restore_defaults_missing_web_user_admin_column(
    super_admin_client: TestClient,
) -> None:
    """Restore backups that predate managed-user Diagnostics admin grants."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.is_admin = True
        database_session.commit()

    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    for row in payload["tables"]["web_users"]:
        row.pop("is_admin", None)
    payload["schema"]["web_users"].remove("is_admin")
    legacy_backup_content = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-pre-debug-admin-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        restored_user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert restored_user is not None
        assert restored_user.is_admin is False


def test_debug_restore_defaults_missing_web_user_password_change_column(
    super_admin_client: TestClient,
) -> None:
    """Restore backups that predate temporary-password enforcement metadata."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.password_must_change = True
        database_session.commit()

    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    for row in payload["tables"]["web_users"]:
        row.pop("password_must_change", None)
    payload["schema"]["web_users"].remove("password_must_change")
    legacy_backup_content = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-pre-password-change-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        restored_user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert restored_user is not None
        assert restored_user.password_must_change is False


def test_debug_restore_defaults_missing_web_user_archive_column(
    super_admin_client: TestClient,
) -> None:
    """Restore backups that predate hidden web-user archival metadata."""

    archived_at_utc = datetime(2026, 7, 10, 13, 30, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.archived_at_utc = archived_at_utc
        database_session.commit()

    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    for row in payload["tables"]["web_users"]:
        row.pop("archived_at_utc", None)
    payload["schema"]["web_users"].remove("archived_at_utc")
    legacy_backup_content = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-pre-web-user-archive-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        restored_user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert restored_user is not None
        assert restored_user.archived_at_utc is None


def test_debug_restore_defaults_missing_ai_cleanup_revert_columns(
    super_admin_client: TestClient,
) -> None:
    """Restore backups that predate server-backed AI cleanup undo fields."""

    original_job_id = _seed_full_backup_data()
    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    for column_name in (
        "ai_cleanup_original_summary",
        "ai_cleanup_pending_summary",
        "ai_cleanup_source",
        "ai_cleanup_at_utc",
    ):
        payload["schema"]["jobs"].remove(column_name)
        for row in payload["tables"]["jobs"]:
            row.pop(column_name, None)
    legacy_backup_content = gzip.compress(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-pre-cleanup-revert-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        restored_job = database_session.get(Job, original_job_id)
        assert restored_job is not None
        assert restored_job.ai_cleanup_original_summary is None
        assert restored_job.ai_cleanup_pending_summary is None
        assert restored_job.ai_cleanup_source is None
        assert restored_job.ai_cleanup_at_utc is None


def test_debug_restore_defaults_missing_passkey_table_to_empty(
    super_admin_client: TestClient,
) -> None:
    """Restore backups that predate passkey support with no registered passkeys."""

    _seed_full_backup_data()
    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    payload["tables"].pop("webauthn_credentials", None)
    payload["schema"].pop("webauthn_credentials", None)
    legacy_backup_content = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-pre-passkey-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        assert database_session.scalar(select(func.count(WebAuthnCredential.id))) == 0


def test_debug_restore_defaults_missing_cloudflare_security_tables_to_empty(
    super_admin_client: TestClient,
) -> None:
    """Restore backups that predate app-managed Cloudflare block tables."""

    _seed_full_backup_data()
    with database.SessionLocal() as database_session:
        database_session.add(
            LoginFailureCounter(
                client_ip="198.51.100.77",
                username="admin",
                failed_count=3,
                created_at_utc=datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
                updated_at_utc=datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
            )
        )
        database_session.add(
            CloudflareIPBlock(
                ip_address="198.51.100.77",
                cloudflare_rule_id="cf-backup-rule",
                source="automatic",
                reason="backup compatibility seed",
                failure_count=3,
                notes="Job Logger automatic block",
                created_at_utc=datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
                updated_at_utc=datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
            )
        )
        database_session.add(
            LoginAttempt(
                succeeded=False,
                event="web_login_failed",
                created_at_utc=datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
                client_ip="198.51.100.77",
                enforcement_client_ip="198.51.100.77",
                username="backup-user",
                reason="invalid_credentials",
                hidden_at_utc=datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
            )
        )
        database_session.commit()

    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    for table_name in ("cloudflare_ip_blocks", "login_attempts", "login_failure_counters"):
        payload["tables"].pop(table_name, None)
        payload["schema"].pop(table_name, None)
        payload["table_counts"].pop(table_name, None)
    legacy_backup_content = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-pre-cloudflare-blocks-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        assert database_session.scalar(select(func.count(CloudflareIPBlock.id))) == 0
        assert database_session.scalar(select(func.count(LoginAttempt.id))) == 0
        assert database_session.scalar(select(func.count(LoginFailureCounter.id))) == 0


def test_debug_restore_defaults_missing_login_counter_username(
    super_admin_client: TestClient,
) -> None:
    """Restore backups that predate username-scoped local login counters."""

    with database.SessionLocal() as database_session:
        database_session.add(
            LoginFailureCounter(
                client_ip="198.51.100.88",
                username="admin",
                failed_count=4,
                created_at_utc=datetime(2026, 6, 27, 12, 0, tzinfo=UTC),
                updated_at_utc=datetime(2026, 6, 27, 12, 0, tzinfo=UTC),
            )
        )
        database_session.commit()

    debug_page_response = super_admin_client.get("/debug")
    csrf_token = extract_csrf_token(debug_page_response.text)
    backup_response = super_admin_client.post(
        "/debug/backup",
        data={"csrf_token": csrf_token},
    )
    payload = json.loads(gzip.decompress(backup_response.content).decode("utf-8"))
    for row in payload["tables"]["login_failure_counters"]:
        row.pop("username", None)
    payload["schema"]["login_failure_counters"].remove("username")
    legacy_backup_content = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        mtime=0,
    )

    restore_page_response = super_admin_client.get("/debug")
    restore_csrf_token = extract_csrf_token(restore_page_response.text)
    restore_response = super_admin_client.post(
        "/debug/restore",
        data={"csrf_token": restore_csrf_token, "confirmation": "RESTORE"},
        files={
            "backup_file": (
                "job-logger-pre-login-counter-username-full-backup.json.gz",
                legacy_backup_content,
                "application/gzip",
            )
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        counter = database_session.scalar(
            select(LoginFailureCounter).where(LoginFailureCounter.client_ip == "198.51.100.88")
        )
        assert counter is not None
        assert counter.username == ""
        assert counter.failed_count == 4


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


def test_debug_automatic_backup_download_requires_csrf(super_admin_client: TestClient) -> None:
    """Automatic backup downloads are sensitive and require CSRF protection."""

    response = super_admin_client.post(
        "/debug/automatic-backups/download",
        data={"filename": automatic_backup_filename(datetime(2026, 6, 20, 16, 0, tzinfo=UTC))},
        follow_redirects=False,
    )

    assert response.status_code == 403
