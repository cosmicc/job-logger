"""Cloudflare zone IP Access Rule helpers for app-managed login blocks."""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_logger.config import Settings, settings
from job_logger.logging_config import redact_sensitive_text
from job_logger.models import CloudflareIPBlock

logger = logging.getLogger(__name__)

CLOUDFLARE_API_BASE_URL = "https://api.cloudflare.com/client/v4"
CLOUDFLARE_TIMEOUT_SECONDS = 10.0
CLOUDFLARE_BLOCK_REASON_MAX_CHARS = 180
CLOUDFLARE_BLOCK_NOTE_MAX_CHARS = 255


class CloudflareBlockError(RuntimeError):
    """Raised when an app-managed Cloudflare block operation cannot finish."""


@dataclass(frozen=True)
class CloudflareAccessRule:
    """Small app-owned representation of a Cloudflare IP Access Rule."""

    rule_id: str
    ip_address: str


def cloudflare_ip_blocking_configured(application_settings: Settings = settings) -> bool:
    """Return whether Cloudflare blocking has all required runtime settings."""

    return bool(
        application_settings.cloudflare_ip_blocking_enabled
        and application_settings.cloudflare_api_token.strip()
        and application_settings.cloudflare_zone_id.strip()
    )


def normalize_ip_address(value: str) -> str | None:
    """Return a canonical IPv4/IPv6 address string, or None for invalid input."""

    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError:
        return None


def sanitize_cloudflare_block_reason(value: object, *, default_reason: str) -> str:
    """Return a safe, single-line reason for app-managed Cloudflare blocks."""

    cleaned_reason = redact_sensitive_text(str(value or ""))
    cleaned_reason = cleaned_reason.replace("\x00", "").replace("\r", " ").replace("\n", " ")
    cleaned_reason = re.sub(r"\s+", " ", cleaned_reason).strip()
    if not cleaned_reason:
        cleaned_reason = default_reason
    return cleaned_reason[:CLOUDFLARE_BLOCK_REASON_MAX_CHARS]


def _allowlist_entries(application_settings: Settings) -> tuple[str, ...]:
    """Split the configured allowlist on common environment-friendly separators."""

    return tuple(
        item.strip()
        for item in re.split(r"[\s,]+", application_settings.cloudflare_ip_block_allowlist)
        if item.strip()
    )


def ip_is_allowlisted(ip_address: str, application_settings: Settings = settings) -> bool:
    """Return whether an IP is protected from app-managed Cloudflare blocking."""

    normalized_ip = normalize_ip_address(ip_address)
    if normalized_ip is None:
        return False

    ip_value = ipaddress.ip_address(normalized_ip)
    for entry in _allowlist_entries(application_settings):
        try:
            if "/" in entry:
                if ip_value in ipaddress.ip_network(entry, strict=False):
                    return True
            elif ip_value == ipaddress.ip_address(entry):
                return True
        except ValueError:
            logger.warning("Ignoring invalid Cloudflare IP block allowlist entry=%s", entry)
    return False


def _cloudflare_headers(application_settings: Settings) -> dict[str, str]:
    """Return authorization headers without exposing the token in logs."""

    return {
        "Authorization": f"Bearer {application_settings.cloudflare_api_token.strip()}",
        "Content-Type": "application/json",
    }


def _cloudflare_target_for_ip(ip_address: str) -> str:
    """Return the Cloudflare IP Access Rule target type for an IP address."""

    ip_value = ipaddress.ip_address(ip_address)
    return "ip6" if ip_value.version == 6 else "ip"


def _api_error_message(payload: object) -> str:
    """Return a safe, compact Cloudflare API error message."""

    if not isinstance(payload, dict):
        return "Cloudflare API returned an unexpected response."
    errors = payload.get("errors")
    if not isinstance(errors, list) or not errors:
        return "Cloudflare API request was not successful."

    messages: list[str] = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        message = str(error.get("message") or "").strip()
        code = str(error.get("code") or "").strip()
        if code and message:
            messages.append(f"{code}: {message}")
        elif message:
            messages.append(message)
    return "; ".join(messages) or "Cloudflare API request was not successful."


def create_cloudflare_ip_block(
    ip_address: str,
    *,
    note: str,
    application_settings: Settings = settings,
) -> CloudflareAccessRule:
    """Create a zone-scoped Cloudflare IP Access Rule with block mode."""

    if not cloudflare_ip_blocking_configured(application_settings):
        raise CloudflareBlockError("Cloudflare IP blocking is not fully configured.")

    normalized_ip = normalize_ip_address(ip_address)
    if normalized_ip is None:
        raise CloudflareBlockError("Cannot block an invalid IP address.")
    if ip_is_allowlisted(normalized_ip, application_settings):
        raise CloudflareBlockError("IP address is on the Cloudflare block allowlist.")

    url = (
        f"{CLOUDFLARE_API_BASE_URL}/zones/"
        f"{application_settings.cloudflare_zone_id.strip()}/firewall/access_rules/rules"
    )
    body = {
        "mode": "block",
        "configuration": {
            "target": _cloudflare_target_for_ip(normalized_ip),
            "value": normalized_ip,
        },
        "notes": note[:255],
    }
    try:
        response = httpx.post(
            url,
            headers=_cloudflare_headers(application_settings),
            json=body,
            timeout=CLOUDFLARE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise CloudflareBlockError("Could not contact Cloudflare to create IP block.") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise CloudflareBlockError("Cloudflare API returned a non-JSON response.") from exc

    if response.status_code >= 400 or not payload.get("success"):
        raise CloudflareBlockError(_api_error_message(payload))

    result = payload.get("result")
    if not isinstance(result, dict) or not result.get("id"):
        raise CloudflareBlockError("Cloudflare API did not return a rule ID.")
    return CloudflareAccessRule(rule_id=str(result["id"]), ip_address=normalized_ip)


def delete_cloudflare_ip_block(
    rule_id: str,
    *,
    application_settings: Settings = settings,
) -> None:
    """Delete one app-managed Cloudflare IP Access Rule by Cloudflare rule ID."""

    if not cloudflare_ip_blocking_configured(application_settings):
        raise CloudflareBlockError("Cloudflare IP blocking is not fully configured.")
    cleaned_rule_id = str(rule_id).strip()
    if not cleaned_rule_id:
        raise CloudflareBlockError("Cloudflare rule ID is missing.")

    url = (
        f"{CLOUDFLARE_API_BASE_URL}/zones/"
        f"{application_settings.cloudflare_zone_id.strip()}/firewall/access_rules/rules/"
        f"{cleaned_rule_id}"
    )
    try:
        response = httpx.delete(
            url,
            headers=_cloudflare_headers(application_settings),
            timeout=CLOUDFLARE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise CloudflareBlockError("Could not contact Cloudflare to delete IP block.") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise CloudflareBlockError("Cloudflare API returned a non-JSON response.") from exc

    if response.status_code == 404:
        logger.warning("Cloudflare IP Access Rule was already absent rule_id=%s", cleaned_rule_id)
        return
    if response.status_code >= 400 or not payload.get("success"):
        raise CloudflareBlockError(_api_error_message(payload))


def cloudflare_block_for_ip(database_session: Session, ip_address: str) -> CloudflareIPBlock | None:
    """Return the local app-managed Cloudflare block row for an IP, if present."""

    normalized_ip = normalize_ip_address(ip_address)
    if normalized_ip is None:
        return None
    return database_session.scalar(
        select(CloudflareIPBlock)
        .where(CloudflareIPBlock.ip_address == normalized_ip)
        .limit(1)
    )


def create_app_cloudflare_block(
    database_session: Session,
    ip_address: str,
    *,
    source: str,
    reason: str,
    failure_count: int | None = None,
    application_settings: Settings = settings,
) -> CloudflareIPBlock:
    """Create a Cloudflare block and stage the local app-managed rule row."""

    normalized_ip = normalize_ip_address(ip_address)
    if normalized_ip is None:
        raise CloudflareBlockError("Cannot block an invalid IP address.")
    if ip_is_allowlisted(normalized_ip, application_settings):
        raise CloudflareBlockError("IP address is on the Cloudflare block allowlist.")

    existing_block = cloudflare_block_for_ip(database_session, normalized_ip)
    if existing_block is not None:
        return existing_block

    safe_reason = sanitize_cloudflare_block_reason(
        reason,
        default_reason=f"Diagnostics {source} Cloudflare block",
    )
    note = f"Job Logger {source} block: {safe_reason}"[:CLOUDFLARE_BLOCK_NOTE_MAX_CHARS]
    access_rule = create_cloudflare_ip_block(
        normalized_ip,
        note=note,
        application_settings=application_settings,
    )
    block = CloudflareIPBlock(
        ip_address=normalized_ip,
        cloudflare_rule_id=access_rule.rule_id,
        source=source,
        reason=safe_reason,
        failure_count=failure_count,
        notes=note,
    )
    database_session.add(block)
    database_session.flush()
    logger.warning(
        "Created app-managed Cloudflare IP block ip=%s source=%s failure_count=%s",
        normalized_ip,
        source,
        failure_count,
    )
    return block


def remove_app_cloudflare_block(
    database_session: Session,
    block: CloudflareIPBlock,
    *,
    application_settings: Settings = settings,
) -> None:
    """Delete the Cloudflare rule and stage removal of its local block-list row."""

    delete_cloudflare_ip_block(
        block.cloudflare_rule_id,
        application_settings=application_settings,
    )
    logger.warning("Removed app-managed Cloudflare IP block ip=%s", block.ip_address)
    database_session.delete(block)
