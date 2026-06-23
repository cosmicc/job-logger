"""Runtime file logging configuration for Job Logger."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from job_logger.config import Settings
from job_logger.time_utils import to_local

SENSITIVE_QUERY_VALUE_RE = re.compile(
    r"(?i)(\b(?:api_key|apikey|access_token|refresh_token|token|client_secret|password)=)"
    r"([^&\s\"']+)"
)
SENSITIVE_BEARER_VALUE_RE = re.compile(r"(?i)(authorization:\s*bearer\s+)([^\s\"']+)")


def redact_sensitive_text(value: str) -> str:
    """Redact common secret-bearing substrings before writing diagnostic logs."""

    redacted_query_values = SENSITIVE_QUERY_VALUE_RE.sub(r"\1***", value)
    return SENSITIVE_BEARER_VALUE_RE.sub(r"\1***", redacted_query_values)


class LocalTimezoneFormatter(logging.Formatter):
    """Format log records with America/Detroit timestamps and redaction."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if "\n" not in formatted:
            return redact_sensitive_text(formatted)

        line_prefix = f"{self.formatTime(record, self.datefmt)} {record.levelname} [{record.name}] "
        lines = formatted.splitlines()
        prefixed_lines = "\n".join([lines[0], *(f"{line_prefix}{line}" for line in lines[1:])])
        return redact_sensitive_text(prefixed_lines)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timestamp = to_local(datetime.fromtimestamp(record.created, tz=UTC))
        if datefmt:
            return timestamp.strftime(datefmt)
        return timestamp.isoformat(timespec="seconds")


def configure_logging(application_settings: Settings) -> Path:
    """Configure host-mounted application logging and return the app log path."""

    log_dir = Path(application_settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    app_log_path = log_dir / "app.log"
    configured_log_level = logging.getLevelName(application_settings.log_level)
    formatter = LocalTimezoneFormatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S %Z",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(configured_log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    for handler in root_logger.handlers:
        if getattr(handler, "_job_logger_marker", "") == "job_logger_app_file":
            handler_path = Path(getattr(handler, "baseFilename", ""))
            if handler_path == app_log_path:
                handler.setLevel(configured_log_level)
                handler.setFormatter(formatter)
                return app_log_path
            root_logger.removeHandler(handler)
            handler.close()

    file_handler = RotatingFileHandler(app_log_path, maxBytes=1_000_000, backupCount=3)
    file_handler.setLevel(configured_log_level)
    file_handler.setFormatter(formatter)
    file_handler._job_logger_marker = "job_logger_app_file"  # type: ignore[attr-defined]
    root_logger.addHandler(file_handler)
    return app_log_path
