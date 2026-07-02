"""Tests for stdout application logging configuration."""

from __future__ import annotations

import logging

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
