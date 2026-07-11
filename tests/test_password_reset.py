"""Tests for self-service managed-user password reset."""

from __future__ import annotations

import logging
from dataclasses import replace
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import select

from job_logger import database
from job_logger.config import settings
from job_logger.main import create_app
from job_logger.models import AuditEvent, PasswordResetToken, WebUser
from job_logger.routes import password_reset as password_reset_routes
from job_logger.routes import users as users_routes
from job_logger.services.mail import MailDeliveryResult
from job_logger.services.password_reset import PASSWORD_RESET_RATE_LIMIT_MESSAGE
from job_logger.services.users import create_web_user, verify_web_user_password
from tests.conftest import TEST_WEB_USER_PASSWORD, extract_csrf_token, login_as_super_admin


def _reset_settings(**overrides):
    """Return app settings with password reset enabled for route tests."""

    base_overrides = {
        "password_reset_enabled": True,
        "password_reset_token_ttl_hours": 24.0,
        "app_public_base_url": "https://joblogger.example.test",
        "mail_enabled": True,
        "mail_from_email": "joblogger@example.test",
        "mail_from_name": "Job Logger",
        "mail_smtp_host": "smtp.example.test",
        "mail_smtp_port": 587,
        "mail_smtp_username": None,
        "mail_smtp_password": None,
        "mail_smtp_starttls": True,
        "mail_smtp_ssl": False,
        "mail_smtp_timeout_seconds": 10.0,
        "turnstile_enabled": False,
        "turnstile_site_key": "",
        "turnstile_secret_key": "",
        "dev_build": False,
    }
    base_overrides.update(overrides)
    return replace(settings, **base_overrides)


def _set_seed_user_email(email: str, *, disabled: bool = False) -> str:
    """Set the seeded technician email and return the user id."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.email = email
        user.disabled = disabled
        database_session.commit()
        return user.id


def _forgot_password_csrf(client: TestClient) -> str:
    """Return the CSRF token from the reset request page."""

    response = client.get("/forgot-password")
    assert response.status_code == 200
    return extract_csrf_token(response.text)


def test_login_hides_forgot_password_link_when_reset_disabled(client: TestClient) -> None:
    """The login page should not advertise password reset unless it is enabled."""

    response = client.get("/login")

    assert response.status_code == 200
    assert "Forgot password?" not in response.text
    assert client.get("/forgot-password").status_code == 404


def test_password_reset_request_sends_only_for_one_enabled_matching_email(client: TestClient, monkeypatch) -> None:
    """Reset requests should send only when exactly one enabled user matches the email."""

    _set_seed_user_email("Tech@Example.Test")
    sent_messages: list[dict[str, str]] = []

    def fake_send_password_reset_email(**kwargs) -> MailDeliveryResult:
        sent_messages.append(kwargs)
        return MailDeliveryResult(succeeded=True)

    monkeypatch.setattr(password_reset_routes, "send_password_reset_email", fake_send_password_reset_email)
    with TestClient(create_app(_reset_settings())) as reset_client:
        login_response = reset_client.get("/login")
        assert "Forgot password?" in login_response.text
        assert login_response.text.index("Forgot password?") < login_response.text.index("This is a public device")

        csrf_token = _forgot_password_csrf(reset_client)
        existing_response = reset_client.post(
            "/forgot-password",
            data={"csrf_token": csrf_token, "email": "tech@example.test"},
            follow_redirects=False,
        )
        assert existing_response.status_code == 303
        assert existing_response.headers["location"] == "/forgot-password"
        assert len(sent_messages) == 1
        assert sent_messages[0]["recipient_email"] == "tech@example.test"
        assert sent_messages[0]["reset_url"].startswith("https://joblogger.example.test/reset-password/")

        missing_response = reset_client.post(
            "/forgot-password",
            data={"csrf_token": csrf_token, "email": "missing@example.test"},
            follow_redirects=True,
        )
        assert missing_response.status_code == 200
        assert "If an enabled Job Logger account exists for that email address" in missing_response.text
        assert len(sent_messages) == 1

        with database.SessionLocal() as database_session:
            create_web_user(
                database_session,
                full_name="Duplicate Email",
                username="duplicate",
                password="Duplicate-password1!",
                autotask_resource_id=2,
                email="tech@example.test",
                password_must_change=False,
            )
            database_session.commit()

        duplicate_response = reset_client.post(
            "/forgot-password",
            data={"csrf_token": csrf_token, "email": "tech@example.test"},
            follow_redirects=True,
        )
        assert duplicate_response.status_code == 200
        assert "If an enabled Job Logger account exists for that email address" in duplicate_response.text
        assert len(sent_messages) == 1

    with database.SessionLocal() as database_session:
        reset_tokens = list(database_session.execute(select(PasswordResetToken)).scalars())
        assert len(reset_tokens) == 1
        assert reset_tokens[0].sent_to_email == "tech@example.test"
        assert sent_messages[0]["reset_url"].rsplit("/", maxsplit=1)[-1] not in reset_tokens[0].token_hash
        audit_actions = [row.action for row in database_session.execute(select(AuditEvent)).scalars()]
        assert "auth.password_reset.email_sent" in audit_actions
        assert audit_actions.count("auth.password_reset.email_not_sent") == 2


def test_disabled_users_do_not_receive_password_reset_email(client: TestClient, monkeypatch) -> None:
    """Disabled managed users should not receive reset links."""

    _set_seed_user_email("disabled@example.test", disabled=True)
    sent_messages: list[dict[str, str]] = []

    def fake_send_password_reset_email(**kwargs) -> MailDeliveryResult:
        sent_messages.append(kwargs)
        return MailDeliveryResult(succeeded=True)

    monkeypatch.setattr(password_reset_routes, "send_password_reset_email", fake_send_password_reset_email)
    with TestClient(create_app(_reset_settings())) as reset_client:
        csrf_token = _forgot_password_csrf(reset_client)
        response = reset_client.post(
            "/forgot-password",
            data={"csrf_token": csrf_token, "email": "disabled@example.test"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "If an enabled Job Logger account exists for that email address" in response.text
    assert sent_messages == []


def test_password_reset_link_changes_password_once_and_invalidates_sessions(client: TestClient, monkeypatch) -> None:
    """A valid reset token should be single-use, update the password, and invalidate sessions."""

    user_id = _set_seed_user_email("tech@example.test")
    sent_messages: list[dict[str, str]] = []

    def fake_send_password_reset_email(**kwargs) -> MailDeliveryResult:
        sent_messages.append(kwargs)
        return MailDeliveryResult(succeeded=True)

    monkeypatch.setattr(password_reset_routes, "send_password_reset_email", fake_send_password_reset_email)
    with TestClient(create_app(_reset_settings())) as reset_client:
        csrf_token = _forgot_password_csrf(reset_client)
        reset_client.post(
            "/forgot-password",
            data={"csrf_token": csrf_token, "email": "tech@example.test"},
            follow_redirects=False,
        )
        assert len(sent_messages) == 1
        reset_path = urlsplit(sent_messages[0]["reset_url"]).path

        reset_page = reset_client.get(reset_path)
        assert reset_page.status_code == 200
        assert "Set new password" in reset_page.text
        reset_csrf = extract_csrf_token(reset_page.text)

        weak_response = reset_client.post(
            reset_path,
            data={"csrf_token": reset_csrf, "new_password": "weak", "confirm_password": "weak"},
        )
        assert weak_response.status_code == 400
        assert "Password must be at least 8 characters." in weak_response.text

        complete_response = reset_client.post(
            reset_path,
            data={
                "csrf_token": reset_csrf,
                "new_password": "New-password1!",
                "confirm_password": "New-password1!",
            },
            follow_redirects=False,
        )
        assert complete_response.status_code == 303
        assert complete_response.headers["location"] == "/login"

        reused_response = reset_client.get(reset_path)
        assert reused_response.status_code == 400
        assert "This password reset link is invalid or expired. Request a new reset link." in reused_response.text

    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.sessions_invalidated_at_utc is not None
        assert user.password_must_change is False
        assert verify_web_user_password("New-password1!", user.password_hash)
        assert not verify_web_user_password(TEST_WEB_USER_PASSWORD, user.password_hash)
        reset_token = database_session.scalar(select(PasswordResetToken))
        assert reset_token is not None
        assert reset_token.used_at_utc is not None
        audit_actions = [row.action for row in database_session.execute(select(AuditEvent)).scalars()]
        assert "auth.password_reset.completed" in audit_actions
        assert audit_actions.count("auth.password_reset.token_used") >= 1


def test_admin_sent_password_reset_link_works_when_self_service_reset_is_disabled(
    client: TestClient,
    monkeypatch,
) -> None:
    """Admin-sent reset links should work even when `/forgot-password` is hidden."""

    assert client is not None
    user_id = _set_seed_user_email("tech@example.test")
    sent_messages: list[dict[str, str]] = []

    def fake_send_password_reset_email(**kwargs) -> MailDeliveryResult:
        sent_messages.append(kwargs)
        return MailDeliveryResult(succeeded=True)

    monkeypatch.setattr(users_routes, "send_password_reset_email", fake_send_password_reset_email)
    reset_settings = _reset_settings(password_reset_enabled=False)
    with TestClient(create_app(reset_settings)) as reset_client:
        login_as_super_admin(reset_client)
        assert reset_client.get("/forgot-password").status_code == 404

        users_page_response = reset_client.get("/users")
        csrf_token = extract_csrf_token(users_page_response.text)
        send_response = reset_client.post(
            f"/users/{user_id}/password-reset-email",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert send_response.status_code == 303
        assert len(sent_messages) == 1
        reset_path = urlsplit(sent_messages[0]["reset_url"]).path

        reset_page = reset_client.get(reset_path)
        assert reset_page.status_code == 200
        assert "Set new password" in reset_page.text
        reset_csrf = extract_csrf_token(reset_page.text)
        complete_response = reset_client.post(
            reset_path,
            data={
                "csrf_token": reset_csrf,
                "new_password": "Admin-reset1!",
                "confirm_password": "Admin-reset1!",
            },
            follow_redirects=False,
        )
        assert complete_response.status_code == 303
        assert complete_response.headers["location"] == "/login"

    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert verify_web_user_password("Admin-reset1!", user.password_hash)
        assert user.password_must_change is False


def test_password_reset_requests_are_rate_limited_by_ip(client: TestClient) -> None:
    """Reset throttles should work even when submitted emails do not match users."""

    with TestClient(create_app(_reset_settings())) as reset_client:
        csrf_token = _forgot_password_csrf(reset_client)
        responses = [
            reset_client.post(
                "/forgot-password",
                data={"csrf_token": csrf_token, "email": f"missing-{index}@example.test"},
                follow_redirects=True,
            )
            for index in range(6)
        ]

    assert all(response.status_code == 200 for response in responses)
    assert PASSWORD_RESET_RATE_LIMIT_MESSAGE in responses[-1].text
    with database.SessionLocal() as database_session:
        audit_actions = [row.action for row in database_session.execute(select(AuditEvent)).scalars()]
        assert "auth.password_reset.rate_limited" in audit_actions


def test_turnstile_csp_is_added_when_password_reset_uses_turnstile(client: TestClient) -> None:
    """The reset page should render Turnstile and keep CSP scoped to Cloudflare."""

    reset_settings = _reset_settings(
        turnstile_enabled=True,
        turnstile_site_key="site-key",
        turnstile_secret_key="secret-key",
    )
    with TestClient(create_app(reset_settings)) as reset_client:
        response = reset_client.get("/forgot-password")

    assert response.status_code == 200
    assert "/static/password-reset.js?v=" in response.text
    assert (
        '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" defer '
        'data-turnstile-api-script data-turnstile-fallback-src="'
        'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"></script>'
    ) in response.text
    assert 'id="password-reset-turnstile"' in response.text
    assert "data-turnstile-widget" in response.text
    assert 'class="cf-turnstile"' not in response.text
    assert 'data-sitekey="site-key"' in response.text
    assert "Human verification is loading..." in response.text
    assert "data-password-reset-submit disabled" in response.text
    csp_header = response.headers["content-security-policy"]
    assert "script-src 'self' https://challenges.cloudflare.com" in csp_header
    assert "frame-src https://challenges.cloudflare.com" in csp_header
    assert "frame-ancestors 'none'" in csp_header


def test_turnstile_browser_event_logging_requires_csrf_and_sanitizes_details(caplog) -> None:
    """Browser-side Turnstile telemetry should be CSRF-protected and sanitized."""

    reset_settings = _reset_settings(
        turnstile_enabled=True,
        turnstile_site_key="site-key",
        turnstile_secret_key="secret-key",
    )
    with TestClient(create_app(reset_settings)) as reset_client:
        page_response = reset_client.get("/forgot-password")
        csrf_token = extract_csrf_token(page_response.text)

        missing_csrf_response = reset_client.post(
            "/forgot-password/turnstile-event",
            json={"event": "turnstile.api_script_error"},
        )
        assert missing_csrf_response.status_code == 403

        with caplog.at_level(logging.DEBUG, logger="job_logger.routes.password_reset"):
            response = reset_client.post(
                "/forgot-password/turnstile-event",
                headers={"X-CSRF-Token": csrf_token},
                json={
                    "event": "turnstile.api_script_error",
                    "details": {
                        "script_src": "https://challenges.cloudflare.com/turnstile/v0/api.js?token=secret",
                        "token": "raw-turnstile-token",
                        "token_length": 21,
                        "email": "tech@example.test",
                        "response_value": "raw-response",
                        "response_input_present": True,
                        "response_input_has_value": False,
                        "sitekey": "site-key",
                        "fallback_attempted": False,
                    },
                },
            )

    assert response.status_code == 204
    assert "Turnstile browser debug event=turnstile.api_script_error" in caplog.text
    assert "Turnstile browser event event=turnstile.api_script_error" in caplog.text
    assert "https://challenges.cloudflare.com/turnstile/v0/api.js" in caplog.text
    assert "fallback_attempted" in caplog.text
    assert "token_length" in caplog.text
    assert "response_input_present" in caplog.text
    assert "response_input_has_value" in caplog.text
    assert "raw-turnstile-token" not in caplog.text
    assert "tech@example.test" not in caplog.text
    assert "raw-response" not in caplog.text
    assert "site-key" not in caplog.text
