"""Authenticated managed web-user configuration routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from job_logger.database import get_database_session
from job_logger.enums import ThemeMode
from job_logger.models import WebUser
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
    THEME_META_COLORS,
    UserPreferenceError,
    get_theme_for_principal,
    preference_principal_from_session,
    save_theme_for_principal,
)
from job_logger.services.users import WebUserError, change_web_user_password, get_enabled_web_user_by_id_or_raise
from job_logger.ui import template_context, templates

router = APIRouter(prefix="/config", tags=["config"])


def _wants_json_response(request: Request) -> bool:
    """Return whether the browser expects the autosave JSON response."""

    return "application/json" in request.headers.get("accept", "").lower()


def _current_config_web_user(request: Request, database_session: Session) -> WebUser:
    """Return the enabled managed web user allowed to access `/config`."""

    require_authenticated_username(request)
    if current_user_kind(request) != WEB_USER_SESSION_KIND:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managed web-user configuration is required.")
    return get_enabled_web_user_by_id_or_raise(database_session, current_web_user_id(request))


def _current_web_user_preference_principal(request: Request, database_session: Session):
    """Return the current managed web-user preference principal or raise an auth error."""

    _current_config_web_user(request, database_session)
    principal = preference_principal_from_session(request.session)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authenticated user configuration is unavailable.")
    return principal


@router.get("", response_class=HTMLResponse)
def config_page(request: Request, database_session: Session = Depends(get_database_session)) -> Response:
    """Render the managed web-user configuration page."""

    try:
        principal = _current_web_user_preference_principal(request, database_session)
    except WebUserError:
        logout_session(request)
        return RedirectResponse(url="/login", status_code=303)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            logout_session(request)
            return RedirectResponse(url="/login", status_code=303)
        raise

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
) -> Response:
    """Persist managed web-user configuration values."""

    wants_json = _wants_json_response(request)
    try:
        actor = require_authenticated_username(request)
        principal = _current_web_user_preference_principal(request, database_session)
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
        if wants_json:
            return JSONResponse(
                {
                    "theme": user_preference.theme.value,
                    "theme_color": THEME_META_COLORS[user_preference.theme],
                    "message": "Configuration updated.",
                }
            )
    except (HTTPException, UserPreferenceError, WebUserError) as exc:
        database_session.rollback()
        if isinstance(exc, WebUserError):
            logout_session(request)
        if wants_json:
            status_code = exc.status_code if isinstance(exc, HTTPException) else status.HTTP_400_BAD_REQUEST
            return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=status_code)
        raise

    return RedirectResponse(url="/config", status_code=303)


@router.post("/password")
async def change_password(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Change the current managed web user's login password."""

    try:
        actor = require_authenticated_username(request)
        user = _current_config_web_user(request, database_session)
    except WebUserError:
        database_session.rollback()
        logout_session(request)
        return RedirectResponse(url="/login", status_code=303)
    except HTTPException as exc:
        database_session.rollback()
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            logout_session(request)
            return RedirectResponse(url="/login", status_code=303)
        raise

    try:
        form_data = await request.form()
        validate_csrf_token(request, str(form_data.get("csrf_token", "")))
        change_web_user_password(
            database_session,
            user,
            new_password=str(form_data.get("new_password", "")),
            confirm_password=str(form_data.get("confirm_password", "")),
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="user.config.password_changed",
            request=request,
            details={"web_user_id": user.id, "username": user.username},
        )
        database_session.commit()
        add_flash_message(request, "Password changed.", "success")
    except (HTTPException, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/config", status_code=303)
