"""Authentication, CSRF, and safe logging helpers."""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from job_logger.config import Settings, settings
from job_logger.models import WebUser

# Session keys are intentionally centralized to avoid typo-driven auth bugs.
SESSION_USERNAME_KEY = "authenticated_username"
SESSION_USER_KIND_KEY = "authenticated_user_kind"
SESSION_WEB_USER_ID_KEY = "authenticated_web_user_id"
SESSION_AUTHENTICATED_AT_UTC_KEY = "authenticated_at_utc"
SESSION_AUTH_METHOD_KEY = "authenticated_method"
SESSION_CSRF_TOKEN_KEY = "csrf_token"
SESSION_FLASH_KEY = "flash_messages"
SESSION_SHOW_PASSKEY_SETUP_PROMPT_KEY = "show_passkey_setup_prompt"
SUPER_ADMIN_SESSION_KIND = "super_admin"
WEB_USER_SESSION_KIND = "web_user"
PASSWORD_AUTH_METHOD = "password"
PASSKEY_AUTH_METHOD = "passkey"

# Sensitive audit keys are redacted before being written to logs or JSON snapshots.
SENSITIVE_KEY_FRAGMENTS = ("password", "secret", "token", "key", "authorization", "cookie")


def verify_password(plain_text_password: str, application_settings: Settings = settings) -> bool:
    """Verify the submitted password against the configured super-admin password."""

    if application_settings.app_password:
        return hmac.compare_digest(application_settings.app_password, plain_text_password)

    # The development default makes the app usable before secrets are configured.
    return hmac.compare_digest("admin", plain_text_password)


def authenticate_username(username: str, application_settings: Settings = settings) -> bool:
    """Validate the submitted username against the configured super admin."""

    return hmac.compare_digest(application_settings.app_username, username)


def login_session(request: Request, username: str) -> None:
    """Create an authenticated super-admin session."""

    request.session.clear()
    request.session[SESSION_USERNAME_KEY] = username
    request.session[SESSION_USER_KIND_KEY] = SUPER_ADMIN_SESSION_KIND
    request.session[SESSION_AUTHENTICATED_AT_UTC_KEY] = datetime.now(UTC).isoformat()
    request.session[SESSION_AUTH_METHOD_KEY] = PASSWORD_AUTH_METHOD
    request.session[SESSION_CSRF_TOKEN_KEY] = secrets.token_urlsafe(32)


def login_web_user_session(
    request: Request,
    *,
    username: str,
    web_user_id: str,
    authentication_method: str = PASSWORD_AUTH_METHOD,
) -> None:
    """Create an authenticated managed web-user session."""

    request.session.clear()
    request.session[SESSION_USERNAME_KEY] = username
    request.session[SESSION_USER_KIND_KEY] = WEB_USER_SESSION_KIND
    request.session[SESSION_WEB_USER_ID_KEY] = web_user_id
    request.session[SESSION_AUTHENTICATED_AT_UTC_KEY] = datetime.now(UTC).isoformat()
    request.session[SESSION_AUTH_METHOD_KEY] = authentication_method
    request.session[SESSION_SHOW_PASSKEY_SETUP_PROMPT_KEY] = True
    request.session[SESSION_CSRF_TOKEN_KEY] = secrets.token_urlsafe(32)


def logout_session(request: Request) -> None:
    """Clear all server-signed session state."""

    request.session.clear()


def current_username_from_session(session: Mapping[str, Any]) -> str | None:
    """Return the authenticated local app username stored in session data."""

    username = session.get(SESSION_USERNAME_KEY)
    if isinstance(username, str) and username:
        return username

    return None


def current_user_kind_from_session(
    session: Mapping[str, Any],
    application_settings: Settings = settings,
) -> str | None:
    """Return whether the current session is super admin or managed web user."""

    user_kind = session.get(SESSION_USER_KIND_KEY)
    if user_kind in {SUPER_ADMIN_SESSION_KIND, WEB_USER_SESSION_KIND}:
        return str(user_kind)

    # Older signed sessions did not carry a user kind. Treat an existing config
    # account session as super admin so operators are not forced out on deploy.
    username = current_username_from_session(session)
    if username is not None and hmac.compare_digest(username, application_settings.app_username):
        return SUPER_ADMIN_SESSION_KIND

    return None


def current_web_user_id_from_session(session: Mapping[str, Any]) -> str | None:
    """Return the managed web-user UUID from session data, if present."""

    user_id = session.get(SESSION_WEB_USER_ID_KEY)
    if isinstance(user_id, str) and user_id:
        return user_id

    return None


def current_authentication_method_from_session(session: Mapping[str, Any]) -> str | None:
    """Return the method used to create the current login session."""

    authentication_method = session.get(SESSION_AUTH_METHOD_KEY)
    if authentication_method in {PASSWORD_AUTH_METHOD, PASSKEY_AUTH_METHOD}:
        return str(authentication_method)
    return None


def authenticated_at_utc_from_session(session: Mapping[str, Any]) -> datetime | None:
    """Return the UTC login timestamp stored in an authenticated session."""

    raw_authenticated_at = session.get(SESSION_AUTHENTICATED_AT_UTC_KEY)
    if not isinstance(raw_authenticated_at, str) or not raw_authenticated_at:
        return None

    try:
        authenticated_at = datetime.fromisoformat(raw_authenticated_at.replace("Z", "+00:00"))
    except ValueError:
        return None

    if authenticated_at.tzinfo is None:
        return authenticated_at.replace(tzinfo=UTC)

    return authenticated_at.astimezone(UTC)


def authenticated_session_is_expired(
    session: Mapping[str, Any],
    application_settings: Settings = settings,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether authenticated session state has exceeded its max age."""

    if current_username_from_session(session) is None:
        return False

    authenticated_at = authenticated_at_utc_from_session(session)
    if authenticated_at is None:
        return True

    current_time = now or datetime.now(UTC)
    return (current_time.astimezone(UTC) - authenticated_at).total_seconds() > application_settings.session_timeout_seconds


def expire_authenticated_session_if_needed(
    request: Request,
    application_settings: Settings = settings,
) -> bool:
    """Clear expired authenticated session state and leave a login-page notice."""

    if not authenticated_session_is_expired(request.session, application_settings):
        return False

    request.session.clear()
    add_flash_message(request, "Session expired. Sign in again.", "error")
    return True


def current_username(request: Request) -> str | None:
    """Return the authenticated local app username, if one exists."""

    return current_username_from_session(request.session)


def current_user_kind(request: Request) -> str | None:
    """Return the authenticated session kind, if one exists."""

    return current_user_kind_from_session(request.session)


def current_web_user_id(request: Request) -> str | None:
    """Return the managed web-user UUID for the current session, if present."""

    return current_web_user_id_from_session(request.session)


def require_authenticated_username_from_session(session: Mapping[str, Any]) -> str:
    """Return the authenticated username from session data or raise a 401 error."""

    username = current_username_from_session(session)
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    return username


def require_authenticated_username(request: Request) -> str:
    """Return the authenticated username or raise a 401 error."""

    return require_authenticated_username_from_session(request.session)


def is_super_admin_session(session: Mapping[str, Any]) -> bool:
    """Return whether the session belongs to the config super admin."""

    return current_user_kind_from_session(session) == SUPER_ADMIN_SESSION_KIND


def require_super_admin(request: Request) -> str:
    """Return the super-admin username or raise a 403 error."""

    username = require_authenticated_username(request)
    if not is_super_admin_session(request.session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access is required.")
    return username


def session_has_debug_access(session: Mapping[str, Any], database_session: Session) -> bool:
    """Return whether the authenticated session may use Diagnostics routes."""

    if is_super_admin_session(session):
        return True

    if current_user_kind_from_session(session) != WEB_USER_SESSION_KIND:
        return False

    web_user_id = current_web_user_id_from_session(session)
    if web_user_id is None:
        return False

    web_user = database_session.get(WebUser, web_user_id)
    return bool(web_user is not None and not web_user.disabled and web_user.is_admin)


def require_debug_access(request: Request, database_session: Session) -> str:
    """Return the authenticated actor allowed to use Diagnostics or raise 403."""

    username = require_authenticated_username(request)
    if not session_has_debug_access(request.session, database_session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Diagnostics access is required.")
    return username


def require_web_user_id(request: Request) -> str:
    """Return the managed web-user UUID or raise a 403 error."""

    require_authenticated_username(request)
    return require_web_user_id_from_session(request.session)


def require_web_user_id_from_session(session: Mapping[str, Any]) -> str:
    """Return the managed web-user UUID from session data or raise a 403 error."""

    require_authenticated_username_from_session(session)
    user_id = current_web_user_id_from_session(session)
    if current_user_kind_from_session(session) != WEB_USER_SESSION_KIND or user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A managed web-user login is required.")
    return user_id


def csrf_token(request: Request) -> str:
    """Return the session CSRF token, creating it when missing."""

    existing_token = request.session.get(SESSION_CSRF_TOKEN_KEY)
    if isinstance(existing_token, str) and existing_token:
        return existing_token

    new_token = secrets.token_urlsafe(32)
    request.session[SESSION_CSRF_TOKEN_KEY] = new_token
    return new_token


def validate_csrf_session_token(session: Mapping[str, Any], submitted_token: str | None) -> None:
    """Validate a submitted CSRF token against session data."""

    expected_token = session.get(SESSION_CSRF_TOKEN_KEY)
    if not isinstance(expected_token, str) or not submitted_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token.")

    if not hmac.compare_digest(expected_token, submitted_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")


def validate_csrf_token(request: Request, submitted_token: str | None) -> None:
    """Validate a submitted CSRF token for a state-changing request."""

    validate_csrf_session_token(request.session, submitted_token)


def validate_csrf_header(request: Request) -> None:
    """Validate the CSRF token sent by JavaScript fetch requests."""

    validate_csrf_token(request, request.headers.get("x-csrf-token"))


def add_flash_message(request: Request, message: str, category: str = "info") -> None:
    """Store a short one-time message in the signed session cookie."""

    flash_messages = request.session.get(SESSION_FLASH_KEY)
    if not isinstance(flash_messages, list):
        flash_messages = []

    flash_messages.append({"message": message, "category": category})
    request.session[SESSION_FLASH_KEY] = flash_messages[-5:]


def pop_flash_messages(request: Request) -> list[dict[str, str]]:
    """Return and clear one-time flash messages."""

    flash_messages = request.session.pop(SESSION_FLASH_KEY, [])
    if not isinstance(flash_messages, list):
        return []

    safe_messages: list[dict[str, str]] = []
    for flash_message in flash_messages:
        if isinstance(flash_message, dict):
            safe_messages.append(
                {
                    "message": str(flash_message.get("message", "")),
                    "category": str(flash_message.get("category", "info")),
                }
            )
    return safe_messages


def sanitize_for_audit(value: Any) -> Any:
    """Return a JSON-safe value with sensitive keys redacted."""

    if isinstance(value, dict):
        sanitized_dictionary: dict[str, Any] = {}
        for key, nested_value in value.items():
            string_key = str(key)
            normalized_key = string_key.lower()
            if any(fragment in normalized_key for fragment in SENSITIVE_KEY_FRAGMENTS):
                sanitized_dictionary[string_key] = "[redacted]"
            else:
                sanitized_dictionary[string_key] = sanitize_for_audit(nested_value)
        return sanitized_dictionary

    if isinstance(value, list):
        return [sanitize_for_audit(item) for item in value]

    if isinstance(value, tuple):
        return [sanitize_for_audit(item) for item in value]

    if isinstance(value, str | int | float | bool) or value is None:
        return value

    return str(value)
