"""Tests for America/Detroit time conversion and rounding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from job_logger.time_utils import enforce_minimum_rounded_end, round_to_nearest_quarter_hour, to_local


def test_round_to_nearest_quarter_hour_rounds_forward() -> None:
    """A time 8 minutes after a quarter hour rounds forward."""

    timestamp = datetime(2026, 6, 16, 12, 8, tzinfo=UTC)
    rounded_timestamp = round_to_nearest_quarter_hour(timestamp)

    assert to_local(rounded_timestamp).strftime("%H:%M") == "08:15"


def test_round_to_nearest_quarter_hour_rounds_backward() -> None:
    """A time 7 minutes after a quarter hour rounds backward."""

    timestamp = datetime(2026, 6, 16, 12, 7, tzinfo=UTC)
    rounded_timestamp = round_to_nearest_quarter_hour(timestamp)

    assert to_local(rounded_timestamp).strftime("%H:%M") == "08:00"


def test_enforce_minimum_rounded_end_adds_one_interval() -> None:
    """A very short job still receives at least one 15-minute rounded block."""

    rounded_start = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    rounded_end = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

    assert enforce_minimum_rounded_end(rounded_start, rounded_end) == rounded_start + timedelta(minutes=15)

