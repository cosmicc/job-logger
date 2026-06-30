"""Tests for per-user configuration and theme preferences."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from job_logger import database
from job_logger.config import load_settings, settings
from job_logger.enums import ThemeMode
from job_logger.main import create_app, validate_runtime_settings
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
    assert "Device sign-in" in config_response.text
    assert "Set up device sign-in" in config_response.text
    assert "No device sign-ins have been added" in config_response.text
    assert "Submit from Work in Progress" in config_response.text
    assert "submits the time entry to Autotask immediately" in config_response.text
    assert "data-direct-submit-option" in config_response.text
    assert "data-direct-submit-state" in config_response.text
    assert "Off" in config_response.text
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
    assert save_response.json()["submit_from_work_in_progress"] is False

    workflow_response = authenticated_client.post(
        "/config",
        headers={"Accept": "application/json", "X-CSRF-Token": csrf_token},
        data={"csrf_token": csrf_token, "submit_from_work_in_progress": "true"},
        follow_redirects=False,
    )
    assert workflow_response.status_code == 200
    assert workflow_response.json()["theme"] == "light"
    assert workflow_response.json()["submit_from_work_in_progress"] is True

    updated_config_response = authenticated_client.get("/config")
    mobile_response = authenticated_client.get("/home")
    assert 'class="theme-light"' in updated_config_response.text
    assert 'class="theme-light"' in mobile_response.text
    assert re.search(r'name="theme"[^>]+value="light"[^>]+checked', updated_config_response.text)
    assert "On" in updated_config_response.text

    with database.SessionLocal() as database_session:
        preference = database_session.scalar(select(UserPreference).where(UserPreference.principal_key.like("web_user:%")))
        assert preference is not None
        assert preference.theme == ThemeMode.LIGHT
        assert preference.submit_from_work_in_progress is True


def test_dev_build_flag_uses_strict_boolean_environment_value(monkeypatch) -> None:
    """DEV_BUILD should opt in only when the deployment explicitly enables it."""

    monkeypatch.delenv("DEV_BUILD", raising=False)
    assert load_settings().dev_build is False

    monkeypatch.setenv("DEV_BUILD", "true")
    assert load_settings().dev_build is True

    monkeypatch.setenv("DEV_BUILD", "false")
    assert load_settings().dev_build is False


def test_cloudflare_block_settings_load_from_environment(monkeypatch) -> None:
    """Cloudflare block settings should stay environment-only and validated."""

    monkeypatch.setenv("CLOUDFLARE_IP_BLOCKING_ENABLED", "true")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token-value")
    monkeypatch.setenv("CLOUDFLARE_ZONE_ID", "zone-value")
    monkeypatch.setenv("CLOUDFLARE_IP_BLOCK_ALLOWLIST", "198.51.100.1, 203.0.113.0/24")
    monkeypatch.setenv("CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS", "7")

    loaded_settings = load_settings()

    assert loaded_settings.cloudflare_ip_blocking_enabled is True
    assert loaded_settings.cloudflare_api_token == "token-value"
    assert loaded_settings.cloudflare_zone_id == "zone-value"
    assert loaded_settings.cloudflare_ip_block_allowlist == "198.51.100.1, 203.0.113.0/24"
    assert loaded_settings.cloudflare_auto_block_failed_login_attempts == 7


def test_local_login_lockout_duration_loads_from_environment(monkeypatch) -> None:
    """Local lockout duration should be configurable and positive."""

    monkeypatch.setenv("LOGIN_LOCAL_LOCKOUT_MINUTES", "20")

    assert load_settings().login_local_lockout_minutes == 20


def test_local_login_lockout_duration_must_be_positive(monkeypatch) -> None:
    """Disabling local lockout through a zero duration would reopen brute-force risk."""

    monkeypatch.setenv("LOGIN_LOCAL_LOCKOUT_MINUTES", "0")

    with pytest.raises(ValueError, match="LOGIN_LOCAL_LOCKOUT_MINUTES must be greater than zero."):
        load_settings()


def test_runtime_validation_allows_cloudflare_access_disabled_in_production() -> None:
    """Production can start without Cloudflare Access while app auth remains enforced."""

    production_settings = replace(
        settings,
        app_environment="production",
        app_secret_key="x" * 32,
        app_password="not-the-default-password",
        database_url="postgresql+psycopg://job_logger:not-default@db:5432/job_logger",
        session_cookie_secure=True,
        cloudflare_access_required=False,
        autotask_provider="autotask",
    )

    validate_runtime_settings(production_settings)


def test_runtime_validation_rejects_production_development_defaults() -> None:
    """Production should reject secrets and database passwords from development examples."""

    production_settings = replace(
        settings,
        app_environment="production",
        app_secret_key="development-only-change-me",
        app_password="admin",
        database_url="postgresql+psycopg://job_logger:job_logger_password@db:5432/job_logger",
        session_cookie_secure=True,
        cloudflare_access_required=True,
        autotask_provider="autotask",
    )

    with pytest.raises(RuntimeError, match="APP_SECRET_KEY must be replaced in production."):
        validate_runtime_settings(production_settings)


def test_runtime_validation_rejects_production_placeholder_secrets() -> None:
    """Copying .env.example without replacing placeholders should not start production."""

    production_settings = replace(
        settings,
        app_environment="production",
        app_secret_key="replace-with-at-least-32-random-characters",
        app_password="replace-with-a-long-random-app-password",
        database_url="postgresql+psycopg://job_logger:replace-with-a-long-random-database-password@db:5432/job_logger",
        session_cookie_secure=True,
        cloudflare_access_required=True,
        autotask_provider="autotask",
    )

    with pytest.raises(RuntimeError, match="APP_SECRET_KEY must be replaced in production."):
        validate_runtime_settings(production_settings)


def test_production_security_headers_include_hsts() -> None:
    """Production responses should include app-side HSTS for HTTPS deployments."""

    production_settings = replace(
        settings,
        app_environment="production",
        app_secret_key="x" * 32,
        app_password="not-the-default-password",
        database_url="postgresql+psycopg://job_logger:not-default@db:5432/job_logger",
        session_cookie_secure=True,
        cloudflare_access_required=True,
        autotask_provider="autotask",
        automatic_backups_enabled=False,
    )
    test_app = create_app(production_settings)
    with TestClient(test_app) as test_client:
        response = test_client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == "max-age=15552000"


def test_ai_cleanup_revert_retention_loads_from_environment(monkeypatch) -> None:
    """Stored cleanup undo text should have a configurable positive retention window."""

    monkeypatch.setenv("AI_CLEANUP_REVERT_RETENTION_HOURS", "6.5")

    assert load_settings().ai_cleanup_revert_retention_hours == 6.5


def test_cloudflare_auto_block_threshold_must_be_positive(monkeypatch) -> None:
    """A zero auto-block threshold would make every failure block immediately."""

    monkeypatch.setenv("CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS", "0")

    try:
        load_settings()
    except ValueError as exc:
        assert "CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS must be greater than zero." in str(exc)
    else:
        raise AssertionError("Expected a validation error for a zero Cloudflare auto-block threshold.")


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
    passkey_options_response = client.post(
        "/config/passkeys/options",
        headers={"Accept": "application/json", "X-CSRF-Token": csrf_token},
        json={},
        follow_redirects=False,
    )
    assert passkey_options_response.status_code == 403
    passkey_delete_response = client.post(
        "/config/passkeys/not-a-passkey/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert passkey_delete_response.status_code == 403
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
