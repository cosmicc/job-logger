"""Login failure counting and optional Cloudflare auto-blocking."""

from __future__ import annotations

import logging

from fastapi import Request
from sqlalchemy.orm import Session

from job_logger.config import Settings, settings
from job_logger.services.audit import record_audit_event
from job_logger.services.cloudflare_blocks import (
    CloudflareBlockError,
    cloudflare_block_for_ip,
    cloudflare_ip_blocking_configured,
    create_app_cloudflare_block,
    ip_is_allowlisted,
    normalize_ip_address,
)
from job_logger.services.login_failures import (
    client_ip_from_request,
    increment_login_failure_counter,
    log_failed_login_attempt,
)

logger = logging.getLogger(__name__)


def record_failed_login_attempt_and_maybe_block(
    database_session: Session,
    request: Request,
    *,
    submitted_username: str,
    submitted_password: str,
    reason: str,
    application_settings: Settings = settings,
) -> int:
    """Record one failed login and auto-block its IP when the threshold is reached."""

    failed_count = increment_login_failure_counter(database_session, request)
    log_failed_login_attempt(
        request,
        submitted_username=submitted_username,
        submitted_password=submitted_password,
        reason=reason,
        failed_count=failed_count,
        max_attempts=application_settings.cloudflare_auto_block_failed_login_attempts,
        application_settings=application_settings,
    )
    maybe_auto_block_failed_login_ip(
        database_session,
        request,
        failed_count=failed_count,
        application_settings=application_settings,
    )
    return failed_count


def maybe_auto_block_failed_login_ip(
    database_session: Session,
    request: Request,
    *,
    failed_count: int,
    application_settings: Settings = settings,
) -> None:
    """Automatically block a login IP after the configured consecutive-failure threshold."""

    threshold = application_settings.cloudflare_auto_block_failed_login_attempts
    if failed_count < threshold:
        return
    if not cloudflare_ip_blocking_configured(application_settings):
        return

    logged_client_ip = client_ip_from_request(request)
    normalized_ip = normalize_ip_address(logged_client_ip)
    if normalized_ip is None:
        logger.warning("Skipped Cloudflare auto-block for invalid login client IP")
        return
    if ip_is_allowlisted(normalized_ip, application_settings):
        logger.warning("Skipped Cloudflare auto-block for allowlisted ip=%s", normalized_ip)
        return
    if cloudflare_block_for_ip(database_session, normalized_ip) is not None:
        return

    try:
        block = create_app_cloudflare_block(
            database_session,
            normalized_ip,
            source="automatic",
            reason=f"{threshold} consecutive failed local app login attempts",
            failure_count=failed_count,
            application_settings=application_settings,
        )
    except CloudflareBlockError as exc:
        logger.warning("Could not auto-block failed login IP at Cloudflare: %s", exc)
        return

    record_audit_event(
        database_session,
        actor="system",
        action="debug.cloudflare_ip_block.created",
        request=request,
        details={
            "ip_address": block.ip_address,
            "cloudflare_rule_id": block.cloudflare_rule_id,
            "source": block.source,
            "failure_count": failed_count,
        },
    )
