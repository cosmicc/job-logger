"""Template rendering helpers shared by route modules."""

from __future__ import annotations

from fastapi import Request
from fastapi.templating import Jinja2Templates

from job_logger import time_utils
from job_logger.security import csrf_token, current_username, pop_flash_messages

# templates is the single Jinja environment used by all server-rendered pages.
templates = Jinja2Templates(directory="job_logger/templates")

# Filters keep timezone formatting out of templates and routes.
templates.env.filters["local_display"] = time_utils.format_local_display
templates.env.filters["local_date"] = time_utils.format_local_date
templates.env.filters["local_time"] = time_utils.format_local_time


def template_context(request: Request, **extra_context: object) -> dict[str, object]:
    """Build common context for all templates."""

    context: dict[str, object] = {
        "request": request,
        "csrf_token": csrf_token(request),
        "current_username": current_username(request),
        "flash_messages": pop_flash_messages(request),
    }
    context.update(extra_context)
    return context

