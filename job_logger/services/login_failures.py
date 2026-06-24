"""Host-accessible login-attempt logging helpers."""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_logger.config import Settings, settings
from job_logger.logging_config import redact_sensitive_text
from job_logger.models import LoginFailureCounter
from job_logger.time_utils import format_local_display

LOGGER = logging.getLogger(__name__)
MAX_USERNAME_LOG_CHARS = 255
MAX_CLIENT_IP_LOG_CHARS = 64
MAX_USER_AGENT_LOG_CHARS = 255
MAX_TEXT_FIELD_CHARS = 512


@dataclass(frozen=True)
class LoginFailureRecord:
    """One sanitized failed-login record parsed from the JSONL log file."""

    entry_id: str
    created_at_utc: str
    created_at_display: str
    client_ip: str
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
    """One sanitized successful-login record parsed from the JSONL log file."""

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
    """Return single-line text bounded for log storage and UI display."""

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


def _direct_client_ip_from_request(request: Request | None) -> str:
    """Return the socket peer IP observed by the app server."""

    if request is None or request.client is None or not request.client.host:
        return "unknown"
    return _bounded_text(request.client.host, MAX_CLIENT_IP_LOG_CHARS)


def _user_agent_from_request(request: Request | None) -> str:
    """Return a bounded user agent for failed-login troubleshooting."""

    if request is None:
        return ""

    return _bounded_text(request.headers.get("user-agent"), MAX_USER_AGENT_LOG_CHARS)


def _request_header(request: Request | None, header_name: str) -> str:
    """Return a bounded request header value for diagnostics."""

    if request is None:
        return ""
    return _bounded_text(request.headers.get(header_name, ""))


def _payload_integer(payload: dict[str, Any], key: str) -> int:
    """Read a non-negative integer from a JSON payload."""

    try:
        return max(int(payload.get(key) or 0), 0)
    except (TypeError, ValueError):
        return 0


def _entry_id_from_line(line: str) -> str:
    """Return a stable identifier for one raw failed-login JSONL line."""

    return sha256(line.encode("utf-8", errors="replace")).hexdigest()


def _created_at_display_from_payload(payload: dict[str, Any]) -> tuple[str, str]:
    """Return raw UTC and local display timestamps from a log payload."""

    created_at_utc = str(payload.get("created_at_utc", ""))
    created_at_display = created_at_utc
    try:
        parsed_created_at = datetime.fromisoformat(created_at_utc)
        created_at_display = format_local_display(parsed_created_at)
    except (TypeError, ValueError):
        pass
    return created_at_utc, created_at_display


def _record_from_payload(payload: dict[str, Any]) -> LoginFailureRecord | None:
    """Convert one JSON payload from disk into a display-safe record."""

    created_at_utc, created_at_display = _created_at_display_from_payload(payload)

    return LoginFailureRecord(
        entry_id=_bounded_text(str(payload.get("_entry_id", "")), 64),
        created_at_utc=created_at_utc,
        created_at_display=created_at_display,
        client_ip=_bounded_text(str(payload.get("client_ip", "unknown")), MAX_CLIENT_IP_LOG_CHARS),
        direct_client_ip=_bounded_text(str(payload.get("direct_client_ip", "")), MAX_CLIENT_IP_LOG_CHARS),
        x_real_ip=_bounded_text(str(payload.get("x_real_ip", "")), MAX_CLIENT_IP_LOG_CHARS),
        x_forwarded_for=_bounded_text(str(payload.get("x_forwarded_for", ""))),
        forwarded_proto=_bounded_text(str(payload.get("forwarded_proto", "")), 64),
        host=redact_sensitive_text(_bounded_text(str(payload.get("host", "")))),
        username=redact_sensitive_text(_bounded_text(str(payload.get("username", "")), MAX_USERNAME_LOG_CHARS)),
        username_length=_payload_integer(payload, "username_length"),
        username_truncated=bool(payload.get("username_truncated", False)),
        password_supplied=bool(payload.get("password_supplied", False)),
        password_length=_payload_integer(payload, "password_length"),
        user_agent=redact_sensitive_text(_bounded_text(str(payload.get("user_agent", "")), MAX_USER_AGENT_LOG_CHARS)),
        method=_bounded_text(str(payload.get("method", "")), 24),
        path=_bounded_text(str(payload.get("path", ""))),
        next_url=redact_sensitive_text(_bounded_text(str(payload.get("next_url", "")))),
        reason=_bounded_text(str(payload.get("reason", "invalid_credentials")), 64),
        failed_count=_payload_integer(payload, "failed_count"),
        max_attempts=_payload_integer(payload, "max_attempts"),
        lockout_applied=bool(payload.get("lockout_applied", False)),
        lockout_remaining_seconds=_payload_integer(payload, "lockout_remaining_seconds"),
    )


def _success_record_from_payload(payload: dict[str, Any]) -> LoginSuccessRecord | None:
    """Convert one successful-login JSON payload into a display-safe record."""

    created_at_utc, created_at_display = _created_at_display_from_payload(payload)
    return LoginSuccessRecord(
        created_at_utc=created_at_utc,
        created_at_display=created_at_display,
        client_ip=_bounded_text(str(payload.get("client_ip", "unknown")), MAX_CLIENT_IP_LOG_CHARS),
        direct_client_ip=_bounded_text(str(payload.get("direct_client_ip", "")), MAX_CLIENT_IP_LOG_CHARS),
        x_real_ip=_bounded_text(str(payload.get("x_real_ip", "")), MAX_CLIENT_IP_LOG_CHARS),
        x_forwarded_for=_bounded_text(str(payload.get("x_forwarded_for", ""))),
        forwarded_proto=_bounded_text(str(payload.get("forwarded_proto", "")), 64),
        host=redact_sensitive_text(_bounded_text(str(payload.get("host", "")))),
        username=redact_sensitive_text(_bounded_text(str(payload.get("username", "")), MAX_USERNAME_LOG_CHARS)),
        user_kind=_bounded_text(str(payload.get("user_kind", "unknown")), 64),
        web_user_id=_bounded_text(str(payload.get("web_user_id", "")), 64),
        authentication_method=_bounded_text(str(payload.get("authentication_method", "password")), 64),
        user_agent=redact_sensitive_text(_bounded_text(str(payload.get("user_agent", "")), MAX_USER_AGENT_LOG_CHARS)),
        method=_bounded_text(str(payload.get("method", "")), 24),
        path=_bounded_text(str(payload.get("path", ""))),
    )


def _base_request_payload(request: Request, *, event: str, username: str) -> dict[str, Any]:
    """Return common sanitized request metadata for login attempt logs."""

    return {
        "event": event,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "client_ip": client_ip_from_request(request),
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


def _append_jsonl_payload(log_path: Path, payload: dict[str, Any], *, log_description: str) -> None:
    """Append one sanitized JSONL payload, creating the log directory if needed."""

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as login_log_file:
            login_log_file.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            login_log_file.write("\n")
    except OSError as exc:
        LOGGER.warning("Failed to write %s at %s: %s", log_description, log_path, exc)


def log_failed_login_attempt(
    request: Request,
    *,
    submitted_username: str,
    submitted_password: str,
    reason: str = "invalid_credentials",
    failed_count: int = 0,
    max_attempts: int = 0,
    lockout_applied: bool = False,
    lockout_remaining_seconds: int = 0,
    application_settings: Settings = settings,
) -> None:
    """Append one failed-login attempt to the host-mounted JSONL log file.

    Raw submitted passwords are never written. The log records whether a
    password was supplied and its length so operators can spot brute-force
    patterns without retaining credential material.
    """

    log_path = Path(application_settings.login_failure_log_path)
    payload = {
        **_base_request_payload(request, event="web_login_failed", username=submitted_username),
        "username_length": len(submitted_username),
        "username_truncated": len(submitted_username) > MAX_USERNAME_LOG_CHARS,
        "password_supplied": bool(submitted_password),
        "password_length": len(submitted_password),
        "next_url": "",
        "reason": _bounded_text(reason, 64),
        "failed_count": max(int(failed_count), 0),
        "max_attempts": max(int(max_attempts), 0),
        "lockout_applied": bool(lockout_applied),
        "lockout_remaining_seconds": max(int(lockout_remaining_seconds), 0),
    }
    _append_jsonl_payload(log_path, payload, log_description="login failure log")


def log_successful_login_attempt(
    request: Request,
    *,
    username: str,
    user_kind: str,
    web_user_id: str | None = None,
    authentication_method: str = "password",
    application_settings: Settings = settings,
) -> None:
    """Append one successful-login attempt to the host-mounted JSONL log file."""

    log_path = Path(application_settings.login_success_log_path)
    payload = {
        **_base_request_payload(request, event="web_login_succeeded", username=username),
        "user_kind": _bounded_text(user_kind, 64),
        "web_user_id": _bounded_text(web_user_id or "", 64),
        "authentication_method": _bounded_text(authentication_method, 64),
    }
    _append_jsonl_payload(log_path, payload, log_description="login success log")


def _read_recent_payloads(log_path: Path, row_limit: int) -> list[dict[str, Any]]:
    """Return newest JSON objects from a JSONL file."""

    bounded_limit = max(0, row_limit)
    if bounded_limit == 0 or not log_path.exists():
        return []

    recent_lines: deque[str] = deque(maxlen=bounded_limit)
    try:
        with log_path.open("r", encoding="utf-8") as login_log_file:
            for line in login_log_file:
                stripped_line = line.strip()
                if stripped_line:
                    recent_lines.append(stripped_line)
    except OSError as exc:
        LOGGER.warning("Failed to read login log at %s: %s", log_path, exc)
        return []

    payloads: list[dict[str, Any]] = []
    for raw_line in reversed(recent_lines):
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payload["_entry_id"] = _entry_id_from_line(raw_line)
            payloads.append(payload)
    return payloads


def increment_login_failure_counter(
    database_session: Session,
    request: Request,
) -> int:
    """Increment and return the consecutive failed-login count for the request IP."""

    client_ip = client_ip_from_request(request)
    counter = database_session.scalar(
        select(LoginFailureCounter)
        .where(LoginFailureCounter.client_ip == client_ip)
        .limit(1)
    )
    current_time = datetime.now(UTC)
    if counter is None:
        counter = LoginFailureCounter(
            client_ip=client_ip,
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
) -> None:
    """Reset consecutive failed-login state after a successful local login."""

    client_ip = client_ip_from_request(request)
    counter = database_session.scalar(
        select(LoginFailureCounter)
        .where(LoginFailureCounter.client_ip == client_ip)
        .limit(1)
    )
    if counter is None:
        return

    current_time = datetime.now(UTC)
    counter.failed_count = 0
    counter.last_success_at_utc = current_time
    counter.updated_at_utc = current_time
    database_session.flush()


def _paginate_login_records(
    records: list[LoginFailureRecord] | list[LoginSuccessRecord],
    *,
    page: int,
    page_size: int,
) -> LoginRecordPage:
    """Return one bounded page object for diagnostics login tables."""

    bounded_page_size = max(1, min(page_size, 100))
    total_records = len(records)
    total_pages = max(1, (total_records + bounded_page_size - 1) // bounded_page_size)
    bounded_page = max(1, min(page, total_pages))
    start_index = (bounded_page - 1) * bounded_page_size
    page_records = records[start_index : start_index + bounded_page_size]
    return LoginRecordPage(
        records=page_records,
        page=bounded_page,
        page_size=bounded_page_size,
        total_records=total_records,
        total_pages=total_pages,
        previous_page=bounded_page - 1 if bounded_page > 1 else None,
        next_page=bounded_page + 1 if bounded_page < total_pages else None,
    )


def read_recent_login_failures(
    *,
    application_settings: Settings = settings,
    limit: int | None = None,
    hidden_entry_ids: set[str] | None = None,
) -> list[LoginFailureRecord]:
    """Return newest failed-login records parsed from the configured JSONL file."""

    log_path = Path(application_settings.login_failure_log_path)
    row_limit = limit if limit is not None else application_settings.login_failure_debug_rows
    hidden_ids = hidden_entry_ids or set()
    records: list[LoginFailureRecord] = []
    for payload in _read_recent_payloads(log_path, row_limit):
        record = _record_from_payload(payload)
        if record is not None:
            if record.entry_id in hidden_ids:
                continue
            records.append(record)
    return records


def read_recent_login_successes(
    *,
    application_settings: Settings = settings,
    limit: int | None = None,
) -> list[LoginSuccessRecord]:
    """Return newest successful-login records parsed from the configured JSONL file."""

    log_path = Path(application_settings.login_success_log_path)
    row_limit = limit if limit is not None else application_settings.login_failure_debug_rows
    records: list[LoginSuccessRecord] = []
    for payload in _read_recent_payloads(log_path, row_limit):
        record = _success_record_from_payload(payload)
        if record is not None:
            records.append(record)
    return records


def read_login_failures_page(
    *,
    application_settings: Settings = settings,
    page: int = 1,
    page_size: int = 10,
    hidden_entry_ids: set[str] | None = None,
) -> LoginRecordPage:
    """Return one diagnostics page of newest failed-login records."""

    return _paginate_login_records(
        read_recent_login_failures(
            application_settings=application_settings,
            hidden_entry_ids=hidden_entry_ids,
        ),
        page=page,
        page_size=page_size,
    )


def read_login_successes_page(
    *,
    application_settings: Settings = settings,
    page: int = 1,
    page_size: int = 10,
) -> LoginRecordPage:
    """Return one diagnostics page of newest successful-login records."""

    return _paginate_login_records(
        read_recent_login_successes(application_settings=application_settings),
        page=page,
        page_size=page_size,
    )
