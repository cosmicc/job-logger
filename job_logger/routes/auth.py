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
from job_logger.services.login_failures import log_successful_login_attempt, reset_login_failure_counter
from job_logger.services.login_protection import (
    current_login_lockout,
    record_failed_login_attempt_and_maybe_block,
    record_local_login_lockout,
)
from job_logger.services.users import authenticate_web_user_with_status, mark_web_user_login_succeeded
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
    lockout_state = current_login_lockout(
        database_session,
        request,
        submitted_username=submitted_username,
    )
    if lockout_state.locked:
        record_local_login_lockout(
            database_session,
            request,
            submitted_username=submitted_username,
            submitted_password=submitted_password,
            lockout_state=lockout_state,
        )
        database_session.commit()
        remaining_minutes = max((lockout_state.remaining_seconds + 59) // 60, 1)
        add_flash_message(
            request,
            f"Too many failed sign-in attempts. Try again in about {remaining_minutes} minutes.",
            "error",
        )
        return RedirectResponse(url="/login", status_code=303)

    if authenticate_username(submitted_username) and verify_password(submitted_password):
        reset_login_failure_counter(database_session, request, submitted_username=submitted_username)
        login_session(request, submitted_username)
        log_successful_login_attempt(
            request,
            username=submitted_username,
            user_kind="super_admin",
            authentication_method="password",
        )
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

    web_user_authentication = authenticate_web_user_with_status(
        database_session,
        submitted_username,
        submitted_password,
    )
    web_user = web_user_authentication.user
    if web_user is not None:
        reset_login_failure_counter(database_session, request, submitted_username=web_user.username)
        mark_web_user_login_succeeded(web_user)
        login_web_user_session(request, username=web_user.username, web_user_id=web_user.id)
        log_successful_login_attempt(
            request,
            username=web_user.username,
            user_kind="web_user",
            web_user_id=web_user.id,
            authentication_method="password",
        )
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

    if web_user_authentication.disabled_user is not None:
        disabled_user = web_user_authentication.disabled_user
        record_audit_event(
            database_session,
            actor=disabled_user.username,
            action="auth.login.failed",
            request=request,
            details={
                "username": disabled_user.username,
                "user_kind": "web_user",
                "web_user_id": disabled_user.id,
                "reason": "account_disabled",
            },
        )
        record_failed_login_attempt_and_maybe_block(
            database_session,
            request,
            submitted_username=submitted_username,
            submitted_password=submitted_password,
            reason="account_disabled",
        )
        database_session.commit()
        add_flash_message(request, "This user account is disabled. Contact the administrator.", "error")
        return RedirectResponse(url="/login", status_code=303)

    record_audit_event(
        database_session,
        actor=submitted_username or "unknown",
        action="auth.login.failed",
        request=request,
        details={"username": submitted_username, "reason": "invalid_credentials"},
    )
    record_failed_login_attempt_and_maybe_block(
        database_session,
        request,
        submitted_username=submitted_username,
        submitted_password=submitted_password,
        reason="invalid_credentials",
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
