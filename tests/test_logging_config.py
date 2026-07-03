"""Tests for stdout application logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from job_logger.config import load_settings
from job_logger.logging_config import configure_logging


def _remove_job_logger_handlers() -> None:
    """Remove app handlers installed by logging configuration tests."""

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        if getattr(handler, "_job_logger_marker", "") in {"job_logger_app_file", "job_logger_stdout"}:
            root_logger.removeHandler(handler)
            handler.close()


def test_log_level_setting_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOG_LEVEL should accept only the supported app-log levels."""

    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert load_settings().log_level == "DEBUG"

    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with pytest.raises(ValueError, match="LOG_LEVEL must be DEBUG, INFO, WARNING, or ERROR"):
        load_settings()


def test_log_dir_setting_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOG_DIR should enable file logs only when explicitly configured."""

    monkeypatch.delenv("LOG_DIR", raising=False)
    assert load_settings().log_dir is None

    monkeypatch.setenv("LOG_DIR", "/data/logs")
    assert load_settings().log_dir == "/data/logs"


def test_configured_log_level_controls_stdout(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The stdout app log should honor LOG_LEVEL."""

    logger = logging.getLogger("job_logger.tests.logging")
    root_logger = logging.getLogger()
    previous_root_level = root_logger.level
    try:
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        configure_logging(load_settings())
        logger.debug("debug message visible")
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert "debug message visible" in capsys.readouterr().out

        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        configure_logging(load_settings())
        logger.warning("warning message hidden")
        logger.error("error message visible")
        for handler in logging.getLogger().handlers:
            handler.flush()

        log_text = capsys.readouterr().out
        assert "warning message hidden" not in log_text
        assert "error message visible" in log_text
    finally:
        root_logger.setLevel(previous_root_level)
        _remove_job_logger_handlers()


def test_configured_log_dir_writes_redacted_file_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Optional LOG_DIR file logging should use the shared redacting formatter."""

    logger = logging.getLogger("job_logger.tests.file_logging")
    root_logger = logging.getLogger()
    previous_root_level = root_logger.level
    try:
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        monkeypatch.setenv("LOG_DIR", str(tmp_path))
        configure_logging(load_settings())
        logger.info("request api_key=secret-token Authorization: Bearer secret-bearer")
        for handler in logging.getLogger().handlers:
            handler.flush()

        log_file_text = (tmp_path / "job-logger-app.log").read_text(encoding="utf-8")
        assert "job_logger.tests.file_logging" in log_file_text
        assert "api_key=***" in log_file_text
        assert "Authorization: Bearer ***" in log_file_text
        assert "secret-token" not in log_file_text
        assert "secret-bearer" not in log_file_text
    finally:
        root_logger.setLevel(previous_root_level)
        _remove_job_logger_handlers()
