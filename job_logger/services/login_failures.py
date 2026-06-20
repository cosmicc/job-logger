"""Host-accessible failed-login logging helpers."""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Request

from job_logger.config import Settings, settings
from job_logger.logging_config import redact_sensitive_text
from job_logger.time_utils import format_local_display

LOGGER = logging.getLogger(__name__)
MAX_USERNAME_LOG_CHARS = 255
MAX_CLIENT_IP_LOG_CHARS = 64
MAX_USER_AGENT_LOG_CHARS = 255
MAX_TEXT_FIELD_CHARS = 512


@dataclass(frozen=True)
class LoginFailureRecord:
    """One sanitized failed-login record parsed from the JSONL log file."""

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


def _bounded_text(value: object, max_length: int = MAX_TEXT_FIELD_CHARS) -> str:
    """Return single-line text bounded for log storage and UI display."""

    return str(value or "").replace("\x00", "").replace("\r", "\\r").replace("\n", "\\n")[:max_length]


def client_ip_from_request(request: Request | None) -> str:
    """Return the best troubleshooting client IP without using it for authorization."""

    if request is None:
        return "unknown"

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return _bounded_text(real_ip, MAX_CLIENT_IP_LOG_CHARS)

    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        first_forwarded_ip = forwarded_for.split(",", maxsplit=1)[0].strip()
        if first_forwarded_ip:
            return _bounded_text(first_forwarded_ip, MAX_CLIENT_IP_LOG_CHARS)

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


def _record_from_payload(payload: dict[str, Any]) -> LoginFailureRecord | None:
    """Convert one JSON payload from disk into a display-safe record."""

    created_at_utc = str(payload.get("created_at_utc", ""))
    created_at_display = created_at_utc
    try:
        parsed_created_at = datetime.fromisoformat(created_at_utc)
        created_at_display = format_local_display(parsed_created_at)
    except (TypeError, ValueError):
        pass

    return LoginFailureRecord(
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


def log_failed_login_attempt(
    request: Request,
    *,
    submitted_username: str,
    submitted_password: str,
    reason: str = "invalid_credentials",
    application_settings: Settings = settings,
) -> None:
    """Append one failed-login attempt to the host-mounted JSONL log file.

    Raw submitted passwords are never written. The log records whether a
    password was supplied and its length so operators can spot brute-force
    patterns without retaining credential material.
    """

    log_path = Path(application_settings.login_failure_log_path)
    bounded_username = _bounded_text(submitted_username, MAX_USERNAME_LOG_CHARS)
    payload = {
        "event": "web_login_failed",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "client_ip": client_ip_from_request(request),
        "direct_client_ip": _direct_client_ip_from_request(request),
        "x_real_ip": _request_header(request, "x-real-ip"),
        "x_forwarded_for": _request_header(request, "x-forwarded-for"),
        "forwarded_proto": _request_header(request, "x-forwarded-proto"),
        "host": _request_header(request, "host"),
        "username": bounded_username,
        "username_length": len(submitted_username),
        "username_truncated": len(submitted_username) > MAX_USERNAME_LOG_CHARS,
        "password_supplied": bool(submitted_password),
        "password_length": len(submitted_password),
        "user_agent": _user_agent_from_request(request),
        "method": _bounded_text(request.method, 24),
        "path": _bounded_text(request.url.path),
        "next_url": "",
        "reason": _bounded_text(reason, 64),
        # Job Logger currently records failed login attempts but does not apply
        # an application-level lockout. Keep these explicit for diagnostics so
        # the table schema matches Mileage Logger without implying enforcement.
        "failed_count": 0,
        "max_attempts": 0,
        "lockout_applied": False,
        "lockout_remaining_seconds": 0,
    }

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as login_failure_log_file:
            login_failure_log_file.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            login_failure_log_file.write("\n")
    except OSError as exc:
        LOGGER.warning("Failed to write login failure log at %s: %s", log_path, exc)


def read_recent_login_failures(
    *,
    application_settings: Settings = settings,
    limit: int | None = None,
) -> list[LoginFailureRecord]:
    """Return newest failed-login records parsed from the configured JSONL file."""

    log_path = Path(application_settings.login_failure_log_path)
    row_limit = limit if limit is not None else application_settings.login_failure_debug_rows
    bounded_limit = max(0, row_limit)
    if bounded_limit == 0 or not log_path.exists():
        return []

    recent_lines: deque[str] = deque(maxlen=bounded_limit)
    try:
        with log_path.open("r", encoding="utf-8") as login_failure_log_file:
            for line in login_failure_log_file:
                stripped_line = line.strip()
                if stripped_line:
                    recent_lines.append(stripped_line)
    except OSError as exc:
        LOGGER.warning("Failed to read login failure log at %s: %s", log_path, exc)
        return []

    records: list[LoginFailureRecord] = []
    for raw_line in reversed(recent_lines):
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            record = _record_from_payload(payload)
            if record is not None:
                records.append(record)
    return records
