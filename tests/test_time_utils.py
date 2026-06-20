"""Tests for America/Detroit time conversion and rounding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from job_logger.time_utils import (
    enforce_minimum_rounded_end,
    format_local_compact_time_range,
    format_local_display,
    format_local_time,
    format_utc_iso,
    parse_local_form_datetime,
    round_end_for_technician,
    round_start_for_technician,
    round_to_nearest_quarter_hour,
    to_local,
)


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


def test_technician_favoring_start_rounds_down_and_stop_rounds_up() -> None:
    """Active work starts round down while active stops round up."""

    timestamp = datetime(2026, 6, 16, 12, 8, tzinfo=UTC)

    assert to_local(round_start_for_technician(timestamp)).strftime("%H:%M") == "08:00"
    assert to_local(round_end_for_technician(timestamp)).strftime("%H:%M") == "08:15"


def test_technician_favoring_end_keeps_exact_quarter_hour() -> None:
    """A stop already on a quarter-hour boundary should not round forward."""

    timestamp = datetime(2026, 6, 16, 12, 15, tzinfo=UTC)

    assert round_end_for_technician(timestamp) == timestamp


def test_enforce_minimum_rounded_end_adds_one_interval() -> None:
    """A very short job still receives at least one 15-minute rounded block."""

    rounded_start = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    rounded_end = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

    assert enforce_minimum_rounded_end(rounded_start, rounded_end) == rounded_start + timedelta(minutes=15)


def test_format_local_time_uses_detroit_twelve_hour_display() -> None:
    """Visible times should be America/Detroit 12-hour values with am/pm."""

    timestamp = datetime(2026, 6, 16, 12, 15, tzinfo=UTC)

    assert format_local_time(timestamp) == "8:15 am"
    assert format_local_display(timestamp) == "Jun 16, 2026 8:15 am"


def test_format_utc_iso_keeps_explicit_utc_offset_for_naive_database_values() -> None:
    """Browser data attributes should not let UTC values parse as local time."""

    timestamp = datetime(2026, 6, 16, 12, 15)

    assert format_utc_iso(timestamp) == "2026-06-16T12:15:00+00:00"


def test_format_local_compact_time_range_uses_detroit_twelve_hour_display() -> None:
    """Compact service-call card ranges should omit spaces around am/pm."""

    start_timestamp = datetime(2026, 6, 16, 20, 0, tzinfo=UTC)
    end_timestamp = datetime(2026, 6, 16, 21, 0, tzinfo=UTC)

    assert format_local_compact_time_range(start_timestamp, end_timestamp) == "4:00pm-5:00pm"


def test_parse_local_form_datetime_accepts_twelve_hour_display() -> None:
    """Review form times posted as am/pm values should convert through Detroit."""

    parsed_timestamp = parse_local_form_datetime("2026-06-16", "8:15 am")

    assert parsed_timestamp == datetime(2026, 6, 16, 12, 15, tzinfo=UTC)


def test_parse_local_form_datetime_handles_noon_and_midnight() -> None:
    """The 12-hour parser should handle the two ambiguous edge hours."""

    parsed_midnight = parse_local_form_datetime("2026-06-16", "12:00 am")
    parsed_noon = parse_local_form_datetime("2026-06-16", "12:00 pm")

    assert parsed_midnight == datetime(2026, 6, 16, 4, 0, tzinfo=UTC)
    assert parsed_noon == datetime(2026, 6, 16, 16, 0, tzinfo=UTC)


def test_parse_local_form_datetime_accepts_legacy_twenty_four_hour_values() -> None:
    """Stale pages and integrations can still submit old HTML time values."""

    parsed_timestamp = parse_local_form_datetime("2026-06-16", "08:15")

    assert parsed_timestamp == datetime(2026, 6, 16, 12, 15, tzinfo=UTC)
