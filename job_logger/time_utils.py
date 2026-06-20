"""Centralized timezone and 15-minute rounding utilities."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# LOCAL_TIMEZONE is the required user-facing timezone for EST/EDT handling.
LOCAL_TIMEZONE = ZoneInfo("America/Detroit")

# ROUNDING_INTERVAL_MINUTES is the required local review increment.
ROUNDING_INTERVAL_MINUTES = 15

# TWELVE_HOUR_TIME_PATTERN parses the user-facing review time format. Keeping
# the parser centralized avoids duplicating AM/PM edge cases in routes or
# service code while still accepting old HTML time-input values for compatibility.
TWELVE_HOUR_TIME_PATTERN = re.compile(r"^\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<period>[aApP])\.?[mM]\.?\s*$")


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


def local_day_bounds_utc(local_day: date) -> tuple[datetime, datetime]:
    """Return the UTC half-open bounds for one America/Detroit calendar day."""

    local_day_start = datetime.combine(local_day, time.min, tzinfo=LOCAL_TIMEZONE)
    local_next_day_start = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=LOCAL_TIMEZONE)
    return local_day_start.astimezone(UTC), local_next_day_start.astimezone(UTC)


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


def _round_to_quarter_hour_boundary(timestamp: datetime, *, round_up: bool) -> datetime:
    """Round a timestamp to a quarter-hour boundary in local wall-clock time."""

    local_timestamp = to_local(timestamp)
    local_midnight = local_timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = local_timestamp - local_midnight
    elapsed_microseconds = (
        (elapsed.days * 24 * 60 * 60 + elapsed.seconds) * 1_000_000
    ) + elapsed.microseconds
    interval_microseconds = ROUNDING_INTERVAL_MINUTES * 60 * 1_000_000
    rounded_intervals = elapsed_microseconds // interval_microseconds
    if round_up and elapsed_microseconds % interval_microseconds:
        rounded_intervals += 1

    rounded_local_timestamp = local_midnight + timedelta(
        microseconds=rounded_intervals * interval_microseconds
    )
    return rounded_local_timestamp.astimezone(UTC)


def round_start_for_technician(timestamp: datetime) -> datetime:
    """Round a start timestamp down to the prior quarter hour."""

    return _round_to_quarter_hour_boundary(timestamp, round_up=False)


def round_end_for_technician(timestamp: datetime) -> datetime:
    """Round an end timestamp up to the next quarter hour."""

    return _round_to_quarter_hour_boundary(timestamp, round_up=True)


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
    parsed_time = parse_local_form_time(local_time)
    local_timestamp = datetime.combine(parsed_date, parsed_time, tzinfo=LOCAL_TIMEZONE)
    return local_timestamp.astimezone(UTC)


def parse_local_form_time(local_time: str) -> time:
    """Parse user-facing America/Detroit time values from review forms.

    New rendered forms use 12-hour text such as ``8:15 am`` so users never see
    24-hour time. The older ``HH:MM`` format remains accepted for compatibility
    with tests, browser autofill, and any stale pages open during deployment.
    """

    normalized_time = local_time.strip()
    twelve_hour_match = TWELVE_HOUR_TIME_PATTERN.match(normalized_time)
    if twelve_hour_match:
        parsed_hour = int(twelve_hour_match.group("hour"))
        parsed_minute = int(twelve_hour_match.group("minute"))
        parsed_period = twelve_hour_match.group("period").lower()
        if parsed_hour < 1 or parsed_hour > 12 or parsed_minute > 59:
            raise ValueError("Time must be a valid 12-hour value.")

        if parsed_period == "a":
            hour_24 = 0 if parsed_hour == 12 else parsed_hour
            return time(hour=hour_24, minute=parsed_minute)

        hour_24 = 12 if parsed_hour == 12 else parsed_hour + 12
        return time(hour=hour_24, minute=parsed_minute)

    return time.fromisoformat(normalized_time)


def format_local_date(timestamp: datetime | None) -> str:
    """Format a timestamp for an HTML date input."""

    if timestamp is None:
        return ""

    return to_local(timestamp).date().isoformat()


def format_local_time(timestamp: datetime | None) -> str:
    """Format a timestamp for user-facing America/Detroit time display."""

    if timestamp is None:
        return ""

    return format_time_for_display(to_local(timestamp).time())


def format_local_compact_time(timestamp: datetime | None) -> str:
    """Format a local display time without the space before am/pm."""

    return format_local_time(timestamp).replace(" ", "")


def format_local_compact_time_range(start_timestamp: datetime | None, end_timestamp: datetime | None) -> str:
    """Format a concise local time range for compact service-call cards."""

    safe_start_time = format_local_compact_time(start_timestamp)
    safe_end_time = format_local_compact_time(end_timestamp)
    if safe_start_time and safe_end_time:
        return f"{safe_start_time}-{safe_end_time}"

    return safe_start_time or safe_end_time


def format_local_display(timestamp: datetime | None) -> str:
    """Format a timestamp for readable America/Detroit display."""

    if timestamp is None:
        return "Not set"

    local_timestamp = to_local(timestamp)
    return f"{local_timestamp.strftime('%b')} {local_timestamp.day}, {local_timestamp.year} {format_time_for_display(local_timestamp.time())}"


def format_time_for_display(local_time: time) -> str:
    """Return a 12-hour lower-case am/pm display string."""

    hour_24 = local_time.hour
    hour_12 = hour_24 % 12 or 12
    period = "am" if hour_24 < 12 else "pm"
    return f"{hour_12}:{local_time.minute:02d} {period}"


def format_autotask_datetime(timestamp: datetime) -> str:
    """Format UTC timestamps for Autotask REST payloads."""

    return ensure_utc(timestamp).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_utc_iso(timestamp: datetime | None) -> str:
    """Format a timestamp as explicit UTC ISO text for browser data attributes."""

    if timestamp is None:
        return ""

    return ensure_utc(timestamp).isoformat()
