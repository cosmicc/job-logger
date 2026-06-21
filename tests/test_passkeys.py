"""Tests for managed web-user passkey registration and login."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse

from job_logger import database
from job_logger.config import settings
from job_logger.models import AuditEvent, WebAuthnCredential, WebUser
from job_logger.security import (
    SESSION_AUTHENTICATED_AT_UTC_KEY,
    SESSION_USERNAME_KEY,
    authenticated_session_is_expired,
)
from tests.conftest import TEST_WEB_USER_PASSWORD, extract_csrf_token, login_as, login_as_web_user


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
        "job_logger.services.passkeys.verify_registration_response",
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


def test_login_page_exposes_password_fallback_and_passkey_button(client: TestClient) -> None:
    """The login page should keep password login while offering passkey login."""

    response = client.get("/login")

    assert response.status_code == 200
    assert 'action="/login"' in response.text
    assert "Use passkey" in response.text
    assert "data-passkey-login-button" in response.text
    assert "/static/passkeys.js" in response.text


def test_config_can_register_and_delete_passkey(client: TestClient, monkeypatch) -> None:
    """A managed web user can add and remove a passkey from Config."""

    credential = _register_mock_passkey(client, monkeypatch)

    config_response = client.get("/config")
    assert "Passkeys" in config_response.text
    assert "data-passkey-register-button" in config_response.text
    assert "Synced passkey" in config_response.text
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
    """Password login should ask once per login when the user has no passkeys."""

    login_as_web_user(client)
    home_response = client.get("/home")
    assert home_response.status_code == 200
    assert "Set up faster sign-in" in home_response.text
    assert "data-passkey-register-button" in home_response.text

    repeated_home_response = client.get("/home")
    assert "Set up faster sign-in" not in repeated_home_response.text
    assert "data-passkey-register-button" not in repeated_home_response.text

    login_as_web_user(client)
    next_login_home_response = client.get("/home")
    assert "Set up faster sign-in" in next_login_home_response.text

    _register_mock_passkey(client, monkeypatch, credential_id=b"credential-two")
    updated_home_response = client.get("/home")
    assert "Set up faster sign-in" not in updated_home_response.text

    login_as_web_user(client)
    later_login_home_response = client.get("/home")
    assert "Set up faster sign-in" not in later_login_home_response.text


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
        "job_logger.services.passkeys.verify_authentication_response",
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
    assert verify_response.json()["redirect_url"] == "/home"
    assert client.get("/home").status_code == 200
    success_log_lines = Path(os.environ["LOGIN_SUCCESS_LOG_PATH"]).read_text(encoding="utf-8").strip().splitlines()
    success_log_payload = json.loads(success_log_lines[-1])
    assert success_log_payload["username"] == "tech"
    assert success_log_payload["authentication_method"] == "passkey"
    with database.SessionLocal() as database_session:
        updated_credential = database_session.get(WebAuthnCredential, credential.id)
        assert updated_credential is not None
        assert updated_credential.sign_count == 12
        assert updated_credential.last_used_at_utc is not None
        actions = list(database_session.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at_utc)))
        assert "auth.passkey.login.succeeded" in actions


def test_failed_passkey_login_keeps_password_fallback(client: TestClient, monkeypatch) -> None:
    """A failed passkey assertion should not block normal password login."""

    _register_mock_passkey(client, monkeypatch)
    client.cookies.clear()
    login_response = client.get("/login")
    csrf_token = extract_csrf_token(login_response.text)
    client.post("/login/passkey/options", headers={"X-CSRF-Token": csrf_token}, json={})

    def reject_authentication(**_):
        raise InvalidAuthenticationResponse("bad signature")

    monkeypatch.setattr("job_logger.services.passkeys.verify_authentication_response", reject_authentication)
    verify_response = client.post(
        "/login/passkey/verify",
        headers={"X-CSRF-Token": csrf_token},
        json=_passkey_payload(),
    )

    assert verify_response.status_code == 400
    assert verify_response.json()["fallback"] == "password"
    assert client.get("/home", follow_redirects=False).status_code == 303

    login_as(client, username="tech", password=TEST_WEB_USER_PASSWORD)
    assert client.get("/home").status_code == 200
    with database.SessionLocal() as database_session:
        actions = list(database_session.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at_utc)))
        assert "auth.passkey.login.failed" in actions


def test_disabled_user_cannot_login_with_passkey(client: TestClient, monkeypatch) -> None:
    """Disabled managed users should be blocked even with an existing passkey."""

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
    assert "disabled" in verify_response.json()["detail"].lower()
