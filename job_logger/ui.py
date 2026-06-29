"""Template rendering helpers shared by route modules."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from job_logger import time_utils
from job_logger.config import settings
from job_logger.enums import ThemeMode
from job_logger.security import (
    csrf_token,
    current_user_kind,
    current_username,
    is_super_admin_session,
    pop_flash_messages,
    session_has_debug_access,
)
from job_logger.services.preferences import THEME_META_COLORS, get_theme_for_session
from job_logger.services.system_health import AppHealthSnapshot, collect_app_health_snapshot
from job_logger.version import APP_VERSION

# templates is the single Jinja environment used by all server-rendered pages.
templates = Jinja2Templates(directory="job_logger/templates")
STATIC_ASSET_DIR = Path(__file__).resolve().parent / "static"

# Filters keep timezone formatting out of templates and routes.
templates.env.filters["local_display"] = time_utils.format_local_display
templates.env.filters["local_date"] = time_utils.format_local_date
templates.env.filters["local_time"] = time_utils.format_local_time
templates.env.filters["utc_iso"] = time_utils.format_utc_iso
templates.env.filters["job_date_label"] = time_utils.format_job_date_label
templates.env.filters["weekday_name"] = time_utils.format_weekday_name


@lru_cache(maxsize=1)
def static_asset_version() -> str:
    """Return a content-derived static asset version for cache busting."""

    digest = hashlib.sha256(APP_VERSION.encode("utf-8"))
    for asset_path in sorted(STATIC_ASSET_DIR.rglob("*")):
        if not asset_path.is_file():
            continue
        digest.update(asset_path.relative_to(STATIC_ASSET_DIR).as_posix().encode("utf-8"))
        digest.update(asset_path.read_bytes())
    return f"{APP_VERSION}-{digest.hexdigest()[:12]}"


def template_context(
    request: Request,
    *,
    database_session: Session | None = None,
    **extra_context: object,
) -> dict[str, object]:
    """Build common context for all templates."""

    current_theme = ThemeMode.DARK
    if database_session is not None and current_username(request):
        current_theme = get_theme_for_session(database_session, request.session)
    current_can_access_debug = False
    app_health_snapshot = AppHealthSnapshot(issues=())
    if database_session is not None and current_username(request):
        current_can_access_debug = session_has_debug_access(request.session, database_session)
        if current_can_access_debug:
            app_health_snapshot = collect_app_health_snapshot()

    context: dict[str, object] = {
        "request": request,
        "csrf_token": csrf_token(request),
        "current_username": current_username(request),
        "current_user_kind": current_user_kind(request),
        "current_is_super_admin": is_super_admin_session(request.session),
        "current_can_access_debug": current_can_access_debug,
        "app_health_snapshot": app_health_snapshot,
        "app_health_degraded": app_health_snapshot.degraded,
        "app_health_alert_label": app_health_snapshot.alert_label,
        "current_theme": current_theme.value,
        "theme_color": THEME_META_COLORS[current_theme],
        "flash_messages": pop_flash_messages(request),
        "ai_cleanup_enabled": settings.ai_cleanup_enabled,
        "dev_build": settings.dev_build,
        "app_version": APP_VERSION,
        "static_asset_version": static_asset_version(),
    }
    context.update(extra_context)
    return context
