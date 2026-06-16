"""Authentication, CSRF, and safe logging helpers."""

from __future__ import annotations

import argparse
import hmac
import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request, status

from job_logger.config import Settings, settings

# PasswordHasher provides Argon2id password hashing for the local app account.
password_hasher = PasswordHasher()

# Session keys are intentionally centralized to avoid typo-driven auth bugs.
SESSION_USERNAME_KEY = "authenticated_username"
SESSION_CSRF_TOKEN_KEY = "csrf_token"
SESSION_FLASH_KEY = "flash_messages"

# Sensitive audit keys are redacted before being written to logs or JSON snapshots.
SENSITIVE_KEY_FRAGMENTS = ("password", "secret", "token", "key", "authorization", "cookie")


def hash_password(plain_text_password: str) -> str:
    """Return an Argon2id hash for a deployment password."""

    return password_hasher.hash(plain_text_password)


def verify_password(plain_text_password: str, application_settings: Settings = settings) -> bool:
    """Verify the submitted password against configured credentials."""

    if application_settings.app_password_hash:
        try:
            return password_hasher.verify(application_settings.app_password_hash, plain_text_password)
        except (VerifyMismatchError, VerificationError):
            return False

    if application_settings.app_password:
        return hmac.compare_digest(application_settings.app_password, plain_text_password)

    # The development default makes the app usable before secrets are configured.
    return hmac.compare_digest("admin", plain_text_password)


def authenticate_username(username: str, application_settings: Settings = settings) -> bool:
    """Validate the submitted username with constant-time comparison."""

    return hmac.compare_digest(application_settings.app_username, username)


def login_session(request: Request, username: str) -> None:
    """Create an authenticated application session."""

    request.session.clear()
    request.session[SESSION_USERNAME_KEY] = username
    request.session[SESSION_CSRF_TOKEN_KEY] = secrets.token_urlsafe(32)


def logout_session(request: Request) -> None:
    """Clear all server-signed session state."""

    request.session.clear()


def current_username(request: Request) -> str | None:
    """Return the authenticated local app username, if one exists."""

    username = request.session.get(SESSION_USERNAME_KEY)
    if isinstance(username, str) and username:
        return username

    return None


def require_authenticated_username(request: Request) -> str:
    """Return the authenticated username or raise a 401 error."""

    username = current_username(request)
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    return username


def csrf_token(request: Request) -> str:
    """Return the session CSRF token, creating it when missing."""

    existing_token = request.session.get(SESSION_CSRF_TOKEN_KEY)
    if isinstance(existing_token, str) and existing_token:
        return existing_token

    new_token = secrets.token_urlsafe(32)
    request.session[SESSION_CSRF_TOKEN_KEY] = new_token
    return new_token


def validate_csrf_token(request: Request, submitted_token: str | None) -> None:
    """Validate a submitted CSRF token for a state-changing request."""

    expected_token = request.session.get(SESSION_CSRF_TOKEN_KEY)
    if not isinstance(expected_token, str) or not submitted_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token.")

    if not hmac.compare_digest(expected_token, submitted_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")


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


def main() -> None:
    """Command line helper for generating password hashes."""

    parser = argparse.ArgumentParser(description="Job Logger security helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    hash_parser = subparsers.add_parser("hash-password", help="Generate an Argon2id password hash")
    hash_parser.add_argument("password", help="Plain text password to hash")

    arguments = parser.parse_args()
    if arguments.command == "hash-password":
        print(hash_password(arguments.password))


if __name__ == "__main__":
    main()

