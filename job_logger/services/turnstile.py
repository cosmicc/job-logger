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


async def verify_turnstile_response(
    *,
    response_token: str,
    remote_ip: str,
    application_settings: Settings = settings,
) -> TurnstileVerificationResult:
    """Verify a browser Turnstile response token with Cloudflare Siteverify."""

    if not application_settings.turnstile_enabled:
        if application_settings.dev_build and not application_settings.is_production:
            return TurnstileVerificationResult(success=True)
        LOGGER.warning("Turnstile verification bypass refused outside explicit dev build")
        return TurnstileVerificationResult(success=False, error_codes=("turnstile-disabled",))

    if not response_token or not application_settings.turnstile_secret_key:
        return TurnstileVerificationResult(success=False, error_codes=("missing-input",))
    if len(response_token) > TURNSTILE_RESPONSE_TOKEN_MAX_LENGTH:
        return TurnstileVerificationResult(success=False, error_codes=("invalid-input-response",))

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
        LOGGER.warning("Turnstile verification request failed: %s", exc.__class__.__name__)
        return TurnstileVerificationResult(success=False, error_codes=("verification-error",))

    error_codes = tuple(str(error_code)[:80] for error_code in verification.get("error-codes", []) if error_code)
    if not bool(verification.get("success")):
        LOGGER.info("Turnstile verification failed with codes=%s", ",".join(error_codes) or "none")
        return TurnstileVerificationResult(success=False, error_codes=error_codes or ("verification-failed",))

    returned_action = str(verification.get("action", ""))
    if returned_action != PASSWORD_RESET_TURNSTILE_ACTION:
        LOGGER.info("Turnstile verification failed with action mismatch")
        return TurnstileVerificationResult(success=False, error_codes=("action-mismatch",))

    expected_hostname = _expected_hostname(application_settings)
    returned_hostname = str(verification.get("hostname", "")).casefold()
    if expected_hostname and returned_hostname != expected_hostname:
        LOGGER.info("Turnstile verification failed with hostname mismatch")
        return TurnstileVerificationResult(success=False, error_codes=("hostname-mismatch",))

    return TurnstileVerificationResult(success=True)
