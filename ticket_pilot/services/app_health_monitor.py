"""Background app-health checks that send best-effort admin notifications."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from ticket_pilot import database
from ticket_pilot.config import Settings, settings
from ticket_pilot.services.pushover import send_pushover_notification
from ticket_pilot.services.system_health import AppHealthSnapshot, collect_app_health_snapshot

logger = logging.getLogger(__name__)

HealthFingerprint = tuple[tuple[str, str], ...]
_acknowledgement_lock = threading.Lock()
_acknowledged_health_fingerprint: HealthFingerprint = ()


@dataclass
class HealthNotificationState:
    """State used to time notifications for the active degraded issue set."""

    active_fingerprint: HealthFingerprint = ()
    last_degraded_notification_at: float | None = None


def health_snapshot_fingerprint(snapshot: AppHealthSnapshot) -> HealthFingerprint:
    """Return a stable issue fingerprint that ignores jittery metric values."""

    return tuple(sorted((issue.code, issue.severity) for issue in snapshot.issues))


def health_snapshot_message(snapshot: AppHealthSnapshot) -> str:
    """Return a bounded human-readable health summary for Pushover."""

    if not snapshot.issues:
        return "All monitored TicketPilot checks are passing."

    lines = [f"{snapshot.status_label}:"]
    for issue in snapshot.issues[:8]:
        lines.append(f"- {issue.label}: {issue.summary}")
    if len(snapshot.issues) > 8:
        lines.append(f"- {len(snapshot.issues) - 8} additional issue(s).")
    return "\n".join(lines)


def acknowledge_health_snapshot(snapshot: AppHealthSnapshot) -> HealthFingerprint:
    """Acknowledge the current degraded issue set until its fingerprint changes."""

    fingerprint = health_snapshot_fingerprint(snapshot)
    if not fingerprint:
        raise ValueError("Only a degraded application-health alert can be acknowledged.")
    global _acknowledged_health_fingerprint
    with _acknowledgement_lock:
        _acknowledged_health_fingerprint = fingerprint
    return fingerprint


def health_snapshot_is_acknowledged(snapshot: AppHealthSnapshot) -> bool:
    """Return whether administrators acknowledged this exact degraded issue set."""

    fingerprint = health_snapshot_fingerprint(snapshot)
    if not fingerprint:
        return False
    with _acknowledgement_lock:
        return fingerprint == _acknowledged_health_fingerprint


def clear_health_acknowledgement() -> None:
    """Clear the process-local health acknowledgement."""

    global _acknowledged_health_fingerprint
    with _acknowledgement_lock:
        _acknowledged_health_fingerprint = ()


def notify_if_health_changed(
    snapshot: AppHealthSnapshot,
    state: HealthNotificationState,
    *,
    application_settings: Settings = settings,
    observed_at: float | None = None,
) -> str | None:
    """Send a notification for degraded, changed, repeated, or restored health."""

    current_fingerprint = health_snapshot_fingerprint(snapshot)
    previous_fingerprint = state.active_fingerprint
    current_observed_at = time.monotonic() if observed_at is None else observed_at
    if current_fingerprint and health_snapshot_is_acknowledged(snapshot):
        # Keep monitoring, but suppress repeats for the exact issue set an
        # administrator has already reviewed.
        state.active_fingerprint = current_fingerprint
        return None
    with _acknowledgement_lock:
        acknowledged_fingerprint = _acknowledged_health_fingerprint
    if acknowledged_fingerprint and acknowledged_fingerprint != current_fingerprint:
        clear_health_acknowledgement()

    if current_fingerprint == previous_fingerprint:
        if not current_fingerprint:
            return None
        reminder_due = (
            state.last_degraded_notification_at is None
            or current_observed_at - state.last_degraded_notification_at
            >= application_settings.pushover_reminder_interval_seconds
        )
        if not reminder_due:
            return None

        priority = 1 if snapshot.severity == "critical" else 0
        send_pushover_notification(
            "TicketPilot health still degraded",
            health_snapshot_message(snapshot),
            priority=priority,
            application_settings=application_settings,
        )
        state.last_degraded_notification_at = current_observed_at
        return "reminder"

    state.active_fingerprint = current_fingerprint
    if current_fingerprint:
        title = "TicketPilot health degraded"
        if previous_fingerprint:
            title = "TicketPilot health changed"
        priority = 1 if snapshot.severity == "critical" else 0
        send_pushover_notification(
            title,
            health_snapshot_message(snapshot),
            priority=priority,
            application_settings=application_settings,
        )
        state.last_degraded_notification_at = current_observed_at
        return "degraded" if not previous_fingerprint else "changed"

    state.last_degraded_notification_at = None
    send_pushover_notification(
        "TicketPilot health restored",
        "All monitored TicketPilot checks are passing again.",
        priority=0,
        application_settings=application_settings,
    )
    return "restored"


def collect_notification_health_snapshot() -> AppHealthSnapshot:
    """Collect one health snapshot using an isolated database session."""

    with database.SessionLocal() as database_session:
        return collect_app_health_snapshot(database_session=database_session)


async def app_health_notification_scheduler(application_settings: Settings = settings) -> None:
    """Run app-health notification checks until the application shuts down."""

    if not application_settings.pushover_notifications_enabled:
        return
    if not application_settings.pushover_configured:
        logger.warning("Pushover health monitor is enabled but Pushover credentials are incomplete.")

    state = HealthNotificationState()
    while True:
        try:
            snapshot = await asyncio.to_thread(collect_notification_health_snapshot)
            await asyncio.to_thread(
                notify_if_health_changed,
                snapshot,
                state,
                application_settings=application_settings,
            )
        except SQLAlchemyError:
            logger.exception("Could not collect database-backed health checks for Pushover notifications.")
        except Exception:
            logger.exception("Unexpected app-health notification monitor failure.")
        await asyncio.sleep(application_settings.app_health_monitor_interval_seconds)
