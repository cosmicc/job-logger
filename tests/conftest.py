"""Shared pytest setup for the Job Logger app."""

from __future__ import annotations

import os
import re
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
os.environ["LOGIN_FAILURE_DEBUG_ROWS"] = "20"
os.environ["APP_ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
os.environ["APP_SESSION_COOKIE_SECURE"] = "false"
os.environ["CLOUDFLARE_ACCESS_REQUIRED"] = "false"
os.environ["DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["TRANSCRIPTION_PROVIDER"] = "mock"
os.environ["AUTOTASK_PROVIDER"] = "mock"

from job_logger import database  # noqa: E402
from job_logger.database import Base  # noqa: E402
from job_logger.main import create_app  # noqa: E402
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
    login_failure_log_path.unlink(missing_ok=True)
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
    Base.metadata.drop_all(database.engine)
    login_failure_log_path.unlink(missing_ok=True)


@pytest.fixture()
def authenticated_client(client: TestClient) -> TestClient:
    """Return a client with an authenticated managed web-user session."""

    return login_as_web_user(client)


@pytest.fixture()
def super_admin_client(client: TestClient) -> TestClient:
    """Return a client authenticated as the config super admin."""

    return login_as_super_admin(client)
