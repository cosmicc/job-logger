"""Tests for per-user configuration and theme preferences."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from job_logger import database
from job_logger.config import load_settings, settings
from job_logger.database import create_database_engine, normalize_database_url
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
    assert "submits the completed entry to Autotask immediately" in config_response.text
    assert "data-direct-submit-option" in config_response.text
    assert "data-direct-submit-state" in config_response.text
    assert "Off" in config_response.text
    assert (
        config_response.text.index('id="appearance-heading"')
        < config_response.text.index('id="password-heading"')
        < config_response.text.index('id="passkeys-heading"')
        < config_response.text.index('id="workflow-heading"')
    )
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


def test_autotask_thread_limit_settings_load_from_environment(monkeypatch) -> None:
    """Autotask concurrency settings should stay bounded by the API threshold."""

    monkeypatch.setenv("AUTOTASK_MAX_CONCURRENT_REQUESTS", "3")
    monkeypatch.setenv("AUTOTASK_REQUEST_SLOT_TIMEOUT_SECONDS", "12.5")

    loaded_settings = load_settings()

    assert loaded_settings.autotask_max_concurrent_requests == 3
    assert loaded_settings.autotask_request_slot_timeout_seconds == 12.5

    monkeypatch.setenv("AUTOTASK_MAX_CONCURRENT_REQUESTS", "4")
    with pytest.raises(ValueError, match="AUTOTASK_MAX_CONCURRENT_REQUESTS"):
        load_settings()


def test_password_reset_settings_load_from_environment(monkeypatch) -> None:
    """Password reset, SMTP, and Turnstile settings should stay environment-backed."""

    monkeypatch.setenv("PASSWORD_RESET_ENABLED", "true")
    monkeypatch.setenv("PASSWORD_RESET_TOKEN_TTL_HOURS", "12")
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://logger.example.test/")
    monkeypatch.setenv("MAIL_ENABLED", "true")
    monkeypatch.setenv("MAIL_FROM_EMAIL", "support@example.test")
    monkeypatch.setenv("MAIL_FROM_NAME", "Job Logger Support")
    monkeypatch.setenv("MAIL_MODE", "smtp")
    monkeypatch.setenv("MAIL_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("MAIL_SMTP_PORT", "465")
    monkeypatch.setenv("MAIL_SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("MAIL_SMTP_PASSWORD", "smtp-password")
    monkeypatch.setenv("MAIL_SMTP_STARTTLS", "false")
    monkeypatch.setenv("MAIL_SMTP_SSL", "true")
    monkeypatch.setenv("MAIL_SMTP_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("MAIL_SMTP2GO_API_KEY", "api-test-key")
    monkeypatch.setenv("TURNSTILE_ENABLED", "true")
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "site-key")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret-key")
    monkeypatch.setenv("TURNSTILE_VERIFY_URL", "https://turnstile.example.test/siteverify")
    monkeypatch.setenv("TURNSTILE_TIMEOUT_SECONDS", "4.5")

    loaded_settings = load_settings()

    assert loaded_settings.password_reset_enabled is True
    assert loaded_settings.password_reset_token_ttl_hours == 12
    assert loaded_settings.password_reset_token_ttl_seconds == 43200
    assert loaded_settings.app_public_base_url == "https://logger.example.test"
    assert loaded_settings.password_reset_mail_configured is True
    assert loaded_settings.mail_enabled is True
    assert loaded_settings.mail_from_email == "support@example.test"
    assert loaded_settings.mail_from_name == "Job Logger Support"
    assert loaded_settings.mail_mode == "smtp"
    assert loaded_settings.mail_smtp_host == "smtp.example.test"
    assert loaded_settings.mail_smtp_port == 465
    assert loaded_settings.mail_smtp_username == "smtp-user"
    assert loaded_settings.mail_smtp_password == "smtp-password"
    assert loaded_settings.mail_smtp_starttls is False
    assert loaded_settings.mail_smtp_ssl is True
    assert loaded_settings.mail_smtp_timeout_seconds == 7.5
    assert loaded_settings.mail_smtp2go_api_key == "api-test-key"
    assert loaded_settings.turnstile_enabled is True
    assert loaded_settings.turnstile_site_key == "site-key"
    assert loaded_settings.turnstile_secret_key == "secret-key"
    assert loaded_settings.turnstile_verify_url == "https://turnstile.example.test/siteverify"
    assert loaded_settings.turnstile_timeout_seconds == 4.5


def test_password_reset_runtime_validation_requires_mail_public_url_and_turnstile() -> None:
    """Password reset should fail closed unless all security dependencies are configured."""

    safe_reset_settings = replace(
        settings,
        password_reset_enabled=True,
        app_public_base_url="https://logger.example.test",
        mail_enabled=True,
        mail_from_email="support@example.test",
        mail_smtp_host="smtp.example.test",
        mail_smtp_starttls=True,
        mail_smtp_ssl=False,
        turnstile_enabled=True,
        turnstile_site_key="site-key",
        turnstile_secret_key="secret-key",
    )

    validate_runtime_settings(safe_reset_settings)

    with pytest.raises(RuntimeError, match="APP_PUBLIC_BASE_URL"):
        validate_runtime_settings(replace(safe_reset_settings, app_public_base_url=""))

    with pytest.raises(RuntimeError, match="MAIL_ENABLED"):
        validate_runtime_settings(replace(safe_reset_settings, mail_enabled=False))

    with pytest.raises(RuntimeError, match="TURNSTILE_SITE_KEY"):
        validate_runtime_settings(replace(safe_reset_settings, turnstile_site_key=""))

    with pytest.raises(RuntimeError, match="TURNSTILE_ENABLED=false"):
        validate_runtime_settings(replace(safe_reset_settings, turnstile_enabled=False, dev_build=False))

    validate_runtime_settings(replace(safe_reset_settings, turnstile_enabled=False, dev_build=True))

    with pytest.raises(RuntimeError, match="MAIL_SMTP_SSL"):
        validate_runtime_settings(replace(safe_reset_settings, mail_smtp_ssl=True, mail_smtp_starttls=True))

    smtp2go_settings = replace(
        safe_reset_settings,
        mail_mode="smtp2go",
        mail_smtp_host="",
        mail_smtp2go_api_key="api-test-key",
    )
    validate_runtime_settings(smtp2go_settings)

    with pytest.raises(RuntimeError, match="MAIL_SMTP2GO_API_KEY"):
        validate_runtime_settings(replace(smtp2go_settings, mail_smtp2go_api_key=None))


def test_invalid_mail_mode_fails_fast(monkeypatch) -> None:
    """Mail delivery mode should stay restricted to known implementations."""

    monkeypatch.setenv("MAIL_MODE", "sendmail")

    with pytest.raises(ValueError, match="MAIL_MODE"):
        load_settings()


def test_database_pool_settings_load_from_environment(monkeypatch) -> None:
    """Database connection tuning should stay environment-backed."""

    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("DATABASE_POOL_SIZE", "8")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "3")
    monkeypatch.setenv("DATABASE_POOL_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("DATABASE_POOL_RECYCLE_SECONDS", "900")
    monkeypatch.setenv("DATABASE_UNAVAILABLE_CHECK_INTERVAL_SECONDS", "6")

    loaded_settings = load_settings()

    assert loaded_settings.database_connect_timeout_seconds == 4
    assert loaded_settings.database_pool_size == 8
    assert loaded_settings.database_max_overflow == 3
    assert loaded_settings.database_pool_timeout_seconds == 12
    assert loaded_settings.database_pool_recycle_seconds == 900
    assert loaded_settings.database_unavailable_check_interval_seconds == 6


def test_app_health_and_pushover_settings_load_from_environment(monkeypatch) -> None:
    """App-health notification settings should stay environment-backed and secret-safe."""

    monkeypatch.setenv("APP_HEALTH_MONITOR_INTERVAL_SECONDS", "120")
    monkeypatch.setenv("APP_HEALTH_DB_LATENCY_WARNING_MS", "150")
    monkeypatch.setenv("APP_HEALTH_DB_LATENCY_CRITICAL_MS", "700")
    monkeypatch.setenv("APP_HEALTH_DB_POOL_WARNING_PERCENT", "75")
    monkeypatch.setenv("APP_HEALTH_DB_POOL_CRITICAL_PERCENT", "92")
    monkeypatch.setenv("PUSHOVER_ENABLED", "true")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "user-key-value")
    monkeypatch.setenv("PUSHOVER_APP_KEY", "app-key-value")
    monkeypatch.setenv("PUSHOVER_API_URL", "https://pushover.example.test/messages.json")
    monkeypatch.setenv("PUSHOVER_TIMEOUT_SECONDS", "3.5")

    loaded_settings = load_settings()

    assert loaded_settings.app_health_monitor_interval_seconds == 120
    assert loaded_settings.app_health_db_latency_warning_ms == 150
    assert loaded_settings.app_health_db_latency_critical_ms == 700
    assert loaded_settings.app_health_db_pool_warning_percent == 75
    assert loaded_settings.app_health_db_pool_critical_percent == 92
    assert loaded_settings.pushover_enabled is True
    assert loaded_settings.pushover_user_key == "user-key-value"
    assert loaded_settings.pushover_app_key == "app-key-value"
    assert loaded_settings.pushover_api_url == "https://pushover.example.test/messages.json"
    assert loaded_settings.pushover_timeout_seconds == 3.5
    assert loaded_settings.pushover_configured is True
    assert loaded_settings.pushover_notifications_enabled is True

    monkeypatch.setenv("DEV_BUILD", "true")

    dev_settings = load_settings()

    assert dev_settings.pushover_enabled is True
    assert dev_settings.pushover_configured is True
    assert dev_settings.pushover_notifications_enabled is False


def test_ai_help_settings_load_from_environment(monkeypatch) -> None:
    """AI Help settings should stay environment-backed and secret-safe."""

    monkeypatch.setenv("AI_HELP_ENABLED", "true")
    monkeypatch.setenv("AI_HELP_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", " gemini-key-value \n")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai/")
    monkeypatch.setenv("AI_HELP_MAX_TOKENS", "800")
    monkeypatch.setenv("AI_HELP_TEMPERATURE", "0.2")
    monkeypatch.setenv("AI_HELP_INSTRUCTIONS", "Answer Job Logger support questions for end users.")

    loaded_settings = load_settings()

    assert loaded_settings.ai_help_enabled is True
    assert loaded_settings.ai_help_provider == "gemini"
    assert loaded_settings.gemini_api_key == "gemini-key-value"
    assert loaded_settings.gemini_model == "gemini-3.5-flash"
    assert loaded_settings.gemini_api_base == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert loaded_settings.ai_help_max_tokens == 800
    assert loaded_settings.ai_help_temperature == 0.2
    assert loaded_settings.ai_help_instructions == "Answer Job Logger support questions for end users."
    assert loaded_settings.ai_help_configured is True


def test_gemini_cleanup_reuses_gemini_api_base(monkeypatch) -> None:
    """Gemini cleanup should share the Gemini URL setting while keeping its model."""

    monkeypatch.setenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai/")
    monkeypatch.setenv("GEMINI_CLEANUP_MODEL", "cleanup-only-model")
    monkeypatch.setenv("GEMINI_CLEANUP_API_BASE_URL", "https://wrong.example.test/v1beta")

    loaded_settings = load_settings()

    assert loaded_settings.gemini_api_base == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert loaded_settings.gemini_cleanup_model == "cleanup-only-model"
    assert not hasattr(loaded_settings, "gemini_cleanup_api_base_url")


def test_plain_postgresql_urls_use_installed_psycopg_driver() -> None:
    """Provider-style PostgreSQL URLs should not require the psycopg2 package."""

    normalized_full_url = normalize_database_url("postgresql://job_logger:not-default@db:5432/job_logger")
    normalized_short_url = normalize_database_url("postgres://job_logger:not-default@db:5432/job_logger")
    full_url_engine = create_database_engine("postgresql://job_logger:not-default@db:5432/job_logger")
    short_url_engine = create_database_engine("postgres://job_logger:not-default@db:5432/job_logger")

    try:
        assert normalized_full_url == "postgresql+psycopg://job_logger:not-default@db:5432/job_logger"
        assert normalized_short_url == "postgresql+psycopg://job_logger:not-default@db:5432/job_logger"
        assert full_url_engine.url.drivername == "postgresql+psycopg"
        assert short_url_engine.url.drivername == "postgresql+psycopg"
    finally:
        full_url_engine.dispose()
        short_url_engine.dispose()


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
        assert user.password_must_change is False
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "user.config.password_changed")
        )
        assert audit_event is not None
        assert new_password not in str(audit_event.details)

    login_as(authenticated_client, username="tech", password=new_password)
    assert authenticated_client.get("/home").status_code == 200
