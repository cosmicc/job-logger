"""Tests for per-user configuration and theme preferences."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from job_logger import database
from job_logger.enums import ThemeMode
from job_logger.models import AuditEvent, UserPreference, WebUser
from tests.conftest import TEST_WEB_USER_PASSWORD, extract_csrf_token, login_as, login_as_super_admin, login_as_web_user


def test_web_user_config_defaults_to_dark_and_autosaves_light_theme(authenticated_client: TestClient) -> None:
    """Managed web users should get dark by default and persist immediate theme changes."""

    config_response = authenticated_client.get("/config")
    assert config_response.status_code == 200
    assert 'class="theme-dark"' in config_response.text
    assert 'class="config-layout"' in config_response.text
    assert 'class="theme-option-grid theme-card-grid"' in config_response.text
    assert 'action="/config/password"' in config_response.text
    assert "Change password" in config_response.text
    assert "Password requirements" in config_response.text
    assert "At least 8 characters" in config_response.text
    assert "Lowercase and uppercase letters" in config_response.text
    assert "At least one number" in config_response.text
    assert "At least one symbol" in config_response.text
    assert 'data-config-form' in config_response.text
    assert "Save config" not in config_response.text
    assert "Current settings" not in config_response.text
    assert 'class="config-current-pill"' not in config_response.text
    assert "data-config-current-theme" not in config_response.text
    assert "data-config-theme-summary" not in config_response.text
    assert re.search(r'name="theme"[^>]+value="dark"[^>]+checked', config_response.text)

    csrf_token = extract_csrf_token(config_response.text)
    save_response = authenticated_client.post(
        "/config",
        headers={"Accept": "application/json", "X-CSRF-Token": csrf_token},
        data={"csrf_token": csrf_token, "theme": "light"},
        follow_redirects=False,
    )
    assert save_response.status_code == 200
    assert save_response.json()["theme"] == "light"
    assert save_response.json()["theme_color"] == "#f6f8fb"

    updated_config_response = authenticated_client.get("/config")
    mobile_response = authenticated_client.get("/home")
    assert 'class="theme-light"' in updated_config_response.text
    assert 'class="theme-light"' in mobile_response.text
    assert re.search(r'name="theme"[^>]+value="light"[^>]+checked', updated_config_response.text)

    with database.SessionLocal() as database_session:
        preference = database_session.scalar(select(UserPreference).where(UserPreference.principal_key.like("web_user:%")))
        assert preference is not None
        assert preference.theme == ThemeMode.LIGHT


def test_super_admin_has_no_config_menu_or_theme_preferences(client: TestClient) -> None:
    """The config super admin should stay dark and have no user config page."""

    with database.SessionLocal() as database_session:
        database_session.add(UserPreference(principal_key="super_admin:admin", theme=ThemeMode.LIGHT))
        database_session.commit()

    login_as_super_admin(client)
    users_response = client.get("/users")
    assert users_response.status_code == 200
    assert 'href="/config"' not in users_response.text
    assert 'data-mobile-config-link' not in users_response.text
    assert 'class="theme-dark"' in users_response.text

    mobile_response = client.get("/home")
    assert 'data-mobile-config-link' not in mobile_response.text

    admin_config_response = client.get("/config")
    assert admin_config_response.status_code == 403

    csrf_token = extract_csrf_token(users_response.text)
    save_response = client.post(
        "/config",
        headers={"Accept": "application/json", "X-CSRF-Token": csrf_token},
        data={"csrf_token": csrf_token, "theme": "light"},
        follow_redirects=False,
    )
    assert save_response.status_code == 403

    password_response = client.post(
        "/config/password",
        data={
            "csrf_token": csrf_token,
            "new_password": "Admin-blocked1!",
            "confirm_password": "Admin-blocked1!",
        },
        follow_redirects=False,
    )
    assert password_response.status_code == 403
    assert 'class="theme-dark"' in client.get("/users").text

    login_as_web_user(client)
    user_config_response = client.get("/config")
    assert 'class="theme-dark"' in user_config_response.text

    with database.SessionLocal() as database_session:
        admin_preference = database_session.scalar(select(UserPreference).where(UserPreference.principal_key == "super_admin:admin"))
        assert admin_preference is not None
        assert admin_preference.theme == ThemeMode.LIGHT


def test_web_user_can_change_password_from_config(authenticated_client: TestClient) -> None:
    """Managed web users should be able to change their own password from config."""

    new_password = "Changed-password1!"
    mismatch_response = authenticated_client.get("/config")
    csrf_token = extract_csrf_token(mismatch_response.text)
    password_response = authenticated_client.post(
        "/config/password",
        data={
            "csrf_token": csrf_token,
            "new_password": new_password,
            "confirm_password": "Changed-password2!",
        },
        follow_redirects=False,
    )
    assert password_response.status_code == 303

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        password_hash_after_mismatch = user.password_hash

    login_as(authenticated_client, username="tech", password=TEST_WEB_USER_PASSWORD)
    config_response = authenticated_client.get("/config")
    csrf_token = extract_csrf_token(config_response.text)
    change_response = authenticated_client.post(
        "/config/password",
        data={
            "csrf_token": csrf_token,
            "new_password": new_password,
            "confirm_password": new_password,
        },
        follow_redirects=False,
    )
    assert change_response.status_code == 303

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        assert user.password_hash != password_hash_after_mismatch
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "user.config.password_changed")
        )
        assert audit_event is not None
        assert new_password not in str(audit_event.details)

    login_as(authenticated_client, username="tech", password=new_password)
    assert authenticated_client.get("/home").status_code == 200
