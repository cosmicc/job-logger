"""Centralized timezone and 15-minute rounding utilities."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# LOCAL_TIMEZONE is the required user-facing timezone for EST/EDT handling.
LOCAL_TIMEZONE = ZoneInfo("America/Detroit")

# ROUNDING_INTERVAL_MINUTES is the required local review increment.
ROUNDING_INTERVAL_MINUTES = 15


def now_utc() -> datetime:
    """Return the current aware UTC timestamp."""

    return datetime.now(UTC)


def ensure_utc(timestamp: datetime) -> datetime:
    """Return an aware UTC timestamp from any aware or naive datetime."""

    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)

    return timestamp.astimezone(UTC)


def to_local(timestamp: datetime) -> datetime:
    """Convert a UTC or aware timestamp to America/Detroit local time."""

    return ensure_utc(timestamp).astimezone(LOCAL_TIMEZONE)


def local_date_for(timestamp: datetime) -> date:
    """Return the America/Detroit calendar date for a timestamp."""

    return to_local(timestamp).date()


def round_to_nearest_quarter_hour(timestamp: datetime) -> datetime:
    """Round a timestamp to the closest 15-minute interval in America/Detroit.

    Rounding is performed in local wall-clock time because that is how users
    review work entries. The result is converted back to UTC before storage.
    """

    local_timestamp = to_local(timestamp)
    local_midnight = local_timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_since_midnight = (local_timestamp - local_midnight).total_seconds()
    interval_seconds = ROUNDING_INTERVAL_MINUTES * 60
    rounded_intervals = int((seconds_since_midnight + (interval_seconds / 2)) // interval_seconds)
    rounded_local_timestamp = local_midnight + timedelta(seconds=rounded_intervals * interval_seconds)
    return rounded_local_timestamp.astimezone(UTC)


def enforce_minimum_rounded_end(rounded_start_utc: datetime, rounded_end_utc: datetime) -> datetime:
    """Ensure a rounded end produces at least one 15-minute duration block."""

    safe_rounded_start_utc = ensure_utc(rounded_start_utc)
    safe_rounded_end_utc = ensure_utc(rounded_end_utc)
    if safe_rounded_end_utc <= safe_rounded_start_utc:
        return safe_rounded_start_utc + timedelta(minutes=ROUNDING_INTERVAL_MINUTES)

    return safe_rounded_end_utc


def rounded_duration_minutes(rounded_start_utc: datetime, rounded_end_utc: datetime) -> int:
    """Return the rounded duration in whole minutes."""

    duration = ensure_utc(rounded_end_utc) - ensure_utc(rounded_start_utc)
    return int(duration.total_seconds() // 60)


def parse_local_form_datetime(local_date: str, local_time: str) -> datetime:
    """Parse HTML date/time fields as America/Detroit and return UTC."""

    parsed_date = date.fromisoformat(local_date)
    parsed_time = time.fromisoformat(local_time)
    local_timestamp = datetime.combine(parsed_date, parsed_time, tzinfo=LOCAL_TIMEZONE)
    return local_timestamp.astimezone(UTC)


def format_local_date(timestamp: datetime | None) -> str:
    """Format a timestamp for an HTML date input."""

    if timestamp is None:
        return ""

    return to_local(timestamp).date().isoformat()


def format_local_time(timestamp: datetime | None) -> str:
    """Format a timestamp for an HTML time input."""

    if timestamp is None:
        return ""

    return to_local(timestamp).strftime("%H:%M")


def format_local_display(timestamp: datetime | None) -> str:
    """Format a timestamp for readable America/Detroit display."""

    if timestamp is None:
        return "Not set"

    return to_local(timestamp).strftime("%b %-d, %Y %-I:%M %p")


def format_autotask_datetime(timestamp: datetime) -> str:
    """Format UTC timestamps for Autotask REST payloads."""

    return ensure_utc(timestamp).replace(microsecond=0).isoformat().replace("+00:00", "Z")

