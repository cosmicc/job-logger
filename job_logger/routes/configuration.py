"""Authenticated per-user configuration routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from job_logger.database import get_database_session
from job_logger.enums import ThemeMode
from job_logger.security import (
    WEB_USER_SESSION_KIND,
    add_flash_message,
    current_user_kind,
    current_web_user_id,
    logout_session,
    require_authenticated_username,
    validate_csrf_token,
)
from job_logger.services.audit import record_audit_event
from job_logger.services.preferences import (
    UserPreferenceError,
    get_theme_for_principal,
    preference_principal_from_session,
    save_theme_for_principal,
)
from job_logger.services.users import WebUserError, get_enabled_web_user_by_id_or_raise
from job_logger.ui import template_context, templates

router = APIRouter(prefix="/config", tags=["config"])


def _current_preference_principal_or_redirect(request: Request, database_session: Session):
    """Return the current preference principal or raise an auth error."""

    require_authenticated_username(request)
    if current_user_kind(request) == WEB_USER_SESSION_KIND:
        get_enabled_web_user_by_id_or_raise(database_session, current_web_user_id(request))
    principal = preference_principal_from_session(request.session)
    if principal is None:
        raise HTTPException(status_code=403, detail="Authenticated user configuration is unavailable.")
    return principal


@router.get("", response_class=HTMLResponse)
def config_page(request: Request, database_session: Session = Depends(get_database_session)) -> Response:
    """Render the authenticated user's configuration page."""

    try:
        principal = _current_preference_principal_or_redirect(request, database_session)
    except (HTTPException, WebUserError):
        logout_session(request)
        return RedirectResponse(url="/login", status_code=303)

    current_theme = get_theme_for_principal(database_session, principal.key)
    return templates.TemplateResponse(
        request,
        "config.html",
        template_context(
            request,
            database_session=database_session,
            config_principal_label=principal.label,
            selected_theme=current_theme.value,
            theme_options=[
                (ThemeMode.DARK.value, "Dark"),
                (ThemeMode.LIGHT.value, "Light"),
            ],
        ),
    )


@router.post("")
async def save_config(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Persist the authenticated user's configuration values."""

    actor = require_authenticated_username(request)
    try:
        principal = _current_preference_principal_or_redirect(request, database_session)
        form_data = await request.form()
        validate_csrf_token(request, str(form_data.get("csrf_token", "")))
        user_preference = save_theme_for_principal(
            database_session,
            principal_key=principal.key,
            theme=str(form_data.get("theme", "")),
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="user.config.updated",
            request=request,
            details={"principal_key": principal.key, "theme": user_preference.theme.value},
        )
        database_session.commit()
        add_flash_message(request, "Configuration saved.", "success")
    except (HTTPException, UserPreferenceError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/config", status_code=303)
