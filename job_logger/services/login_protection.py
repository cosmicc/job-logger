"""Login failure counting and optional Cloudflare auto-blocking."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_logger.config import Settings, settings
from job_logger.models import LoginFailureCounter
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
    enforcement_client_ip_from_request,
    increment_login_failure_counter,
    log_failed_login_attempt,
    login_counter_username,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoginLockoutState:
    """Current local lockout status for one enforcement IP and username."""

    locked: bool
    failed_count: int
    max_attempts: int
    remaining_seconds: int


def _as_utc(timestamp: datetime | None) -> datetime | None:
    """Return a timezone-aware UTC timestamp for lockout arithmetic."""

    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def current_login_lockout(
    database_session: Session,
    request: Request,
    *,
    submitted_username: str,
    application_settings: Settings = settings,
) -> LoginLockoutState:
    """Return whether local login lockout should stop credential verification."""

    max_attempts = application_settings.cloudflare_auto_block_failed_login_attempts
    client_ip = enforcement_client_ip_from_request(request)
    username = login_counter_username(submitted_username)
    counter = database_session.scalar(
        select(LoginFailureCounter)
        .where(LoginFailureCounter.client_ip == client_ip, LoginFailureCounter.username == username)
        .limit(1)
    )
    if counter is None or counter.failed_count < max_attempts:
        return LoginLockoutState(
            locked=False,
            failed_count=counter.failed_count if counter is not None else 0,
            max_attempts=max_attempts,
            remaining_seconds=0,
        )

    current_time = datetime.now(UTC)
    last_failed_at_utc = _as_utc(counter.last_failed_at_utc)
    if last_failed_at_utc is None:
        return LoginLockoutState(locked=False, failed_count=counter.failed_count, max_attempts=max_attempts, remaining_seconds=0)

    lockout_expires_at = last_failed_at_utc + timedelta(minutes=application_settings.login_local_lockout_minutes)
    remaining_seconds = max(int((lockout_expires_at - current_time).total_seconds()), 0)
    if remaining_seconds <= 0:
        counter.failed_count = 0
        counter.updated_at_utc = current_time
        database_session.flush()
        return LoginLockoutState(locked=False, failed_count=0, max_attempts=max_attempts, remaining_seconds=0)

    return LoginLockoutState(
        locked=True,
        failed_count=counter.failed_count,
        max_attempts=max_attempts,
        remaining_seconds=remaining_seconds,
    )


def record_local_login_lockout(
    database_session: Session,
    request: Request,
    *,
    submitted_username: str,
    submitted_password: str,
    lockout_state: LoginLockoutState,
    application_settings: Settings = settings,
) -> None:
    """Log a pre-authentication local lockout without checking credentials."""

    log_failed_login_attempt(
        request,
        submitted_username=submitted_username,
        submitted_password=submitted_password,
        reason="local_lockout",
        failed_count=lockout_state.failed_count,
        max_attempts=lockout_state.max_attempts,
        lockout_applied=True,
        lockout_remaining_seconds=lockout_state.remaining_seconds,
        application_settings=application_settings,
    )
    record_audit_event(
        database_session,
        actor=submitted_username or "unknown",
        action="auth.login.failed",
        request=request,
        details={
            "username": submitted_username,
            "reason": "local_lockout",
            "failed_count": lockout_state.failed_count,
            "lockout_remaining_seconds": lockout_state.remaining_seconds,
        },
    )


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

    failed_count = increment_login_failure_counter(
        database_session,
        request,
        submitted_username=submitted_username,
    )
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

    logged_client_ip = enforcement_client_ip_from_request(request)
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
            "reason": block.reason,
            "failure_count": failed_count,
        },
    )
