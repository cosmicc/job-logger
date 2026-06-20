"""Tests for per-user configuration and theme preferences."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from job_logger import database
from job_logger.enums import ThemeMode
from job_logger.models import UserPreference
from tests.conftest import extract_csrf_token, login_as_super_admin, login_as_web_user


def test_web_user_config_defaults_to_dark_and_can_save_light_theme(authenticated_client: TestClient) -> None:
    """Managed web users should get dark by default and persist their own theme."""

    config_response = authenticated_client.get("/config")
    assert config_response.status_code == 200
    assert 'class="theme-dark"' in config_response.text
    assert re.search(r'name="theme"[^>]+value="dark"[^>]+checked', config_response.text)

    csrf_token = extract_csrf_token(config_response.text)
    save_response = authenticated_client.post(
        "/config",
        data={"csrf_token": csrf_token, "theme": "light"},
        follow_redirects=False,
    )
    assert save_response.status_code == 303
    assert save_response.headers["location"] == "/config"

    updated_config_response = authenticated_client.get("/config")
    mobile_response = authenticated_client.get("/mobile")
    assert 'class="theme-light"' in updated_config_response.text
    assert 'class="theme-light"' in mobile_response.text
    assert re.search(r'name="theme"[^>]+value="light"[^>]+checked', updated_config_response.text)

    with database.SessionLocal() as database_session:
        preference = database_session.scalar(select(UserPreference).where(UserPreference.principal_key.like("web_user:%")))
        assert preference is not None
        assert preference.theme == ThemeMode.LIGHT


def test_super_admin_theme_is_separate_from_managed_web_user(client: TestClient) -> None:
    """The config super admin can save its own theme without changing web users."""

    login_as_super_admin(client)
    admin_config_response = client.get("/config")
    csrf_token = extract_csrf_token(admin_config_response.text)
    save_response = client.post(
        "/config",
        data={"csrf_token": csrf_token, "theme": "light"},
        follow_redirects=False,
    )
    assert save_response.status_code == 303
    assert 'class="theme-light"' in client.get("/users").text

    login_as_web_user(client)
    user_config_response = client.get("/config")
    assert 'class="theme-dark"' in user_config_response.text

    with database.SessionLocal() as database_session:
        admin_preference = database_session.scalar(
            select(UserPreference).where(UserPreference.principal_key == "super_admin:admin")
        )
        assert admin_preference is not None
        assert admin_preference.theme == ThemeMode.LIGHT
