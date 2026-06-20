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
from job_logger.time_utils import format_local_display

LOGGER = logging.getLogger(__name__)
MAX_USERNAME_LOG_CHARS = 255
MAX_CLIENT_IP_LOG_CHARS = 64
MAX_USER_AGENT_LOG_CHARS = 255


@dataclass(frozen=True)
class LoginFailureRecord:
    """One sanitized failed-login record parsed from the JSONL log file."""

    created_at_utc: str
    created_at_display: str
    client_ip: str
    username: str
    password_supplied: bool
    password_length: int
    user_agent: str


def _bounded_text(value: str | None, max_length: int) -> str:
    """Return single-line text bounded for log storage and UI display."""

    return str(value or "").replace("\r", " ").replace("\n", " ")[:max_length]


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


def _user_agent_from_request(request: Request | None) -> str:
    """Return a bounded user agent for failed-login troubleshooting."""

    if request is None:
        return ""

    return _bounded_text(request.headers.get("user-agent"), MAX_USER_AGENT_LOG_CHARS)


def _record_from_payload(payload: dict[str, Any]) -> LoginFailureRecord | None:
    """Convert one JSON payload from disk into a display-safe record."""

    created_at_utc = str(payload.get("created_at_utc", ""))
    created_at_display = created_at_utc
    try:
        parsed_created_at = datetime.fromisoformat(created_at_utc)
        created_at_display = format_local_display(parsed_created_at)
    except (TypeError, ValueError):
        pass

    try:
        password_length = int(payload.get("password_length", 0))
    except (TypeError, ValueError):
        password_length = 0

    return LoginFailureRecord(
        created_at_utc=created_at_utc,
        created_at_display=created_at_display,
        client_ip=_bounded_text(str(payload.get("client_ip", "unknown")), MAX_CLIENT_IP_LOG_CHARS),
        username=_bounded_text(str(payload.get("username", "")), MAX_USERNAME_LOG_CHARS),
        password_supplied=bool(payload.get("password_supplied", False)),
        password_length=max(password_length, 0),
        user_agent=_bounded_text(str(payload.get("user_agent", "")), MAX_USER_AGENT_LOG_CHARS),
    )


def log_failed_login_attempt(
    request: Request,
    *,
    submitted_username: str,
    submitted_password: str,
    application_settings: Settings = settings,
) -> None:
    """Append one failed-login attempt to the host-mounted JSONL log file.

    Raw submitted passwords are never written. The log records whether a
    password was supplied and its length so operators can spot brute-force
    patterns without retaining credential material.
    """

    log_path = Path(application_settings.login_failure_log_path)
    payload = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "client_ip": client_ip_from_request(request),
        "username": _bounded_text(submitted_username, MAX_USERNAME_LOG_CHARS),
        "password_supplied": bool(submitted_password),
        "password_length": len(submitted_password),
        "user_agent": _user_agent_from_request(request),
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
