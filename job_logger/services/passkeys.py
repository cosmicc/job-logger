"""WebAuthn passkey registration and authentication helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json_dict
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from job_logger.config import Settings, settings
from job_logger.logging_config import redact_sensitive_text
from job_logger.models import WebAuthnCredential, WebUser, utc_now

LOGGER = logging.getLogger(__name__)
SESSION_PASSKEY_REGISTRATION_CHALLENGE_KEY = "passkey_registration_challenge"
SESSION_PASSKEY_REGISTRATION_USER_ID_KEY = "passkey_registration_user_id"
SESSION_PASSKEY_AUTHENTICATION_CHALLENGE_KEY = "passkey_authentication_challenge"
MAX_TRANSPORTS_STORED = 12
MAX_TRANSPORT_LENGTH = 40
MAX_USER_AGENT_LENGTH = 255


class PasskeyError(RuntimeError):
    """Raised when a passkey operation cannot be completed safely."""

    def __init__(self, message: str, *, reason: str = "passkey_error") -> None:
        """Store a safe operator-facing reason without exposing credential data."""

        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class PasskeyAuthenticationResult:
    """Result returned after a successful passkey assertion."""

    web_user: WebUser
    credential: WebAuthnCredential


def _bounded_user_agent(request: Request) -> str | None:
    """Return a short user-agent string for passkey device management."""

    user_agent = request.headers.get("user-agent")
    if not user_agent:
        return None
    return user_agent[:MAX_USER_AGENT_LENGTH]


def _safe_request_header(request: Request, header_name: str, max_length: int = 255) -> str:
    """Return a bounded request header value for passkey diagnostics."""

    return redact_sensitive_text(str(request.headers.get(header_name, "")))[:max_length]


def _request_host(request: Request) -> str:
    """Return the hostname used for the current request."""

    if request.url.hostname:
        return request.url.hostname

    host_header = request.headers.get("host", "").split(":", maxsplit=1)[0].strip()
    if host_header:
        return host_header

    raise PasskeyError("Passkey setup needs a valid request host.")


def _is_local_development_host(hostname: str) -> bool:
    """Return whether HTTP is a reasonable WebAuthn origin for this host."""

    return hostname in {"localhost", "127.0.0.1", "::1", "testserver"}


def webauthn_rp_id_for_request(request: Request, application_settings: Settings = settings) -> str:
    """Return the relying-party ID expected by browser passkey APIs."""

    if application_settings.webauthn_rp_id:
        return application_settings.webauthn_rp_id
    return _request_host(request)


def webauthn_origin_for_request(request: Request, application_settings: Settings = settings) -> str:
    """Return the expected browser origin used for passkey verification."""

    if application_settings.webauthn_origin:
        parsed_origin = urlsplit(application_settings.webauthn_origin)
        if not parsed_origin.scheme or not parsed_origin.netloc or parsed_origin.path not in {"", "/"}:
            raise PasskeyError("WEBAUTHN_ORIGIN must be a scheme and host, such as https://logger.example.com.")
        return f"{parsed_origin.scheme}://{parsed_origin.netloc}"

    return f"{request.url.scheme}://{request.url.netloc}"


def _passkey_verification_error(
    *,
    exc: WebAuthnException,
    request: Request,
    application_settings: Settings,
    operation: str,
    default_message: str,
    default_reason: str,
) -> PasskeyError:
    """Return a safe passkey error while logging bounded origin diagnostics."""

    expected_origin = ""
    rp_id = ""
    try:
        expected_origin = webauthn_origin_for_request(request, application_settings)
        rp_id = webauthn_rp_id_for_request(request, application_settings)
    except PasskeyError:
        pass

    request_host = _request_host(request)
    LOGGER.warning(
        "Passkey %s verification failed: exception=%s expected_origin=%s rp_id=%s host=%s request_scheme=%s forwarded_proto=%s forwarded_host=%s",
        operation,
        type(exc).__name__,
        redact_sensitive_text(expected_origin)[:255],
        redact_sensitive_text(rp_id)[:255],
        redact_sensitive_text(request_host)[:255],
        redact_sensitive_text(request.url.scheme)[:32],
        _safe_request_header(request, "x-forwarded-proto", 64),
        _safe_request_header(request, "x-forwarded-host", 255),
    )

    if (
        not application_settings.webauthn_origin
        and expected_origin.startswith("http://")
        and not _is_local_development_host(request_host)
    ):
        if operation == "authentication":
            return PasskeyError(
                "Passkey login failed because the app expected an HTTP origin. "
                "Use your password this time, then restart the nginx/app containers so forwarded HTTPS headers are applied "
                "or set WEBAUTHN_ORIGIN to the public HTTPS URL.",
                reason="origin_scheme_mismatch",
            )
        return PasskeyError(
            "Passkey setup failed because the app expected an HTTP origin. "
            "Restart the nginx/app containers so forwarded HTTPS headers are applied, "
            "or set WEBAUTHN_ORIGIN to the public HTTPS URL.",
            reason="origin_scheme_mismatch",
        )

    return PasskeyError(default_message, reason=default_reason)


def _credential_descriptors(credentials: list[WebAuthnCredential]) -> list[PublicKeyCredentialDescriptor]:
    """Return descriptors for credentials already registered to a user."""

    return [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(credential.credential_id))
        for credential in credentials
    ]


def _set_registration_challenge(request: Request, *, challenge: bytes, web_user_id: str) -> None:
    """Store the one-time passkey registration challenge in the signed session."""

    request.session[SESSION_PASSKEY_REGISTRATION_CHALLENGE_KEY] = bytes_to_base64url(challenge)
    request.session[SESSION_PASSKEY_REGISTRATION_USER_ID_KEY] = web_user_id


def _pop_registration_challenge(request: Request, *, web_user_id: str) -> bytes:
    """Return and clear the pending registration challenge for this user."""

    encoded_challenge = request.session.pop(SESSION_PASSKEY_REGISTRATION_CHALLENGE_KEY, None)
    challenge_user_id = request.session.pop(SESSION_PASSKEY_REGISTRATION_USER_ID_KEY, None)
    if challenge_user_id != web_user_id or not isinstance(encoded_challenge, str):
        raise PasskeyError("Passkey setup expired. Try again.")

    try:
        return base64url_to_bytes(encoded_challenge)
    except ValueError as exc:
        raise PasskeyError("Passkey setup expired. Try again.") from exc


def _set_authentication_challenge(request: Request, *, challenge: bytes) -> None:
    """Store the one-time passkey authentication challenge in the signed session."""

    request.session[SESSION_PASSKEY_AUTHENTICATION_CHALLENGE_KEY] = bytes_to_base64url(challenge)


def _pop_authentication_challenge(request: Request) -> bytes:
    """Return and clear the pending authentication challenge."""

    encoded_challenge = request.session.pop(SESSION_PASSKEY_AUTHENTICATION_CHALLENGE_KEY, None)
    if not isinstance(encoded_challenge, str):
        raise PasskeyError("Passkey login expired. Try again or use your password.")

    try:
        return base64url_to_bytes(encoded_challenge)
    except ValueError as exc:
        raise PasskeyError("Passkey login expired. Try again or use your password.") from exc


def _safe_transports(raw_transports: object) -> list[str] | None:
    """Return bounded browser-reported transports for credential hints."""

    if not isinstance(raw_transports, list):
        return None

    safe_transports: list[str] = []
    for raw_transport in raw_transports[:MAX_TRANSPORTS_STORED]:
        transport = str(raw_transport).strip().lower()
        if not transport or len(transport) > MAX_TRANSPORT_LENGTH:
            continue
        safe_transports.append(transport)
    return safe_transports or None


def _credential_id_from_payload(payload: dict[str, object]) -> str:
    """Return the browser credential ID from an authentication response."""

    raw_id = payload.get("rawId") or payload.get("id")
    if not isinstance(raw_id, str) or not raw_id:
        raise PasskeyError("Passkey response did not include a credential ID.")
    return raw_id


def list_passkey_credentials_for_user(database_session: Session, web_user_id: str) -> list[WebAuthnCredential]:
    """Return registered passkeys for one managed web user."""

    return list(
        database_session.scalars(
            select(WebAuthnCredential)
            .where(WebAuthnCredential.web_user_id == web_user_id)
            .order_by(WebAuthnCredential.created_at_utc.desc())
        )
    )


def passkey_credential_count_for_user(database_session: Session, web_user_id: str) -> int:
    """Return the number of passkeys registered to one managed web user."""

    return len(list_passkey_credentials_for_user(database_session, web_user_id))


def begin_passkey_registration(
    database_session: Session,
    request: Request,
    web_user: WebUser,
    application_settings: Settings = settings,
) -> dict[str, object]:
    """Create browser options for registering a new passkey."""

    existing_credentials = list_passkey_credentials_for_user(database_session, web_user.id)
    options = generate_registration_options(
        rp_id=webauthn_rp_id_for_request(request, application_settings),
        rp_name=application_settings.webauthn_rp_name,
        user_name=web_user.username,
        user_id=web_user.id.encode("utf-8"),
        user_display_name=web_user.full_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=_credential_descriptors(existing_credentials),
    )
    _set_registration_challenge(request, challenge=options.challenge, web_user_id=web_user.id)
    return options_to_json_dict(options)


def finish_passkey_registration(
    database_session: Session,
    request: Request,
    web_user: WebUser,
    credential_payload: dict[str, object],
    application_settings: Settings = settings,
) -> WebAuthnCredential:
    """Verify a browser-created passkey and store its public credential data."""

    challenge = _pop_registration_challenge(request, web_user_id=web_user.id)
    try:
        verified_registration = verify_registration_response(
            credential=credential_payload,
            expected_challenge=challenge,
            expected_rp_id=webauthn_rp_id_for_request(request, application_settings),
            expected_origin=webauthn_origin_for_request(request, application_settings),
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        raise _passkey_verification_error(
            exc=exc,
            request=request,
            application_settings=application_settings,
            operation="registration",
            default_message="Passkey setup failed. Try again.",
            default_reason="registration_verification_failed",
        ) from exc

    credential_id = bytes_to_base64url(verified_registration.credential_id)
    existing_credential = database_session.scalar(
        select(WebAuthnCredential).where(WebAuthnCredential.credential_id == credential_id)
    )
    if existing_credential is not None:
        raise PasskeyError("This passkey is already registered.")

    response_payload = credential_payload.get("response")
    transports = _safe_transports(response_payload.get("transports") if isinstance(response_payload, dict) else None)
    credential = WebAuthnCredential(
        web_user_id=web_user.id,
        credential_id=credential_id,
        credential_public_key=bytes_to_base64url(verified_registration.credential_public_key),
        sign_count=verified_registration.sign_count,
        aaguid=verified_registration.aaguid,
        credential_type=str(verified_registration.credential_type.value),
        device_type=str(verified_registration.credential_device_type.value),
        backed_up=bool(verified_registration.credential_backed_up),
        transports=transports,
        user_agent=_bounded_user_agent(request),
        created_at_utc=utc_now(),
    )
    database_session.add(credential)
    database_session.flush()
    return credential


def delete_passkey_credential(
    database_session: Session,
    *,
    web_user_id: str,
    credential_row_id: str,
) -> WebAuthnCredential:
    """Delete one passkey credential owned by the current managed web user."""

    credential = database_session.get(WebAuthnCredential, credential_row_id)
    if credential is None or credential.web_user_id != web_user_id:
        raise PasskeyError("Passkey was not found.")

    database_session.delete(credential)
    database_session.flush()
    return credential


def begin_passkey_authentication(
    request: Request,
    application_settings: Settings = settings,
) -> dict[str, object]:
    """Create browser options for passkey login."""

    options = generate_authentication_options(
        rp_id=webauthn_rp_id_for_request(request, application_settings),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _set_authentication_challenge(request, challenge=options.challenge)
    return options_to_json_dict(options)


def finish_passkey_authentication(
    database_session: Session,
    request: Request,
    credential_payload: dict[str, object],
    application_settings: Settings = settings,
) -> PasskeyAuthenticationResult:
    """Verify a passkey assertion and return the owning enabled web user."""

    challenge = _pop_authentication_challenge(request)
    credential_id = _credential_id_from_payload(credential_payload)
    credential = database_session.scalar(
        select(WebAuthnCredential).where(WebAuthnCredential.credential_id == credential_id)
    )
    if credential is None:
        raise PasskeyError("Passkey login failed. Use your password instead.")

    if credential.web_user.disabled:
        raise PasskeyError("This user account is disabled.")

    try:
        verified_authentication = verify_authentication_response(
            credential=credential_payload,
            expected_challenge=challenge,
            expected_rp_id=webauthn_rp_id_for_request(request, application_settings),
            expected_origin=webauthn_origin_for_request(request, application_settings),
            credential_public_key=base64url_to_bytes(credential.credential_public_key),
            credential_current_sign_count=credential.sign_count,
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        raise _passkey_verification_error(
            exc=exc,
            request=request,
            application_settings=application_settings,
            operation="authentication",
            default_message="Passkey login failed. Use your password instead.",
            default_reason="authentication_verification_failed",
        ) from exc

    credential.sign_count = verified_authentication.new_sign_count
    credential.device_type = str(verified_authentication.credential_device_type.value)
    credential.backed_up = bool(verified_authentication.credential_backed_up)
    credential.last_used_at_utc = utc_now()
    database_session.flush()
    return PasskeyAuthenticationResult(web_user=credential.web_user, credential=credential)
