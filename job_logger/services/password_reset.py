"""Self-service managed-user password reset helpers."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_logger.config import Settings, settings
from job_logger.models import PasswordResetRequestCounter, PasswordResetToken, WebUser
from job_logger.services.audit import record_audit_event
from job_logger.services.cloudflare_blocks import (
    CloudflareBlockError,
    cloudflare_block_for_ip,
    cloudflare_ip_blocking_configured,
    create_app_cloudflare_block,
    ip_is_allowlisted,
    normalize_ip_address,
)
from job_logger.services.login_failures import enforcement_client_ip_from_request
from job_logger.services.session_control import invalidate_web_user_sessions
from job_logger.services.users import WebUserError, change_web_user_password, normalize_optional_email
from job_logger.time_utils import now_utc

PASSWORD_RESET_GENERIC_MESSAGE = (
    "If an enabled Job Logger account exists for that email address, a password reset email has been sent. "
    "The reset link is valid for 24 hours."
)
PASSWORD_RESET_RATE_LIMIT_MESSAGE = "Too many password reset requests. Try again later."
PASSWORD_RESET_INVALID_LINK_MESSAGE = "This password reset link is invalid or expired. Request a new reset link."
RESET_TOKEN_BYTES = 48
IP_RESET_LIMIT = 5
IP_RESET_WINDOW = timedelta(minutes=15)
EMAIL_RESET_LIMIT = 3
EMAIL_RESET_WINDOW = timedelta(hours=1)
ACCOUNT_EMAIL_LIMIT = 1
ACCOUNT_EMAIL_WINDOW = timedelta(minutes=15)
UNMATCHED_EMAIL_IP_SCOPE = "unmatched_email_ip"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PasswordResetRateLimitResult:
    """Outcome from consuming one or more reset throttle counters."""

    limited: bool
    scope: str | None = None
    limit: int = 0
    window_seconds: int = 0


@dataclass(frozen=True)
class PasswordResetAbuseLockoutState:
    """Local lockout state for repeated unmatched reset-email submissions."""

    locked: bool
    failed_count: int
    max_attempts: int
    remaining_seconds: int


@dataclass(frozen=True)
class PasswordResetTokenLookup:
    """Status returned after resolving a raw reset token."""

    status: str
    reset_token: PasswordResetToken | None = None


def normalize_password_reset_email(email: str | None) -> str:
    """Return the bounded case-insensitive reset email lookup key."""

    normalized_email = normalize_optional_email(email)
    if normalized_email is None:
        raise WebUserError("Email is required.")
    return normalized_email.casefold()


def password_reset_hmac(value: str, *, purpose: str, application_settings: Settings = settings) -> str:
    """Return a hex HMAC used for reset tokens and safe email identifiers."""

    return hmac.new(
        application_settings.app_secret_key.encode(),
        f"{purpose}:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def password_reset_token_hash(raw_token: str, application_settings: Settings = settings) -> str:
    """Return the database token hash for a raw reset URL token."""

    return password_reset_hmac(raw_token, purpose="password-reset-token", application_settings=application_settings)


def password_reset_email_hash(normalized_email: str, application_settings: Settings = settings) -> str:
    """Return a safe audit/throttle identifier for a submitted email address."""

    return password_reset_hmac(normalized_email, purpose="password-reset-email", application_settings=application_settings)


def _as_utc(timestamp: datetime | None) -> datetime | None:
    """Return a timezone-aware UTC timestamp for reset arithmetic."""

    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _request_user_agent(request: Request) -> str:
    """Return a bounded user agent for reset-token metadata."""

    return str(request.headers.get("user-agent", ""))[:255]


def _consume_rate_limit(
    database_session: Session,
    *,
    scope: str,
    scope_key: str,
    max_requests: int,
    window: timedelta,
    current_time: datetime,
) -> PasswordResetRateLimitResult:
    """Increment a fixed-window reset throttle and report whether it is exceeded."""

    counter = database_session.scalar(
        select(PasswordResetRequestCounter)
        .where(
            PasswordResetRequestCounter.scope == scope,
            PasswordResetRequestCounter.scope_key == scope_key,
        )
        .limit(1)
    )
    if counter is None:
        counter = PasswordResetRequestCounter(
            scope=scope,
            scope_key=scope_key,
            window_started_at_utc=current_time,
            request_count=0,
            created_at_utc=current_time,
            updated_at_utc=current_time,
        )
        database_session.add(counter)

    window_started_at_utc = _as_utc(counter.window_started_at_utc) or current_time
    if current_time - window_started_at_utc >= window:
        counter.window_started_at_utc = current_time
        counter.request_count = 0

    counter.request_count += 1
    counter.updated_at_utc = current_time
    database_session.flush()
    if counter.request_count > max_requests:
        return PasswordResetRateLimitResult(
            limited=True,
            scope=scope,
            limit=max_requests,
            window_seconds=int(window.total_seconds()),
        )
    return PasswordResetRateLimitResult(limited=False)


def consume_preflight_reset_rate_limits(
    database_session: Session,
    request: Request,
    *,
    normalized_email: str,
    application_settings: Settings = settings,
) -> PasswordResetRateLimitResult:
    """Consume IP and submitted-email throttles before any account lookup."""

    current_time = now_utc()
    client_ip = enforcement_client_ip_from_request(request)
    ip_result = _consume_rate_limit(
        database_session,
        scope="ip",
        scope_key=client_ip,
        max_requests=IP_RESET_LIMIT,
        window=IP_RESET_WINDOW,
        current_time=current_time,
    )
    email_result = _consume_rate_limit(
        database_session,
        scope="email",
        scope_key=password_reset_email_hash(normalized_email, application_settings),
        max_requests=EMAIL_RESET_LIMIT,
        window=EMAIL_RESET_WINDOW,
        current_time=current_time,
    )
    return ip_result if ip_result.limited else email_result


def consume_account_reset_rate_limit(
    database_session: Session,
    *,
    web_user: WebUser,
) -> PasswordResetRateLimitResult:
    """Consume the per-account email throttle for a matched enabled user."""

    return _consume_rate_limit(
        database_session,
        scope="account",
        scope_key=web_user.id,
        max_requests=ACCOUNT_EMAIL_LIMIT,
        window=ACCOUNT_EMAIL_WINDOW,
        current_time=now_utc(),
    )


def find_unique_enabled_web_user_by_email(
    database_session: Session,
    *,
    normalized_email: str,
) -> WebUser | None:
    """Return one enabled managed user for an email, or None for zero/multiple matches."""

    matching_users = list(
        database_session.execute(
            select(WebUser)
            .where(
                WebUser.disabled.is_(False),
                WebUser.archived_at_utc.is_(None),
                func.lower(WebUser.email) == normalized_email,
            )
            .limit(2)
        ).scalars()
    )
    if len(matching_users) != 1:
        return None
    return matching_users[0]


def _unmatched_email_ip_counter(
    database_session: Session,
    request: Request,
) -> PasswordResetRequestCounter | None:
    """Return the consecutive unmatched-email counter for the trusted request IP."""

    client_ip = enforcement_client_ip_from_request(request)
    return database_session.scalar(
        select(PasswordResetRequestCounter)
        .where(
            PasswordResetRequestCounter.scope == UNMATCHED_EMAIL_IP_SCOPE,
            PasswordResetRequestCounter.scope_key == client_ip,
        )
        .with_for_update()
        .limit(1)
    )


def current_unmatched_password_reset_lockout(
    database_session: Session,
    request: Request,
    *,
    application_settings: Settings = settings,
) -> PasswordResetAbuseLockoutState:
    """Return whether repeated unmatched reset emails locally lock this IP."""

    threshold = application_settings.password_reset_failed_attempts_block_threshold
    counter = _unmatched_email_ip_counter(database_session, request)
    if counter is None or counter.request_count < threshold:
        return PasswordResetAbuseLockoutState(
            locked=False,
            failed_count=counter.request_count if counter is not None else 0,
            max_attempts=threshold,
            remaining_seconds=0,
        )

    current_time = now_utc()
    last_failed_at_utc = _as_utc(counter.updated_at_utc)
    if last_failed_at_utc is None:
        return PasswordResetAbuseLockoutState(
            locked=False,
            failed_count=counter.request_count,
            max_attempts=threshold,
            remaining_seconds=0,
        )

    lockout_expires_at = last_failed_at_utc + timedelta(
        minutes=application_settings.login_local_lockout_minutes
    )
    remaining_seconds = max(int((lockout_expires_at - current_time).total_seconds()), 0)
    if remaining_seconds <= 0:
        counter.window_started_at_utc = current_time
        counter.request_count = 0
        counter.updated_at_utc = current_time
        database_session.flush()
        return PasswordResetAbuseLockoutState(
            locked=False,
            failed_count=0,
            max_attempts=threshold,
            remaining_seconds=0,
        )

    return PasswordResetAbuseLockoutState(
        locked=True,
        failed_count=counter.request_count,
        max_attempts=threshold,
        remaining_seconds=remaining_seconds,
    )


def reset_unmatched_password_reset_attempts(
    database_session: Session,
    request: Request,
) -> None:
    """Reset the trusted IP counter after one unique enabled email match."""

    counter = _unmatched_email_ip_counter(database_session, request)
    if counter is None:
        return

    current_time = now_utc()
    counter.window_started_at_utc = current_time
    counter.request_count = 0
    counter.updated_at_utc = current_time
    database_session.flush()


def record_unmatched_password_reset_attempt_and_maybe_block(
    database_session: Session,
    request: Request,
    *,
    application_settings: Settings = settings,
) -> int:
    """Count an unmatched reset email and optionally block the trusted IP."""

    current_time = now_utc()
    counter = _unmatched_email_ip_counter(database_session, request)
    if counter is None:
        counter = PasswordResetRequestCounter(
            scope=UNMATCHED_EMAIL_IP_SCOPE,
            scope_key=enforcement_client_ip_from_request(request),
            window_started_at_utc=current_time,
            request_count=0,
            created_at_utc=current_time,
            updated_at_utc=current_time,
        )
        database_session.add(counter)

    counter.request_count += 1
    counter.updated_at_utc = current_time
    database_session.flush()
    failed_count = counter.request_count
    threshold = application_settings.password_reset_failed_attempts_block_threshold
    if failed_count < threshold or not cloudflare_ip_blocking_configured(application_settings):
        return failed_count

    normalized_ip = normalize_ip_address(enforcement_client_ip_from_request(request))
    if normalized_ip is None:
        LOGGER.warning("Skipped password-reset Cloudflare auto-block for invalid client IP")
        return failed_count
    if ip_is_allowlisted(normalized_ip, application_settings):
        LOGGER.warning("Skipped password-reset Cloudflare auto-block for allowlisted ip=%s", normalized_ip)
        return failed_count
    if cloudflare_block_for_ip(database_session, normalized_ip) is not None:
        return failed_count

    reason = f"{threshold} consecutive unmatched password reset email attempts"
    try:
        block = create_app_cloudflare_block(
            database_session,
            normalized_ip,
            source="automatic_password_reset",
            reason=reason,
            failure_count=failed_count,
            application_settings=application_settings,
        )
    except CloudflareBlockError as exc:
        LOGGER.warning("Could not auto-block password-reset IP at Cloudflare: %s", exc)
        return failed_count

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
    return failed_count


def create_password_reset_token(
    database_session: Session,
    request: Request,
    *,
    web_user: WebUser,
    sent_to_email: str,
    application_settings: Settings = settings,
) -> tuple[str, PasswordResetToken]:
    """Create one single-use reset-token row and return the raw URL token."""

    raw_token = secrets.token_urlsafe(RESET_TOKEN_BYTES)
    current_time = now_utc()
    reset_token = PasswordResetToken(
        web_user_id=web_user.id,
        token_hash=password_reset_token_hash(raw_token, application_settings),
        created_at_utc=current_time,
        expires_at_utc=current_time + timedelta(seconds=application_settings.password_reset_token_ttl_seconds),
        request_ip=enforcement_client_ip_from_request(request),
        request_user_agent=_request_user_agent(request),
        sent_to_email=sent_to_email,
    )
    database_session.add(reset_token)
    database_session.flush()
    return raw_token, reset_token


def password_reset_url(raw_token: str, application_settings: Settings = settings) -> str:
    """Return the absolute reset URL sent by email."""

    return f"{application_settings.app_public_base_url}/reset-password/{raw_token}"


def lookup_password_reset_token(
    database_session: Session,
    raw_token: str,
    *,
    application_settings: Settings = settings,
) -> PasswordResetTokenLookup:
    """Resolve a raw reset token without exposing whether an account exists."""

    if not raw_token:
        return PasswordResetTokenLookup(status="invalid")

    reset_token = database_session.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == password_reset_token_hash(raw_token, application_settings))
        .with_for_update()
        .limit(1)
    )
    if reset_token is None:
        return PasswordResetTokenLookup(status="invalid")

    if reset_token.used_at_utc is not None:
        return PasswordResetTokenLookup(status="used", reset_token=reset_token)

    expires_at_utc = _as_utc(reset_token.expires_at_utc)
    if expires_at_utc is None or expires_at_utc <= now_utc():
        return PasswordResetTokenLookup(status="expired", reset_token=reset_token)

    if (
        reset_token.web_user is None
        or reset_token.web_user.disabled
        or reset_token.web_user.archived_at_utc is not None
    ):
        return PasswordResetTokenLookup(status="invalid", reset_token=reset_token)

    return PasswordResetTokenLookup(status="valid", reset_token=reset_token)


def complete_password_reset(
    database_session: Session,
    *,
    reset_token: PasswordResetToken,
    new_password: str,
    confirm_password: str,
) -> WebUser:
    """Apply a valid reset token, update the password, and invalidate sessions."""

    if (
        reset_token.web_user is None
        or reset_token.web_user.disabled
        or reset_token.web_user.archived_at_utc is not None
    ):
        raise WebUserError("This password reset link is invalid or expired.")

    web_user = reset_token.web_user
    change_web_user_password(
        database_session,
        web_user,
        new_password=new_password,
        confirm_password=confirm_password,
    )
    invalidate_web_user_sessions(web_user)
    reset_token.used_at_utc = now_utc()
    return web_user


def record_password_reset_audit(
    database_session: Session,
    *,
    action: str,
    request: Request,
    normalized_email: str | None = None,
    web_user: WebUser | None = None,
    reset_token: PasswordResetToken | None = None,
    details: dict[str, object] | None = None,
    application_settings: Settings = settings,
) -> None:
    """Write one sanitized password-reset audit event."""

    safe_details = dict(details or {})
    if normalized_email:
        safe_details["email_hash"] = password_reset_email_hash(normalized_email, application_settings)
    if web_user is not None:
        safe_details["web_user_id"] = web_user.id
        safe_details["username"] = web_user.username
    if reset_token is not None:
        safe_details["reset_row_id"] = reset_token.id

    record_audit_event(
        database_session,
        actor=web_user.username if web_user is not None else "system",
        action=action,
        request=request,
        details=safe_details,
    )
