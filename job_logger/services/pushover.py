"""Best-effort Pushover notifications for application health changes."""

from __future__ import annotations

import logging

import httpx

from job_logger.config import Settings, settings

logger = logging.getLogger(__name__)


def send_pushover_notification(
    title: str,
    message: str,
    *,
    priority: int = 0,
    application_settings: Settings = settings,
) -> bool:
    """Send one Pushover notification without exposing configured secrets."""

    if not application_settings.pushover_notifications_enabled:
        return False
    if not application_settings.pushover_configured:
        logger.warning("Pushover notifications are enabled but PUSHOVER_USER_KEY or PUSHOVER_APP_KEY is missing.")
        return False

    payload = {
        "token": application_settings.pushover_app_key,
        "user": application_settings.pushover_user_key,
        "title": title,
        "message": message,
        "priority": str(priority),
    }
    try:
        response = httpx.post(
            application_settings.pushover_api_url,
            data=payload,
            timeout=application_settings.pushover_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Could not send Pushover notification title=%s", title)
        return False

    return True
