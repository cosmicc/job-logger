"""Local application authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from job_logger.database import get_database_session
from job_logger.security import (
    SUPER_ADMIN_SESSION_KIND,
    add_flash_message,
    authenticate_username,
    current_user_kind,
    current_username,
    login_session,
    login_web_user_session,
    logout_session,
    validate_csrf_token,
    verify_password,
)
from job_logger.services.audit import record_audit_event
from job_logger.services.login_failures import log_failed_login_attempt
from job_logger.services.users import authenticate_web_user
from job_logger.ui import template_context, templates

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    """Render the local app login page."""

    if current_username(request):
        redirect_url = "/users" if current_user_kind(request) == SUPER_ADMIN_SESSION_KIND else "/home"
        return RedirectResponse(url=redirect_url, status_code=303)

    return templates.TemplateResponse(request, "login.html", template_context(request))


@router.post("/login")
async def login(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Authenticate the local application user."""

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    submitted_username = str(form_data.get("username", "")).strip()
    submitted_password = str(form_data.get("password", ""))
    if authenticate_username(submitted_username) and verify_password(submitted_password):
        login_session(request, submitted_username)
        record_audit_event(
            database_session,
            actor=submitted_username,
            action="auth.login.succeeded",
            request=request,
            details={"username": submitted_username, "user_kind": "super_admin"},
        )
        database_session.commit()
        add_flash_message(request, "Signed in.", "success")
        return RedirectResponse(url="/users", status_code=303)

    web_user = authenticate_web_user(database_session, submitted_username, submitted_password)
    if web_user is not None:
        login_web_user_session(request, username=web_user.username, web_user_id=web_user.id)
        record_audit_event(
            database_session,
            actor=web_user.username,
            action="auth.login.succeeded",
            request=request,
            details={"username": web_user.username, "user_kind": "web_user", "web_user_id": web_user.id},
        )
        database_session.commit()
        add_flash_message(request, "Signed in.", "success")
        return RedirectResponse(url="/home", status_code=303)

    record_audit_event(
        database_session,
        actor=submitted_username or "unknown",
        action="auth.login.failed",
        request=request,
        details={"username": submitted_username},
    )
    log_failed_login_attempt(
        request,
        submitted_username=submitted_username,
        submitted_password=submitted_password,
    )
    database_session.commit()
    add_flash_message(request, "Invalid username or password.", "error")
    return RedirectResponse(url="/login", status_code=303)


@router.post("/logout")
async def logout(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Clear the local app session."""

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    actor = current_username(request) or "unknown"
    record_audit_event(database_session, actor=actor, action="auth.logout", request=request)
    database_session.commit()
    logout_session(request)
    return RedirectResponse(url="/login", status_code=303)
