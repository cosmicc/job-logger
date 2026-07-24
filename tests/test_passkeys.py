"""Tests for managed web-user passkey registration and login."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse

from tests.conftest import TEST_WEB_USER_PASSWORD, extract_csrf_token, login_as, login_as_web_user
from ticket_pilot import database
from ticket_pilot.config import settings
from ticket_pilot.models import AuditEvent, LoginAttempt, WebAuthnCredential, WebUser
from ticket_pilot.security import (
    PUBLIC_DEVICE_IDLE_TIMEOUT_SECONDS,
    SESSION_AUTHENTICATED_AT_UTC_KEY,
    SESSION_PUBLIC_DEVICE_KEY,
    SESSION_PUBLIC_DEVICE_LAST_ACTIVITY_UTC_KEY,
    SESSION_USERNAME_KEY,
    authenticated_session_is_expired,
    public_device_session_is_idle_expired,
)
from ticket_pilot.version import APP_VERSION


@dataclass(frozen=True)
class FakeVerifiedRegistration:
    """Minimal py_webauthn registration result used by route tests."""

    credential_id: bytes
    credential_public_key: bytes
    sign_count: int
    aaguid: str
    credential_type: object
    credential_device_type: object
    credential_backed_up: bool


@dataclass(frozen=True)
class FakeVerifiedAuthentication:
    """Minimal py_webauthn authentication result used by route tests."""

    credential_id: bytes
    new_sign_count: int
    credential_device_type: object
    credential_backed_up: bool


def _passkey_payload(credential_id: bytes = b"credential-one") -> dict[str, object]:
    """Return a browser-shaped passkey response payload for mocked verification."""

    encoded_credential_id = bytes_to_base64url(credential_id)
    return {
        "id": encoded_credential_id,
        "rawId": encoded_credential_id,
        "type": "public-key",
        "authenticatorAttachment": "platform",
        "response": {
            "clientDataJSON": bytes_to_base64url(b"client-data"),
            "attestationObject": bytes_to_base64url(b"attestation"),
            "authenticatorData": bytes_to_base64url(b"authenticator-data"),
            "signature": bytes_to_base64url(b"signature"),
            "userHandle": bytes_to_base64url(b"user-handle"),
            "transports": ["internal", "hybrid"],
        },
    }


def _register_mock_passkey(
    client: TestClient,
    monkeypatch,
    *,
    credential_id: bytes = b"credential-one",
) -> WebAuthnCredential:
    """Register a passkey through app routes with mocked crypto verification."""

    login_as_web_user(client)
    config_response = client.get("/config")
    csrf_token = extract_csrf_token(config_response.text)
    options_response = client.post(
        "/config/passkeys/options",
        headers={"X-CSRF-Token": csrf_token},
        json={},
    )
    assert options_response.status_code == 200

    monkeypatch.setattr(
        "ticket_pilot.services.passkeys.verify_registration_response",
        lambda **_: FakeVerifiedRegistration(
            credential_id=credential_id,
            credential_public_key=b"public-key",
            sign_count=7,
            aaguid="00000000-0000-0000-0000-000000000000",
            credential_type=SimpleNamespace(value="public-key"),
            credential_device_type=SimpleNamespace(value="multi_device"),
            credential_backed_up=True,
        ),
    )
    verify_response = client.post(
        "/config/passkeys/verify",
        headers={"X-CSRF-Token": csrf_token},
        json=_passkey_payload(credential_id),
    )
    assert verify_response.status_code == 200

    with database.SessionLocal() as database_session:
        credential = database_session.scalar(select(WebAuthnCredential))
        assert credential is not None
        database_session.expunge(credential)
        return credential


def test_session_timeout_uses_configured_hours() -> None:
    """Authenticated sessions should expire after the configured hour window."""

    current_time = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
    short_timeout_settings = replace(settings, session_timeout_hours=1.0)
    expired_session = {
        SESSION_USERNAME_KEY: "tech",
        SESSION_AUTHENTICATED_AT_UTC_KEY: (current_time - timedelta(hours=2)).isoformat(),
    }
    active_session = {
        SESSION_USERNAME_KEY: "tech",
        SESSION_AUTHENTICATED_AT_UTC_KEY: (current_time - timedelta(minutes=30)).isoformat(),
    }

    assert authenticated_session_is_expired(expired_session, short_timeout_settings, now=current_time) is True
    assert authenticated_session_is_expired(active_session, short_timeout_settings, now=current_time) is False


def test_public_device_session_uses_short_idle_timeout() -> None:
    """Public-device sessions should expire after 15 minutes of inactivity."""

    current_time = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
    active_public_session = {
        SESSION_USERNAME_KEY: "tech",
        SESSION_AUTHENTICATED_AT_UTC_KEY: (current_time - timedelta(hours=2)).isoformat(),
        SESSION_PUBLIC_DEVICE_KEY: True,
        SESSION_PUBLIC_DEVICE_LAST_ACTIVITY_UTC_KEY: (
            current_time - timedelta(seconds=PUBLIC_DEVICE_IDLE_TIMEOUT_SECONDS - 1)
        ).isoformat(),
    }
    expired_public_session = {
        SESSION_USERNAME_KEY: "tech",
        SESSION_AUTHENTICATED_AT_UTC_KEY: current_time.isoformat(),
        SESSION_PUBLIC_DEVICE_KEY: True,
        SESSION_PUBLIC_DEVICE_LAST_ACTIVITY_UTC_KEY: (
            current_time - timedelta(seconds=PUBLIC_DEVICE_IDLE_TIMEOUT_SECONDS)
        ).isoformat(),
    }
    private_session = {
        SESSION_USERNAME_KEY: "tech",
        SESSION_AUTHENTICATED_AT_UTC_KEY: current_time.isoformat(),
        SESSION_PUBLIC_DEVICE_LAST_ACTIVITY_UTC_KEY: (
            current_time - timedelta(seconds=PUBLIC_DEVICE_IDLE_TIMEOUT_SECONDS + 1)
        ).isoformat(),
    }

    assert public_device_session_is_idle_expired(active_public_session, now=current_time) is False
    assert public_device_session_is_idle_expired(expired_public_session, now=current_time) is True
    assert public_device_session_is_idle_expired(private_session, now=current_time) is False


def test_login_page_exposes_password_fallback_and_passkey_button(client: TestClient) -> None:
    """The login page should keep password login while offering passkey login."""

    response = client.get("/login")

    assert response.status_code == 200
    assert 'action="/login"' in response.text
    assert "Use device sign-in" in response.text
    assert "data-passkey-login-button" in response.text
    assert 'name="public_device"' in response.text
    assert 'type="checkbox"' in response.text
    assert 'value="1"' in response.text
    assert "data-public-device-login" in response.text
    assert "This is a public device" in response.text
    assert "Public device sessions expire after 15 minutes of inactivity" in response.text
    assert "public-device-login-help" not in response.text
    assert 'title="Public device sessions expire after 15 minutes of inactivity' in response.text
    assert "/static/passkeys.js" in response.text
    assert "<h1>Sign in</h1>" not in response.text
    assert "Use the local app account configured for this deployment." not in response.text
    assert response.text.index('type="submit"') < response.text.index("data-passkey-login-panel")
    assert "login-brand" not in response.text
    assert f'<p class="login-version-label">v{APP_VERSION}</p>' in response.text
    assert f"v{APP_VERSION}-DEV" not in response.text
    assert '<header class="app-header' not in response.text
    assert 'aria-label="TicketPilot home"' not in response.text

    repository_root = Path(__file__).resolve().parents[1]
    passkeys_script = (repository_root / "ticket_pilot" / "static" / "passkeys.js").read_text(encoding="utf-8")
    stylesheet = (repository_root / "ticket_pilot" / "static" / "app.css").read_text(encoding="utf-8")
    assert "function initializePublicDeviceLoginToggle(button)" in passkeys_script
    assert 'checkbox.addEventListener("change", updateButtonState);' in passkeys_script
    assert "button.disabled = publicDeviceSelected;" in passkeys_script
    assert "passkey-login-public-disabled" in passkeys_script
    assert "Device sign-in is unavailable when public-device mode is selected." in passkeys_script
    assert ".passkey-login-panel .secondary-button:disabled,\n.passkey-login-panel .secondary-button.passkey-login-public-disabled" in stylesheet


def test_login_page_marks_dev_build_version(client: TestClient) -> None:
    """DEV_BUILD should append DEV to the tiny login-page version label."""

    client.app.state.application_settings = replace(client.app.state.application_settings, dev_build=True)

    response = client.get("/login")

    assert response.status_code == 200
    assert f'<p class="login-version-label">v{APP_VERSION}-DEV</p>' in response.text


def test_login_version_label_uses_small_close_spacing() -> None:
    """The login version label should stay visually small and close to the card."""

    stylesheet = (Path(__file__).resolve().parents[1] / "ticket_pilot" / "static" / "app.css").read_text(
        encoding="utf-8"
    )

    assert "grid-auto-rows: max-content;" in stylesheet
    assert "align-content: start;" in stylesheet
    assert "row-gap: 6px;" in stylesheet
    assert ".login-version-label" in stylesheet
    assert "margin: 0;" in stylesheet
    assert "font-size: 10px;" in stylesheet
    assert "line-height: 1;" in stylesheet


def test_config_can_register_and_delete_passkey(client: TestClient, monkeypatch) -> None:
    """A managed web user can add and remove a passkey from Config."""

    credential = _register_mock_passkey(client, monkeypatch)

    config_response = client.get("/config")
    assert "Device sign-in" in config_response.text
    assert "data-passkey-register-button" in config_response.text
    assert "Synced sign-in" in config_response.text
    assert "Backed up" in config_response.text
    assert f"/config/passkeys/{credential.id}/delete" in config_response.text

    csrf_token = extract_csrf_token(config_response.text)
    delete_response = client.post(
        f"/config/passkeys/{credential.id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/config#passkeys"
    with database.SessionLocal() as database_session:
        assert database_session.scalar(select(WebAuthnCredential)) is None
        actions = list(database_session.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at_utc)))
        assert "auth.passkey.registered" in actions
        assert "auth.passkey.deleted" in actions


def test_home_prompts_for_passkey_once_per_login_until_one_is_registered(client: TestClient, monkeypatch) -> None:
    """Password login should keep a phone-only prompt until the mobile UI marks it seen."""

    login_as_web_user(client)
    home_response = client.get("/work")
    assert home_response.status_code == 200
    assert "Set up faster sign-in" in home_response.text
    assert "phone-only-passkey-home-prompt" in home_response.text
    assert "data-mobile-passkey-prompt" in home_response.text
    assert "data-passkey-register-button" in home_response.text

    repeated_home_response = client.get("/work")
    assert "Set up faster sign-in" in repeated_home_response.text

    csrf_token = extract_csrf_token(home_response.text)
    seen_response = client.post(
        "/config/device-sign-in-prompt/seen",
        headers={"X-CSRF-Token": csrf_token},
        json={},
        follow_redirects=False,
    )
    assert seen_response.status_code == 200
    assert seen_response.json()["seen"] is True

    dismissed_home_response = client.get("/work")
    assert "Set up faster sign-in" not in dismissed_home_response.text
    assert "data-passkey-register-button" not in dismissed_home_response.text

    login_as_web_user(client)
    next_login_home_response = client.get("/work")
    assert "Set up faster sign-in" in next_login_home_response.text
    stylesheet = (Path(__file__).resolve().parents[1] / "ticket_pilot" / "static" / "app.css").read_text(encoding="utf-8")
    phone_stylesheet = (Path(__file__).resolve().parents[1] / "ticket_pilot" / "static" / "phone.css").read_text(encoding="utf-8")
    assert ".phone-only-passkey-home-prompt {\n  display: none;" in stylesheet
    assert ".phone-only-passkey-home-prompt {\n  display: block;" in phone_stylesheet

    _register_mock_passkey(client, monkeypatch, credential_id=b"credential-two")
    updated_home_response = client.get("/work")
    assert "Set up faster sign-in" not in updated_home_response.text

    login_as_web_user(client)
    later_login_home_response = client.get("/work")
    assert "Set up faster sign-in" not in later_login_home_response.text


def test_public_device_password_login_hides_passkey_setup(client: TestClient) -> None:
    """Public-device password sessions should not offer new Device sign-in setup."""

    login_response = client.get("/login")
    csrf_token = extract_csrf_token(login_response.text)
    sign_in_response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "username": "tech",
            "password": TEST_WEB_USER_PASSWORD,
            "public_device": "1",
        },
        follow_redirects=False,
    )
    assert sign_in_response.status_code == 303
    assert sign_in_response.headers["location"] == "/work"

    home_response = client.get("/work")
    assert home_response.status_code == 200
    assert "Set up faster sign-in" not in home_response.text
    assert "phone-only-passkey-home-prompt" not in home_response.text

    config_response = client.get("/config")
    assert config_response.status_code == 200
    assert "Device sign-in setup is unavailable while signed in on a public device." in config_response.text
    assert "data-passkey-register-button" not in config_response.text

    csrf_token = extract_csrf_token(config_response.text)
    setup_response = client.post(
        "/config/passkeys/options",
        headers={"X-CSRF-Token": csrf_token},
        json={},
    )
    assert setup_response.status_code == 403
    assert setup_response.json()["detail"] == "Device sign-in setup is unavailable on public devices."


def test_passkey_login_creates_managed_user_session(client: TestClient, monkeypatch) -> None:
    """A verified passkey assertion should sign in the owning enabled web user."""

    credential = _register_mock_passkey(client, monkeypatch)
    client.cookies.clear()
    login_response = client.get("/login")
    csrf_token = extract_csrf_token(login_response.text)
    options_response = client.post(
        "/login/passkey/options",
        headers={"X-CSRF-Token": csrf_token},
        json={},
    )
    assert options_response.status_code == 200
    assert options_response.json()["publicKey"]["rpId"] == "testserver"

    monkeypatch.setattr(
        "ticket_pilot.services.passkeys.verify_authentication_response",
        lambda **_: FakeVerifiedAuthentication(
            credential_id=b"credential-one",
            new_sign_count=12,
            credential_device_type=SimpleNamespace(value="multi_device"),
            credential_backed_up=True,
        ),
    )
    verify_response = client.post(
        "/login/passkey/verify",
        headers={"X-CSRF-Token": csrf_token},
        json=_passkey_payload(),
    )

    assert verify_response.status_code == 200
    assert verify_response.json()["redirect_url"] == "/work"
    assert client.get("/work").status_code == 200
    with database.SessionLocal() as database_session:
        success_attempt = database_session.scalar(
            select(LoginAttempt).where(
                LoginAttempt.succeeded.is_(True),
                LoginAttempt.authentication_method == "passkey",
            )
        )
        assert success_attempt is not None
        assert success_attempt.username == "tech"
        assert success_attempt.authentication_method == "passkey"
        updated_credential = database_session.get(WebAuthnCredential, credential.id)
        assert updated_credential is not None
        assert updated_credential.sign_count == 12
        assert updated_credential.last_used_at_utc is not None
        web_user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert web_user is not None
        assert web_user.last_login_at_utc is not None
        actions = list(database_session.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at_utc)))
        assert "auth.passkey.login.succeeded" in actions


def test_public_device_passkey_login_hides_passkey_setup(client: TestClient, monkeypatch) -> None:
    """Public-device Device sign-in should create the same constrained session."""

    _register_mock_passkey(client, monkeypatch)
    client.cookies.clear()
    login_response = client.get("/login")
    csrf_token = extract_csrf_token(login_response.text)
    options_response = client.post(
        "/login/passkey/options",
        headers={"X-CSRF-Token": csrf_token},
        json={},
    )
    assert options_response.status_code == 200

    monkeypatch.setattr(
        "ticket_pilot.services.passkeys.verify_authentication_response",
        lambda **_: FakeVerifiedAuthentication(
            credential_id=b"credential-one",
            new_sign_count=12,
            credential_device_type=SimpleNamespace(value="multi_device"),
            credential_backed_up=True,
        ),
    )
    credential_payload = _passkey_payload()
    credential_payload["public_device"] = True
    verify_response = client.post(
        "/login/passkey/verify",
        headers={"X-CSRF-Token": csrf_token},
        json=credential_payload,
    )

    assert verify_response.status_code == 200
    assert client.get("/work").status_code == 200
    assert "Set up faster sign-in" not in client.get("/work").text
    config_response = client.get("/config")
    assert "Device sign-in setup is unavailable while signed in on a public device." in config_response.text
    with database.SessionLocal() as database_session:
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "auth.passkey.login.succeeded")
        )
        assert audit_event is not None
        assert audit_event.details["public_device"] is True


def test_failed_passkey_login_keeps_password_fallback(client: TestClient, monkeypatch) -> None:
    """A failed passkey assertion should not block normal password login."""

    _register_mock_passkey(client, monkeypatch)
    client.cookies.clear()
    login_response = client.get("/login")
    csrf_token = extract_csrf_token(login_response.text)
    client.post("/login/passkey/options", headers={"X-CSRF-Token": csrf_token}, json={})

    def reject_authentication(**_):
        raise InvalidAuthenticationResponse("bad signature")

    monkeypatch.setattr("ticket_pilot.services.passkeys.verify_authentication_response", reject_authentication)
    verify_response = client.post(
        "/login/passkey/verify",
        headers={"X-CSRF-Token": csrf_token},
        json=_passkey_payload(),
    )

    assert verify_response.status_code == 400
    assert verify_response.json()["fallback"] == "password"
    assert client.get("/work", follow_redirects=False).status_code == 303

    login_as(client, username="tech", password=TEST_WEB_USER_PASSWORD)
    assert client.get("/work").status_code == 200
    with database.SessionLocal() as database_session:
        actions = list(database_session.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at_utc)))
        assert "auth.passkey.login.failed" in actions


def test_disabled_user_cannot_login_with_passkey(client: TestClient, monkeypatch) -> None:
    """Disabled managed users should be blocked even with an existing passkey."""

    client.app.state.application_settings = replace(
        client.app.state.application_settings,
        admin_contact_email="admin@example.test",
    )
    _register_mock_passkey(client, monkeypatch)
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.disabled = True
        database_session.commit()

    client.cookies.clear()
    login_response = client.get("/login")
    csrf_token = extract_csrf_token(login_response.text)
    client.post("/login/passkey/options", headers={"X-CSRF-Token": csrf_token}, json={})
    verify_response = client.post(
        "/login/passkey/verify",
        headers={"X-CSRF-Token": csrf_token},
        json=_passkey_payload(),
    )

    assert verify_response.status_code == 400
    assert verify_response.json()["detail"] == "Your account is disabled, please contact admin@example.test"
