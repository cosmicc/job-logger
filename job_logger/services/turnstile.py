"""Cloudflare Turnstile verification for public authentication forms."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import httpx

from job_logger.config import Settings, settings

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnstileVerificationResult:
    """Safe result returned after checking a Turnstile token."""

    success: bool
    error_codes: tuple[str, ...] = ()


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

    return TurnstileVerificationResult(success=True)
