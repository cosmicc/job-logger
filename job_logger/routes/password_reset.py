"""Self-service managed-user password reset routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from job_logger.config import settings
from job_logger.database import get_database_session
from job_logger.security import add_flash_message, validate_csrf_token
from job_logger.services.login_failures import enforcement_client_ip_from_request
from job_logger.services.mail import send_password_reset_email
from job_logger.services.password_reset import (
    PASSWORD_RESET_GENERIC_MESSAGE,
    PASSWORD_RESET_INVALID_LINK_MESSAGE,
    PASSWORD_RESET_RATE_LIMIT_MESSAGE,
    complete_password_reset,
    consume_account_reset_rate_limit,
    consume_preflight_reset_rate_limits,
    create_password_reset_token,
    find_unique_enabled_web_user_by_email,
    lookup_password_reset_token,
    normalize_password_reset_email,
    password_reset_url,
    record_password_reset_audit,
)
from job_logger.services.turnstile import verify_turnstile_response
from job_logger.services.users import WebUserError
from job_logger.ui import template_context, templates

router = APIRouter(tags=["password-reset"])


def _application_settings(request: Request):
    """Return request-scoped settings for tests and app factories."""

    return getattr(request.app.state, "application_settings", settings)


def _require_password_reset_enabled(request: Request) -> None:
    """Hide reset routes unless the feature flag is enabled."""

    if not _application_settings(request).password_reset_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")


def _reset_status_action(reset_status: str) -> str:
    """Map reset-token lookup status to an audit action."""

    if reset_status == "expired":
        return "auth.password_reset.token_expired"
    if reset_status == "used":
        return "auth.password_reset.token_used"
    return "auth.password_reset.token_invalid"


def _render_invalid_reset_link(
    request: Request,
    *,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> Response:
    """Render the generic invalid reset-link page."""

    return templates.TemplateResponse(
        request,
        "reset_password.html",
        template_context(
            request,
            reset_link_valid=False,
            invalid_link_message=PASSWORD_RESET_INVALID_LINK_MESSAGE,
        ),
        status_code=status_code,
    )


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request) -> Response:
    """Render the password-reset request page."""

    _require_password_reset_enabled(request)
    application_settings = _application_settings(request)
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        template_context(
            request,
            reset_message=PASSWORD_RESET_GENERIC_MESSAGE,
            turnstile_enabled=application_settings.turnstile_enabled,
            turnstile_site_key=application_settings.turnstile_site_key,
        ),
    )


@router.post("/forgot-password")
async def request_password_reset(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Accept a non-enumerating password-reset request."""

    _require_password_reset_enabled(request)
    application_settings = _application_settings(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    try:
        normalized_email = normalize_password_reset_email(str(form_data.get("email", "")))
    except WebUserError as exc:
        add_flash_message(request, str(exc), "error")
        return RedirectResponse(url="/forgot-password", status_code=303)

    rate_limit = consume_preflight_reset_rate_limits(
        database_session,
        request,
        normalized_email=normalized_email,
        application_settings=application_settings,
    )
    if rate_limit.limited:
        record_password_reset_audit(
            database_session,
            action="auth.password_reset.rate_limited",
            request=request,
            normalized_email=normalized_email,
            details={
                "scope": rate_limit.scope,
                "limit": rate_limit.limit,
                "window_seconds": rate_limit.window_seconds,
                "stage": "preflight",
            },
            application_settings=application_settings,
        )
        database_session.commit()
        add_flash_message(request, PASSWORD_RESET_RATE_LIMIT_MESSAGE, "error")
        return RedirectResponse(url="/forgot-password", status_code=303)

    turnstile_result = await verify_turnstile_response(
        response_token=str(form_data.get("cf-turnstile-response", "")),
        remote_ip=enforcement_client_ip_from_request(request),
        application_settings=application_settings,
    )
    if not turnstile_result.success:
        record_password_reset_audit(
            database_session,
            action="auth.password_reset.turnstile_failed",
            request=request,
            normalized_email=normalized_email,
            details={"error_codes": turnstile_result.error_codes},
            application_settings=application_settings,
        )
        database_session.commit()
        add_flash_message(request, "Human verification failed. Try again.", "error")
        return RedirectResponse(url="/forgot-password", status_code=303)

    record_password_reset_audit(
        database_session,
        action="auth.password_reset.requested",
        request=request,
        normalized_email=normalized_email,
        application_settings=application_settings,
    )
    web_user = find_unique_enabled_web_user_by_email(database_session, normalized_email=normalized_email)
    if web_user is None:
        record_password_reset_audit(
            database_session,
            action="auth.password_reset.email_not_sent",
            request=request,
            normalized_email=normalized_email,
            details={"result": "no_unique_enabled_user"},
            application_settings=application_settings,
        )
        database_session.commit()
        add_flash_message(request, PASSWORD_RESET_GENERIC_MESSAGE, "success")
        return RedirectResponse(url="/forgot-password", status_code=303)

    account_rate_limit = consume_account_reset_rate_limit(database_session, web_user=web_user)
    if account_rate_limit.limited:
        record_password_reset_audit(
            database_session,
            action="auth.password_reset.rate_limited",
            request=request,
            normalized_email=normalized_email,
            web_user=web_user,
            details={
                "scope": account_rate_limit.scope,
                "limit": account_rate_limit.limit,
                "window_seconds": account_rate_limit.window_seconds,
                "stage": "account",
            },
            application_settings=application_settings,
        )
        database_session.commit()
        add_flash_message(request, PASSWORD_RESET_RATE_LIMIT_MESSAGE, "error")
        return RedirectResponse(url="/forgot-password", status_code=303)

    raw_token, reset_token = create_password_reset_token(
        database_session,
        request,
        web_user=web_user,
        sent_to_email=normalized_email,
        application_settings=application_settings,
    )
    delivery_result = await asyncio.to_thread(
        send_password_reset_email,
        recipient_email=normalized_email,
        reset_url=password_reset_url(raw_token, application_settings),
        application_settings=application_settings,
    )
    if delivery_result.succeeded:
        record_password_reset_audit(
            database_session,
            action="auth.password_reset.email_sent",
            request=request,
            normalized_email=normalized_email,
            web_user=web_user,
            reset_token=reset_token,
            details={"provider": delivery_result.provider},
            application_settings=application_settings,
        )
    else:
        reset_token.delivery_error = delivery_result.safe_error
        record_password_reset_audit(
            database_session,
            action="auth.password_reset.email_not_sent",
            request=request,
            normalized_email=normalized_email,
            web_user=web_user,
            reset_token=reset_token,
            details={
                "result": "delivery_failed",
                "provider": delivery_result.provider,
                "delivery_error": delivery_result.safe_error or "unknown",
            },
            application_settings=application_settings,
        )

    database_session.commit()
    add_flash_message(request, PASSWORD_RESET_GENERIC_MESSAGE, "success")
    return RedirectResponse(url="/forgot-password", status_code=303)


@router.get("/reset-password/{raw_token}", response_class=HTMLResponse)
def reset_password_page(
    raw_token: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Render a password-reset form for a valid link."""

    _require_password_reset_enabled(request)
    lookup = lookup_password_reset_token(
        database_session,
        raw_token,
        application_settings=_application_settings(request),
    )
    if lookup.status != "valid":
        record_password_reset_audit(
            database_session,
            action=_reset_status_action(lookup.status),
            request=request,
            web_user=lookup.reset_token.web_user if lookup.reset_token is not None else None,
            reset_token=lookup.reset_token,
            details={"result": lookup.status},
            application_settings=_application_settings(request),
        )
        database_session.commit()
        return _render_invalid_reset_link(request)

    return templates.TemplateResponse(
        request,
        "reset_password.html",
        template_context(request, reset_link_valid=True),
    )


@router.post("/reset-password/{raw_token}")
async def complete_reset_password(
    raw_token: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Replace the managed-user password when the reset link is valid."""

    _require_password_reset_enabled(request)
    application_settings = _application_settings(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    lookup = lookup_password_reset_token(database_session, raw_token, application_settings=application_settings)
    if lookup.status != "valid" or lookup.reset_token is None:
        record_password_reset_audit(
            database_session,
            action=_reset_status_action(lookup.status),
            request=request,
            web_user=lookup.reset_token.web_user if lookup.reset_token is not None else None,
            reset_token=lookup.reset_token,
            details={"result": lookup.status},
            application_settings=application_settings,
        )
        database_session.commit()
        return _render_invalid_reset_link(request)

    try:
        web_user = complete_password_reset(
            database_session,
            reset_token=lookup.reset_token,
            new_password=str(form_data.get("new_password", "")),
            confirm_password=str(form_data.get("confirm_password", "")),
        )
    except WebUserError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")
        return templates.TemplateResponse(
            request,
            "reset_password.html",
            template_context(request, reset_link_valid=True),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    record_password_reset_audit(
        database_session,
        action="auth.password_reset.token_used",
        request=request,
        web_user=web_user,
        reset_token=lookup.reset_token,
        details={"result": "completed"},
        application_settings=application_settings,
    )
    record_password_reset_audit(
        database_session,
        action="auth.password_reset.completed",
        request=request,
        web_user=web_user,
        reset_token=lookup.reset_token,
        details={"sessions_invalidated": True},
        application_settings=application_settings,
    )
    database_session.commit()
    add_flash_message(request, "Password reset. Sign in with your new password.", "success")
    return RedirectResponse(url="/login", status_code=303)
