"""Shared pytest setup for the Job Logger app."""

from __future__ import annotations

import os
import re
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

os.environ["APP_ENV"] = "development"
os.environ["APP_SECRET_KEY"] = "test-secret-key-with-enough-length"
os.environ["APP_USERNAME"] = "admin"
os.environ["APP_PASSWORD"] = "test-password"
os.environ["APP_PASSWORD_HASH"] = ""
os.environ["APP_ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
os.environ["APP_SESSION_COOKIE_SECURE"] = "false"
os.environ["DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["TRANSCRIPTION_PROVIDER"] = "mock"
os.environ["AUTOTASK_PROVIDER"] = "mock"

from job_logger import database  # noqa: E402
from job_logger.database import Base  # noqa: E402
from job_logger.main import create_app  # noqa: E402


def extract_csrf_token(html_text: str) -> str:
    """Extract the CSRF token rendered into test HTML."""

    match = re.search(r'name="csrf_token" value="([^"]+)"', html_text)
    assert match is not None
    return match.group(1)


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """Return a TestClient backed by a fresh in-memory database."""

    database.configure_database("sqlite+pysqlite://")
    Base.metadata.create_all(database.engine)
    test_app = create_app()
    with TestClient(test_app) as test_client:
        yield test_client
    Base.metadata.drop_all(database.engine)


@pytest.fixture()
def authenticated_client(client: TestClient) -> TestClient:
    """Return a client with an authenticated local app session."""

    login_page_response = client.get("/login")
    csrf_token = extract_csrf_token(login_page_response.text)
    login_response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "admin", "password": "test-password"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    return client

