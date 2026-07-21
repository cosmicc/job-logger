"""Background app-health checks that send best-effort admin notifications."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from ticket_pilot import database
from ticket_pilot.config import Settings, settings
from ticket_pilot.services.pushover import send_pushover_notification
from ticket_pilot.services.system_health import AppHealthSnapshot, collect_app_health_snapshot

logger = logging.getLogger(__name__)

HealthFingerprint = tuple[tuple[str, str], ...]


@dataclass
class HealthNotificationState:
    """State used to prevent repeated notifications for unchanged health issues."""

    active_fingerprint: HealthFingerprint = ()


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


def notify_if_health_changed(
    snapshot: AppHealthSnapshot,
    state: HealthNotificationState,
    *,
    application_settings: Settings = settings,
) -> str | None:
    """Send a notification for degraded, changed, or restored app health."""

    current_fingerprint = health_snapshot_fingerprint(snapshot)
    previous_fingerprint = state.active_fingerprint
    if current_fingerprint == previous_fingerprint:
        return None

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
        return "degraded" if not previous_fingerprint else "changed"

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
