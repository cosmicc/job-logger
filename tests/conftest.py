"""Shared pytest setup for the Job Logger app."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["APP_ENV"] = "development"
os.environ["APP_SECRET_KEY"] = "test-secret-key-with-enough-length"
os.environ["APP_USERNAME"] = "admin"
os.environ["APP_PASSWORD"] = "test-password"
os.environ["LOG_DIR"] = "/tmp/job-logger-test-logs"
os.environ["LOGIN_FAILURE_LOG_PATH"] = "/tmp/job-logger-test-login-failures.log"
os.environ["LOGIN_SUCCESS_LOG_PATH"] = "/tmp/job-logger-test-login-successes.log"
os.environ["LOGIN_FAILURE_DEBUG_ROWS"] = "20"
os.environ["APP_ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
os.environ["APP_SESSION_COOKIE_SECURE"] = "false"
os.environ["APP_SESSION_TIMEOUT_HOURS"] = "12"
os.environ["CLOUDFLARE_ACCESS_REQUIRED"] = "false"
os.environ["CLOUDFLARE_IP_BLOCKING_ENABLED"] = "false"
os.environ["CLOUDFLARE_API_TOKEN"] = ""
os.environ["CLOUDFLARE_ZONE_ID"] = ""
os.environ["CLOUDFLARE_IP_BLOCK_ALLOWLIST"] = ""
os.environ["CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS"] = "5"
os.environ["WEBAUTHN_RP_NAME"] = "Job Logger Test"
os.environ["WEBAUTHN_RP_ID"] = "testserver"
os.environ["WEBAUTHN_ORIGIN"] = "http://testserver"
os.environ["DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["TRANSCRIPTION_PROVIDER"] = "mock"
os.environ["AUTOTASK_PROVIDER"] = "mock"
os.environ["AUTOMATIC_BACKUPS_ENABLED"] = "false"
os.environ["AUTOMATIC_BACKUP_DIR"] = "/tmp/job-logger-test-automatic-backups"

from job_logger import database  # noqa: E402
from job_logger.database import Base  # noqa: E402
from job_logger.main import create_app  # noqa: E402
from job_logger.services.system_health import reset_cached_autotask_health  # noqa: E402
from job_logger.services.users import create_web_user  # noqa: E402

TEST_WEB_USER_PASSWORD = "Test-password1!"


def extract_csrf_token(html_text: str) -> str:
    """Extract the CSRF token rendered into test HTML."""

    match = re.search(r'name="csrf_token" value="([^"]+)"', html_text)
    assert match is not None
    return match.group(1)


def login_as(client: TestClient, *, username: str, password: str = "test-password") -> TestClient:
    """Clear any session cookie and authenticate the test client."""

    client.cookies.clear()
    login_page_response = client.get("/login")
    csrf_token = extract_csrf_token(login_page_response.text)
    login_response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": username, "password": password},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    return client


def login_as_web_user(client: TestClient) -> TestClient:
    """Authenticate the client as the seeded managed web user."""

    return login_as(client, username="tech", password=TEST_WEB_USER_PASSWORD)


def login_as_super_admin(client: TestClient) -> TestClient:
    """Authenticate the client as the config super admin."""

    return login_as(client, username="admin")


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """Return a TestClient backed by a fresh in-memory database."""

    login_failure_log_path = Path(os.environ["LOGIN_FAILURE_LOG_PATH"])
    login_success_log_path = Path(os.environ["LOGIN_SUCCESS_LOG_PATH"])
    automatic_backup_dir = Path(os.environ["AUTOMATIC_BACKUP_DIR"])
    login_failure_log_path.unlink(missing_ok=True)
    login_success_log_path.unlink(missing_ok=True)
    shutil.rmtree(Path(os.environ["LOG_DIR"]), ignore_errors=True)
    shutil.rmtree(automatic_backup_dir, ignore_errors=True)
    reset_cached_autotask_health()
    database.configure_database("sqlite+pysqlite://")
    Base.metadata.create_all(database.engine)
    with database.SessionLocal() as database_session:
        create_web_user(
            database_session,
            full_name="Test Technician",
            username="tech",
            password=TEST_WEB_USER_PASSWORD,
            autotask_resource_id=1,
        )
        database_session.commit()
    test_app = create_app()
    with TestClient(test_app) as test_client:
        yield test_client
    reset_cached_autotask_health()
    Base.metadata.drop_all(database.engine)
    login_failure_log_path.unlink(missing_ok=True)
    login_success_log_path.unlink(missing_ok=True)
    shutil.rmtree(Path(os.environ["LOG_DIR"]), ignore_errors=True)
    shutil.rmtree(automatic_backup_dir, ignore_errors=True)


@pytest.fixture()
def authenticated_client(client: TestClient) -> TestClient:
    """Return a client with an authenticated managed web-user session."""

    return login_as_web_user(client)


@pytest.fixture()
def super_admin_client(client: TestClient) -> TestClient:
    """Return a client authenticated as the config super admin."""

    return login_as_super_admin(client)
