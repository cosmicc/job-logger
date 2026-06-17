"""Template rendering helpers shared by route modules."""

from __future__ import annotations

from fastapi import Request
from fastapi.templating import Jinja2Templates

from job_logger import time_utils
from job_logger.services.autotask import AutotaskConnectivityResult, test_cached_autotask_connectivity_for_start
from job_logger.security import csrf_token, current_username, pop_flash_messages

# templates is the single Jinja environment used by all server-rendered pages.
templates = Jinja2Templates(directory="job_logger/templates")

# Filters keep timezone formatting out of templates and routes.
templates.env.filters["local_display"] = time_utils.format_local_display
templates.env.filters["local_date"] = time_utils.format_local_date
templates.env.filters["local_time"] = time_utils.format_local_time


def _read_autotask_connectivity_status() -> AutotaskConnectivityResult:
    """Return the safest possible cached connectivity result for UI badges."""

    try:
        return test_cached_autotask_connectivity_for_start()
    except Exception:
        # We keep header rendering deterministic even when the connectivity checker
        # itself fails by returning a non-secret, safe fallback.
        return AutotaskConnectivityResult(
            provider="autotask",
            available=False,
            summary="Autotask connectivity status is not available.",
            checked_operations=(),
            tips=(),
            failed_operation=None,
        )


def template_context(request: Request, **extra_context: object) -> dict[str, object]:
    """Build common context for all templates."""

    autotask_connectivity = _read_autotask_connectivity_status()

    context: dict[str, object] = {
        "request": request,
        "csrf_token": csrf_token(request),
        "current_username": current_username(request),
        "flash_messages": pop_flash_messages(request),
        "autotask_api_status": {
            "available": autotask_connectivity.available,
            "provider": autotask_connectivity.provider,
            "label": "Online" if autotask_connectivity.available else "Offline",
        },
    }
    context.update(extra_context)
    return context
