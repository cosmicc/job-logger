"""Template rendering helpers shared by route modules."""

from __future__ import annotations

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from job_logger import time_utils
from job_logger.config import settings
from job_logger.enums import ThemeMode
from job_logger.security import csrf_token, current_user_kind, current_username, is_super_admin_session, pop_flash_messages
from job_logger.services.preferences import THEME_META_COLORS, get_theme_for_session
from job_logger.version import APP_VERSION

# templates is the single Jinja environment used by all server-rendered pages.
templates = Jinja2Templates(directory="job_logger/templates")

# Filters keep timezone formatting out of templates and routes.
templates.env.filters["local_display"] = time_utils.format_local_display
templates.env.filters["local_date"] = time_utils.format_local_date
templates.env.filters["local_time"] = time_utils.format_local_time


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

    context: dict[str, object] = {
        "request": request,
        "csrf_token": csrf_token(request),
        "current_username": current_username(request),
        "current_user_kind": current_user_kind(request),
        "current_is_super_admin": is_super_admin_session(request.session),
        "current_theme": current_theme.value,
        "theme_color": THEME_META_COLORS[current_theme],
        "flash_messages": pop_flash_messages(request),
        "ai_cleanup_enabled": settings.ai_cleanup_enabled,
        "static_asset_version": APP_VERSION,
    }
    context.update(extra_context)
    return context
