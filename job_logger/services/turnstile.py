"""Cloudflare Turnstile verification for public authentication forms."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from job_logger.config import Settings, settings

LOGGER = logging.getLogger(__name__)
TURNSTILE_RESPONSE_TOKEN_MAX_LENGTH = 2048
PASSWORD_RESET_TURNSTILE_ACTION = "password_reset"


@dataclass(frozen=True)
class TurnstileVerificationResult:
    """Safe result returned after checking a Turnstile token."""

    success: bool
    error_codes: tuple[str, ...] = ()


def _expected_hostname(application_settings: Settings) -> str | None:
    """Return the expected Turnstile hostname from the configured public URL."""

    parsed_url = urlparse(application_settings.app_public_base_url)
    if parsed_url.hostname is None:
        return None
    return parsed_url.hostname.casefold()


def _safe_verify_url_host(application_settings: Settings) -> str:
    """Return the configured Siteverify host without query string details."""

    parsed_url = urlparse(application_settings.turnstile_verify_url)
    if parsed_url.hostname is None:
        return "unknown"
    return parsed_url.hostname.casefold()


async def verify_turnstile_response(
    *,
    response_token: str,
    remote_ip: str,
    application_settings: Settings = settings,
) -> TurnstileVerificationResult:
    """Verify a browser Turnstile response token with Cloudflare Siteverify."""

    if not application_settings.turnstile_enabled:
        if application_settings.dev_build and not application_settings.is_production:
            LOGGER.debug("Turnstile verification bypassed for explicit non-production dev build")
            return TurnstileVerificationResult(success=True)
        LOGGER.warning("Turnstile verification bypass refused outside explicit dev build")
        return TurnstileVerificationResult(success=False, error_codes=("turnstile-disabled",))

    if not response_token or not application_settings.turnstile_secret_key:
        LOGGER.info(
            "Turnstile verification missing input remote_ip=%s has_token=%s has_secret=%s",
            remote_ip,
            bool(response_token),
            bool(application_settings.turnstile_secret_key),
        )
        return TurnstileVerificationResult(success=False, error_codes=("missing-input",))
    if len(response_token) > TURNSTILE_RESPONSE_TOKEN_MAX_LENGTH:
        LOGGER.info(
            "Turnstile verification rejected oversized token remote_ip=%s token_length=%s max_length=%s",
            remote_ip,
            len(response_token),
            TURNSTILE_RESPONSE_TOKEN_MAX_LENGTH,
        )
        return TurnstileVerificationResult(success=False, error_codes=("invalid-input-response",))

    expected_hostname = _expected_hostname(application_settings)
    LOGGER.debug(
        "Turnstile Siteverify request start remote_ip=%s token_length=%s verify_host=%s expected_hostname=%s timeout_seconds=%s",
        remote_ip,
        len(response_token),
        _safe_verify_url_host(application_settings),
        expected_hostname or "none",
        application_settings.turnstile_timeout_seconds,
    )
    payload = {
        "secret": application_settings.turnstile_secret_key,
        "response": response_token,
        "remoteip": remote_ip,
        "idempotency_key": str(uuid.uuid4()),
    }
    try:
        async with httpx.AsyncClient(timeout=application_settings.turnstile_timeout_seconds) as client:
            response = await client.post(application_settings.turnstile_verify_url, data=payload)
            response.raise_for_status()
            verification = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        http_status = getattr(getattr(exc, "response", None), "status_code", "unknown")
        LOGGER.warning(
            "Turnstile verification request failed remote_ip=%s error_class=%s http_status=%s verify_host=%s",
            remote_ip,
            exc.__class__.__name__,
            http_status,
            _safe_verify_url_host(application_settings),
        )
        return TurnstileVerificationResult(success=False, error_codes=("verification-error",))

    error_codes = tuple(str(error_code)[:80] for error_code in verification.get("error-codes", []) if error_code)
    returned_action = str(verification.get("action", ""))
    returned_hostname = str(verification.get("hostname", "")).casefold()
    LOGGER.debug(
        "Turnstile Siteverify response remote_ip=%s success=%s returned_action=%s returned_hostname=%s error_codes=%s",
        remote_ip,
        bool(verification.get("success")),
        returned_action or "none",
        returned_hostname or "none",
        ",".join(error_codes) or "none",
    )
    if not bool(verification.get("success")):
        LOGGER.info(
            "Turnstile verification failed remote_ip=%s error_codes=%s returned_action=%s returned_hostname=%s",
            remote_ip,
            ",".join(error_codes) or "none",
            returned_action or "none",
            returned_hostname or "none",
        )
        return TurnstileVerificationResult(success=False, error_codes=error_codes or ("verification-failed",))

    if returned_action != PASSWORD_RESET_TURNSTILE_ACTION:
        LOGGER.info(
            "Turnstile verification failed with action mismatch remote_ip=%s expected_action=%s returned_action=%s",
            remote_ip,
            PASSWORD_RESET_TURNSTILE_ACTION,
            returned_action or "none",
        )
        return TurnstileVerificationResult(success=False, error_codes=("action-mismatch",))

    if expected_hostname and returned_hostname != expected_hostname:
        LOGGER.info(
            "Turnstile verification failed with hostname mismatch remote_ip=%s expected_hostname=%s returned_hostname=%s",
            remote_ip,
            expected_hostname,
            returned_hostname or "none",
        )
        return TurnstileVerificationResult(success=False, error_codes=("hostname-mismatch",))

    LOGGER.debug(
        "Turnstile verification succeeded remote_ip=%s returned_action=%s returned_hostname=%s",
        remote_ip,
        returned_action,
        returned_hostname or "none",
    )
    return TurnstileVerificationResult(success=True)
