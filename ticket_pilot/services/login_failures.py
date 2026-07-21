"""Database-backed login-attempt diagnostics helpers."""

from __future__ import annotations

import ipaddress
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ticket_pilot.logging_config import redact_sensitive_text
from ticket_pilot.models import LoginAttempt, LoginFailureCounter
from ticket_pilot.time_utils import format_local_display

LOGGER = logging.getLogger(__name__)
MAX_USERNAME_LOG_CHARS = 255
MAX_CLIENT_IP_LOG_CHARS = 64
MAX_USER_AGENT_LOG_CHARS = 255
MAX_TEXT_FIELD_CHARS = 512
MAX_COUNTER_USERNAME_CHARS = 255


@dataclass(frozen=True)
class LoginFailureRecord:
    """One sanitized failed-login record loaded from the database."""

    entry_id: str
    created_at_utc: str
    created_at_display: str
    client_ip: str
    enforcement_client_ip: str
    direct_client_ip: str
    x_real_ip: str
    x_forwarded_for: str
    forwarded_proto: str
    host: str
    username: str
    username_length: int
    username_truncated: bool
    password_supplied: bool
    password_length: int
    user_agent: str
    method: str
    path: str
    next_url: str
    reason: str
    failed_count: int
    max_attempts: int
    lockout_applied: bool
    lockout_remaining_seconds: int


@dataclass(frozen=True)
class LoginSuccessRecord:
    """One sanitized successful-login record loaded from the database."""

    created_at_utc: str
    created_at_display: str
    client_ip: str
    direct_client_ip: str
    x_real_ip: str
    x_forwarded_for: str
    forwarded_proto: str
    host: str
    username: str
    user_kind: str
    web_user_id: str
    authentication_method: str
    user_agent: str
    method: str
    path: str


@dataclass(frozen=True)
class LoginRecordPage:
    """One bounded diagnostics page of login records."""

    records: list[LoginFailureRecord] | list[LoginSuccessRecord]
    page: int
    page_size: int
    total_records: int
    total_pages: int
    previous_page: int | None
    next_page: int | None


def _bounded_text(value: object, max_length: int = MAX_TEXT_FIELD_CHARS) -> str:
    """Return single-line text bounded for database storage and UI display."""

    return str(value or "").replace("\x00", "").replace("\r", "\\r").replace("\n", "\\n")[:max_length]


def client_ip_from_request(request: Request | None) -> str:
    """Return the best troubleshooting client IP without using it for authorization."""

    if request is None:
        return "unknown"

    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        first_forwarded_ip = forwarded_for.split(",", maxsplit=1)[0].strip()
        if first_forwarded_ip:
            return _bounded_text(first_forwarded_ip, MAX_CLIENT_IP_LOG_CHARS)

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return _bounded_text(real_ip, MAX_CLIENT_IP_LOG_CHARS)

    if request.client is not None and request.client.host:
        return _bounded_text(request.client.host, MAX_CLIENT_IP_LOG_CHARS)

    return "unknown"


def _normalized_ip_address(value: str) -> str | None:
    """Return a canonical IP string for security decisions, or None."""

    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _first_forwarded_ip(request: Request | None) -> str:
    """Return the first X-Forwarded-For value for trusted proxy contexts."""

    if request is None:
        return ""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    return forwarded_for.split(",", maxsplit=1)[0].strip() if forwarded_for else ""


def enforcement_client_ip_from_request(request: Request | None) -> str:
    """Return the login-throttling IP from sanitized proxy headers or the socket peer.

    The public diagnostics IP can include display-only forwarded data. This
    value is the IP used for local lockout counters and Cloudflare block
    decisions. In Docker deployments, nginx overwrites X-Real-IP and
    X-Forwarded-For before the app sees the request.
    """

    if request is None:
        return "unknown"

    for candidate in (
        request.headers.get("x-real-ip", "").strip(),
        _first_forwarded_ip(request),
    ):
        normalized_ip = _normalized_ip_address(candidate)
        if normalized_ip is not None:
            return _bounded_text(normalized_ip, MAX_CLIENT_IP_LOG_CHARS)

    if request.client is not None and request.client.host:
        return _bounded_text(request.client.host, MAX_CLIENT_IP_LOG_CHARS)

    return "unknown"


def login_counter_username(submitted_username: str) -> str:
    """Return the case-insensitive username key used by local login lockout."""

    return _bounded_text(submitted_username.strip().casefold(), MAX_COUNTER_USERNAME_CHARS)


def _direct_client_ip_from_request(request: Request | None) -> str:
    """Return the socket peer IP observed by the app server."""

    if request is None or request.client is None or not request.client.host:
        return "unknown"
    return _bounded_text(request.client.host, MAX_CLIENT_IP_LOG_CHARS)


def _user_agent_from_request(request: Request | None) -> str:
    """Return a bounded user agent for login troubleshooting."""

    if request is None:
        return ""

    return _bounded_text(request.headers.get("user-agent"), MAX_USER_AGENT_LOG_CHARS)


def _request_header(request: Request | None, header_name: str) -> str:
    """Return a bounded request header value for diagnostics."""

    if request is None:
        return ""
    return _bounded_text(request.headers.get(header_name, ""))


def _base_attempt_values(request: Request, *, event: str, username: str) -> dict[str, Any]:
    """Return common sanitized request metadata for login-attempt rows."""

    return {
        "event": event,
        "created_at_utc": datetime.now(UTC),
        "client_ip": client_ip_from_request(request),
        "enforcement_client_ip": enforcement_client_ip_from_request(request),
        "direct_client_ip": _direct_client_ip_from_request(request),
        "x_real_ip": _request_header(request, "x-real-ip"),
        "x_forwarded_for": _request_header(request, "x-forwarded-for"),
        "forwarded_proto": _request_header(request, "x-forwarded-proto"),
        "host": _request_header(request, "host"),
        "username": _bounded_text(username, MAX_USERNAME_LOG_CHARS),
        "user_agent": _user_agent_from_request(request),
        "method": _bounded_text(request.method, 24),
        "path": _bounded_text(request.url.path),
    }


def _created_at_strings(created_at_utc: datetime) -> tuple[str, str]:
    """Return raw UTC and local display timestamps for a login attempt."""

    created_at_iso = created_at_utc.isoformat()
    return created_at_iso, format_local_display(created_at_utc)


def _failure_record_from_attempt(attempt: LoginAttempt) -> LoginFailureRecord:
    """Convert one failed-login attempt row into a display-safe record."""

    created_at_utc, created_at_display = _created_at_strings(attempt.created_at_utc)
    return LoginFailureRecord(
        entry_id=attempt.id,
        created_at_utc=created_at_utc,
        created_at_display=created_at_display,
        client_ip=attempt.client_ip,
        enforcement_client_ip=attempt.enforcement_client_ip,
        direct_client_ip=attempt.direct_client_ip,
        x_real_ip=attempt.x_real_ip,
        x_forwarded_for=attempt.x_forwarded_for,
        forwarded_proto=attempt.forwarded_proto,
        host=redact_sensitive_text(attempt.host),
        username=redact_sensitive_text(attempt.username),
        username_length=attempt.username_length,
        username_truncated=attempt.username_truncated,
        password_supplied=attempt.password_supplied,
        password_length=attempt.password_length,
        user_agent=redact_sensitive_text(attempt.user_agent),
        method=attempt.method,
        path=attempt.path,
        next_url=redact_sensitive_text(attempt.next_url),
        reason=attempt.reason,
        failed_count=attempt.failed_count,
        max_attempts=attempt.max_attempts,
        lockout_applied=attempt.lockout_applied,
        lockout_remaining_seconds=attempt.lockout_remaining_seconds,
    )


def _success_record_from_attempt(attempt: LoginAttempt) -> LoginSuccessRecord:
    """Convert one successful-login attempt row into a display-safe record."""

    created_at_utc, created_at_display = _created_at_strings(attempt.created_at_utc)
    return LoginSuccessRecord(
        created_at_utc=created_at_utc,
        created_at_display=created_at_display,
        client_ip=attempt.client_ip,
        direct_client_ip=attempt.direct_client_ip,
        x_real_ip=attempt.x_real_ip,
        x_forwarded_for=attempt.x_forwarded_for,
        forwarded_proto=attempt.forwarded_proto,
        host=redact_sensitive_text(attempt.host),
        username=redact_sensitive_text(attempt.username),
        user_kind=attempt.user_kind or "unknown",
        web_user_id=attempt.web_user_id,
        authentication_method=attempt.authentication_method or "password",
        user_agent=redact_sensitive_text(attempt.user_agent),
        method=attempt.method,
        path=attempt.path,
    )


def log_failed_login_attempt(
    database_session: Session,
    request: Request,
    *,
    submitted_username: str,
    submitted_password: str,
    reason: str = "invalid_credentials",
    failed_count: int = 0,
    max_attempts: int = 0,
    lockout_applied: bool = False,
    lockout_remaining_seconds: int = 0,
) -> LoginAttempt:
    """Persist one failed-login attempt with only sanitized metadata.

    Raw submitted passwords are never stored. The row records whether a
    password was supplied and its length so operators can spot brute-force
    patterns without retaining credential material.
    """

    attempt = LoginAttempt(
        succeeded=False,
        **_base_attempt_values(request, event="web_login_failed", username=submitted_username),
        username_length=len(submitted_username),
        username_truncated=len(submitted_username) > MAX_USERNAME_LOG_CHARS,
        password_supplied=bool(submitted_password),
        password_length=len(submitted_password),
        next_url="",
        reason=_bounded_text(reason, 64),
        failed_count=max(int(failed_count), 0),
        max_attempts=max(int(max_attempts), 0),
        lockout_applied=bool(lockout_applied),
        lockout_remaining_seconds=max(int(lockout_remaining_seconds), 0),
    )
    database_session.add(attempt)
    database_session.flush()
    return attempt


def log_successful_login_attempt(
    database_session: Session,
    request: Request,
    *,
    username: str,
    user_kind: str,
    web_user_id: str | None = None,
    authentication_method: str = "password",
) -> LoginAttempt:
    """Persist one successful-login attempt with only sanitized metadata."""

    attempt = LoginAttempt(
        succeeded=True,
        **_base_attempt_values(request, event="web_login_succeeded", username=username),
        user_kind=_bounded_text(user_kind, 64),
        web_user_id=_bounded_text(web_user_id or "", 64),
        authentication_method=_bounded_text(authentication_method, 64),
    )
    database_session.add(attempt)
    database_session.flush()
    return attempt


def increment_login_failure_counter(
    database_session: Session,
    request: Request,
    *,
    submitted_username: str,
) -> int:
    """Increment and return the failed-login count for the enforcement IP and username."""

    client_ip = enforcement_client_ip_from_request(request)
    username = login_counter_username(submitted_username)
    counter = database_session.scalar(
        select(LoginFailureCounter)
        .where(LoginFailureCounter.client_ip == client_ip, LoginFailureCounter.username == username)
        .limit(1)
    )
    current_time = datetime.now(UTC)
    if counter is None:
        counter = LoginFailureCounter(
            client_ip=client_ip,
            username=username,
            failed_count=0,
            created_at_utc=current_time,
            updated_at_utc=current_time,
        )
        database_session.add(counter)

    counter.failed_count += 1
    counter.last_failed_at_utc = current_time
    counter.updated_at_utc = current_time
    database_session.flush()
    return counter.failed_count


def reset_login_failure_counter(
    database_session: Session,
    request: Request,
    *,
    submitted_username: str,
) -> None:
    """Reset failed-login state for the successful enforcement IP and username."""

    client_ip = enforcement_client_ip_from_request(request)
    username = login_counter_username(submitted_username)
    counter = database_session.scalar(
        select(LoginFailureCounter)
        .where(LoginFailureCounter.client_ip == client_ip, LoginFailureCounter.username == username)
        .limit(1)
    )
    if counter is None:
        return

    current_time = datetime.now(UTC)
    counter.failed_count = 0
    counter.last_success_at_utc = current_time
    counter.updated_at_utc = current_time
    database_session.flush()


def _login_attempt_statement(*, succeeded: bool, include_hidden_failures: bool):
    """Return the base query for one login-attempt type."""

    statement = select(LoginAttempt).where(LoginAttempt.succeeded.is_(succeeded))
    if not succeeded and not include_hidden_failures:
        statement = statement.where(LoginAttempt.hidden_at_utc.is_(None))
    return statement.order_by(desc(LoginAttempt.created_at_utc), desc(LoginAttempt.id))


def _paginate_login_attempts(
    database_session: Session,
    *,
    succeeded: bool,
    page: int,
    page_size: int,
) -> LoginRecordPage:
    """Return one bounded page of database-backed login attempts."""

    bounded_page_size = max(1, min(page_size, 100))
    count_statement = select(func.count(LoginAttempt.id)).where(LoginAttempt.succeeded.is_(succeeded))
    if not succeeded:
        count_statement = count_statement.where(LoginAttempt.hidden_at_utc.is_(None))
    total_records = database_session.scalar(count_statement) or 0
    total_pages = max(1, (total_records + bounded_page_size - 1) // bounded_page_size)
    bounded_page = max(1, min(page, total_pages))
    attempts = list(
        database_session.scalars(
            _login_attempt_statement(succeeded=succeeded, include_hidden_failures=False)
            .offset((bounded_page - 1) * bounded_page_size)
            .limit(bounded_page_size)
        )
    )
    if succeeded:
        records: list[LoginSuccessRecord] = [_success_record_from_attempt(attempt) for attempt in attempts]
    else:
        records = [_failure_record_from_attempt(attempt) for attempt in attempts]
    return LoginRecordPage(
        records=records,
        page=bounded_page,
        page_size=bounded_page_size,
        total_records=total_records,
        total_pages=total_pages,
        previous_page=bounded_page - 1 if bounded_page > 1 else None,
        next_page=bounded_page + 1 if bounded_page < total_pages else None,
    )


def read_login_failures_page(
    database_session: Session,
    *,
    page: int = 1,
    page_size: int = 10,
) -> LoginRecordPage:
    """Return one diagnostics page of newest failed-login records."""

    return _paginate_login_attempts(database_session, succeeded=False, page=page, page_size=page_size)


def read_login_successes_page(
    database_session: Session,
    *,
    page: int = 1,
    page_size: int = 10,
) -> LoginRecordPage:
    """Return one diagnostics page of newest successful-login records."""

    return _paginate_login_attempts(database_session, succeeded=True, page=page, page_size=page_size)


def _login_attempt_payload(attempt: LoginAttempt) -> dict[str, Any]:
    """Return one JSONL-safe database login-attempt payload."""

    payload: dict[str, Any] = {
        "event": attempt.event,
        "created_at_utc": attempt.created_at_utc.isoformat(),
        "client_ip": attempt.client_ip,
        "enforcement_client_ip": attempt.enforcement_client_ip,
        "direct_client_ip": attempt.direct_client_ip,
        "x_real_ip": attempt.x_real_ip,
        "x_forwarded_for": attempt.x_forwarded_for,
        "forwarded_proto": attempt.forwarded_proto,
        "host": redact_sensitive_text(attempt.host),
        "username": redact_sensitive_text(attempt.username),
        "user_agent": redact_sensitive_text(attempt.user_agent),
        "method": attempt.method,
        "path": attempt.path,
    }
    if attempt.succeeded:
        payload.update(
            {
                "user_kind": attempt.user_kind,
                "web_user_id": attempt.web_user_id,
                "authentication_method": attempt.authentication_method,
            }
        )
    else:
        payload.update(
            {
                "username_length": attempt.username_length,
                "username_truncated": attempt.username_truncated,
                "password_supplied": attempt.password_supplied,
                "password_length": attempt.password_length,
                "next_url": redact_sensitive_text(attempt.next_url),
                "reason": attempt.reason,
                "failed_count": attempt.failed_count,
                "max_attempts": attempt.max_attempts,
                "lockout_applied": attempt.lockout_applied,
                "lockout_remaining_seconds": attempt.lockout_remaining_seconds,
                "hidden_from_debug": attempt.hidden_at_utc is not None,
            }
        )
    return payload


def login_attempts_jsonl(database_session: Session, *, succeeded: bool) -> str:
    """Return database-backed login attempts as sanitized JSON Lines."""

    lines: list[str] = []
    attempts = database_session.scalars(
        _login_attempt_statement(succeeded=succeeded, include_hidden_failures=True)
    )
    for attempt in attempts:
        lines.append(json.dumps(_login_attempt_payload(attempt), sort_keys=True, separators=(",", ":")))
    return "\n".join(lines) + ("\n" if lines else "")
