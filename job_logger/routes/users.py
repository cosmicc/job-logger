"""Super-admin routes for managing database-backed web users."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_logger.database import get_database_session
from job_logger.models import Job, WebAuthnCredential, WebUser
from job_logger.security import add_flash_message, require_super_admin, validate_csrf_token
from job_logger.services.audit import record_audit_event
from job_logger.services.autotask import AutotaskSubmissionError, get_autotask_provider, resource_name_for_display
from job_logger.services.mail import MailDeliveryResult, send_password_reset_email, send_welcome_email
from job_logger.services.password_reset import create_password_reset_token, password_reset_url
from job_logger.services.support_contact import application_settings_from_request
from job_logger.services.users import (
    WebUserError,
    create_web_user,
    delete_or_disable_web_user,
    get_web_user_by_id_or_raise,
    list_web_users,
    normalize_autotask_resource_id,
    normalize_optional_autotask_role_id,
    update_web_user,
)
from job_logger.ui import template_context, templates

router = APIRouter(prefix="/users", tags=["users"])
WELCOME_EMAIL_FORM_FIELD = "send_welcome_email"


@dataclass(frozen=True)
class WebUserListRow:
    """Template row for one managed web user and related account metadata."""

    # user is the editable managed account.
    user: WebUser

    # job_count is used to explain whether delete will disable instead.
    job_count: int

    # passkey_count is display-only Device sign-in setup metadata.
    passkey_count: int


def _job_counts_by_user(database_session: Session) -> dict[str, int]:
    """Return job counts keyed by managed web-user ID."""

    rows = database_session.execute(select(Job.web_user_id, func.count(Job.id)).group_by(Job.web_user_id)).all()
    return {
        str(web_user_id): int(job_count)
        for web_user_id, job_count in rows
        if web_user_id is not None
    }


def _passkey_counts_by_user(database_session: Session) -> dict[str, int]:
    """Return passkey counts keyed by managed web-user ID."""

    rows = database_session.execute(
        select(WebAuthnCredential.web_user_id, func.count(WebAuthnCredential.id)).group_by(
            WebAuthnCredential.web_user_id
        )
    ).all()
    return {
        str(web_user_id): int(passkey_count)
        for web_user_id, passkey_count in rows
        if web_user_id is not None
    }


async def _form_values(request: Request) -> dict[str, str]:
    """Return submitted form values after CSRF validation."""

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    return {key: str(value) for key, value in form_data.items()}


@router.get("", response_class=HTMLResponse)
def users_page(request: Request, database_session: Session = Depends(get_database_session)) -> Response:
    """Render the super-admin web-user manager."""

    try:
        require_super_admin(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)

    job_counts = _job_counts_by_user(database_session)
    passkey_counts = _passkey_counts_by_user(database_session)
    rows = [
        WebUserListRow(
            user=user,
            job_count=job_counts.get(user.id, 0),
            passkey_count=passkey_counts.get(user.id, 0),
        )
        for user in list_web_users(database_session)
    ]
    return templates.TemplateResponse(
        request,
        "users.html",
        template_context(request, database_session=database_session, user_rows=rows),
    )


@router.get("/autotask-resources")
def autotask_resource_options(request: Request, query: str = "") -> JSONResponse:
    """Return safe Autotask resource options for super-admin user setup."""

    try:
        require_super_admin(request)
    except HTTPException as exc:
        return JSONResponse({"detail": str(exc.detail)}, status_code=exc.status_code)

    try:
        resource_options = get_autotask_provider().search_resources(query)
    except AutotaskSubmissionError as exc:
        return JSONResponse({"detail": str(exc), "resources": []}, status_code=400)

    return JSONResponse(
        {
            "resources": [
                {
                    "resource_id": resource_option.resource_id,
                    "resource_name": resource_name_for_display(resource_option.resource_name)
                    or f"Resource {resource_option.resource_id}",
                    "first_name": resource_option.first_name,
                    "last_name": resource_option.last_name,
                    "email": resource_option.email,
                }
                for resource_option in resource_options
            ],
        }
    )


@router.get("/autotask-resource-roles")
def autotask_resource_role_options(request: Request, resource_id: str = "") -> JSONResponse:
    """Return active Autotask service-desk role options for one resource."""

    try:
        require_super_admin(request)
        safe_resource_id = normalize_autotask_resource_id(resource_id)
        role_options = get_autotask_provider().list_resource_service_desk_roles(safe_resource_id)
    except (HTTPException, AutotaskSubmissionError, WebUserError) as exc:
        return JSONResponse({"detail": str(getattr(exc, "detail", exc)), "roles": []}, status_code=getattr(exc, "status_code", 400))

    return JSONResponse(
        {
            "roles": [
                {
                    "role_id": role_option.role_id,
                    "name": role_option.name,
                    "label": role_option.label,
                    "is_default": role_option.is_default,
                }
                for role_option in role_options
            ],
        }
    )


def _validated_default_service_desk_role_id(form_values: dict[str, str]) -> int | None:
    """Validate a submitted default role against the selected Autotask resource."""

    role_id = normalize_optional_autotask_role_id(form_values.get("autotask_default_service_desk_role_id"))
    if role_id is None:
        return None

    resource_id = normalize_autotask_resource_id(form_values.get("autotask_resource_id"))
    role_options = get_autotask_provider().list_resource_service_desk_roles(resource_id)
    if not any(role_option.role_id == role_id for role_option in role_options):
        raise WebUserError("Default service desk role must be an active role for the selected Autotask resource.")

    return role_id


def _welcome_email_failure(*, provider: str, safe_error: str) -> MailDeliveryResult:
    """Return a consistent failed welcome-email outcome for skipped sends."""

    return MailDeliveryResult(succeeded=False, provider=provider, safe_error=safe_error)


def _record_user_mail_outcome(
    database_session: Session,
    *,
    actor: str,
    request: Request,
    user: WebUser,
    delivery_result: MailDeliveryResult,
    sent_action: str,
    failed_action: str,
    extra_details: dict[str, object] | None = None,
) -> None:
    """Audit the safe outcome of a super-admin requested user email."""

    details: dict[str, object] = {
        "web_user_id": user.id,
        "username": user.username,
        "email_saved": user.email is not None,
        "provider": delivery_result.provider,
        "safe_error": delivery_result.safe_error,
    }
    details.update(extra_details or {})

    record_audit_event(
        database_session,
        actor=actor,
        action=sent_action if delivery_result.succeeded else failed_action,
        request=request,
        details=details,
    )


async def _deliver_welcome_email_for_user(
    database_session: Session,
    *,
    actor: str,
    request: Request,
    user: WebUser,
    success_message: str,
    failure_prefix: str,
    success_category: str = "success",
    failure_category: str = "error",
) -> MailDeliveryResult:
    """Send and audit a super-admin requested welcome email."""

    application_settings = application_settings_from_request(request)
    if user.disabled:
        delivery_result = _welcome_email_failure(
            provider=application_settings.mail_mode,
            safe_error="Welcome email was not sent because the new account is disabled.",
        )
    else:
        delivery_result = await asyncio.to_thread(
            send_welcome_email,
            recipient_email=user.email or "",
            full_name=user.full_name,
            username=user.username,
            application_settings=application_settings,
        )

    _record_user_mail_outcome(
        database_session,
        actor=actor,
        request=request,
        user=user,
        delivery_result=delivery_result,
        sent_action="user.web.welcome_email_sent",
        failed_action="user.web.welcome_email_failed",
    )
    database_session.commit()
    if delivery_result.succeeded:
        add_flash_message(request, success_message, success_category)
    else:
        safe_error = delivery_result.safe_error or "Unknown mail delivery error."
        add_flash_message(
            request,
            f"{failure_prefix} {safe_error}",
            failure_category,
        )
    return delivery_result


def _absolute_public_base_url_is_configured(app_public_base_url: str) -> bool:
    """Return whether the configured public URL can be used in account emails."""

    parsed_url = urlparse(app_public_base_url.strip())
    return parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc)


async def _send_password_reset_email_for_user(
    database_session: Session,
    *,
    actor: str,
    request: Request,
    user: WebUser,
) -> None:
    """Create and send a super-admin initiated password-reset link."""

    application_settings = application_settings_from_request(request)
    reset_token = None
    if user.disabled:
        delivery_result = MailDeliveryResult(
            succeeded=False,
            provider=application_settings.mail_mode,
            safe_error="Password reset email was not sent because the account is disabled.",
        )
    elif not user.email:
        delivery_result = MailDeliveryResult(
            succeeded=False,
            provider=application_settings.mail_mode,
            safe_error="A user email address is required to send a password reset email.",
        )
    elif not _absolute_public_base_url_is_configured(application_settings.app_public_base_url):
        delivery_result = MailDeliveryResult(
            succeeded=False,
            provider=application_settings.mail_mode,
            safe_error="APP_PUBLIC_BASE_URL must be an absolute http or https URL to send a password reset email.",
        )
    else:
        raw_token, reset_token = create_password_reset_token(
            database_session,
            request,
            web_user=user,
            sent_to_email=user.email,
            application_settings=application_settings,
        )
        delivery_result = await asyncio.to_thread(
            send_password_reset_email,
            recipient_email=user.email,
            reset_url=password_reset_url(raw_token, application_settings),
            application_settings=application_settings,
        )
        if not delivery_result.succeeded:
            reset_token.delivery_error = delivery_result.safe_error

    _record_user_mail_outcome(
        database_session,
        actor=actor,
        request=request,
        user=user,
        delivery_result=delivery_result,
        sent_action="user.web.password_reset_email_sent",
        failed_action="user.web.password_reset_email_failed",
        extra_details={"reset_row_id": reset_token.id} if reset_token is not None else None,
    )
    database_session.commit()
    if delivery_result.succeeded:
        add_flash_message(request, "Password reset email sent.", "email-success")
    else:
        safe_error = delivery_result.safe_error or "Unknown mail delivery error."
        add_flash_message(request, f"Password reset email was not sent: {safe_error}", "email-error")


@router.post("")
async def add_user(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Create a managed web user from the super-admin page."""

    try:
        actor = require_super_admin(request)
        form_values = await _form_values(request)
        welcome_email_requested = WELCOME_EMAIL_FORM_FIELD in form_values
        result = create_web_user(
            database_session,
            full_name=form_values.get("full_name"),
            username=form_values.get("username"),
            password=form_values.get("password"),
            autotask_resource_id=form_values.get("autotask_resource_id"),
            autotask_default_service_desk_role_id=_validated_default_service_desk_role_id(form_values),
            email=form_values.get("autotask_resource_email"),
            disabled="disabled" in form_values,
            is_admin="is_admin" in form_values,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="user.web.restored" if result.restored_archived_user else "user.web.created",
            request=request,
            details={
                "web_user_id": result.user.id,
                "username": result.user.username,
                "disabled": result.user.disabled,
                "is_admin": result.user.is_admin,
                "autotask_resource_id": result.user.autotask_resource_id,
                "autotask_default_service_desk_role_id": result.user.autotask_default_service_desk_role_id,
                "email_saved": result.user.email is not None,
                "claimed_unowned_job_count": result.claimed_unowned_job_count,
                "restored_archived_user": result.restored_archived_user,
            },
        )
        database_session.commit()
        if result.restored_archived_user:
            created_message = "User restored from hidden history for this Autotask resource ID."
        elif result.claimed_unowned_job_count:
            created_message = f"User created. Assigned {result.claimed_unowned_job_count} existing jobs to this first web user."
        else:
            created_message = "User created."
        if welcome_email_requested:
            await _deliver_welcome_email_for_user(
                database_session,
                actor=actor,
                request=request,
                user=result.user,
                success_message=f"{created_message} Welcome email sent.",
                failure_prefix=f"{created_message} Welcome email was not sent:",
            )
        else:
            add_flash_message(request, created_message, "success")
    except (HTTPException, AutotaskSubmissionError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/users", status_code=303)


@router.post("/{user_id}/password-reset-email")
async def send_user_password_reset_email(
    user_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Send a password-reset link email to one managed web user."""

    try:
        actor = require_super_admin(request)
        await _form_values(request)
        user = get_web_user_by_id_or_raise(database_session, user_id)
        await _send_password_reset_email_for_user(
            database_session,
            actor=actor,
            request=request,
            user=user,
        )
    except (HTTPException, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/users", status_code=303)


@router.post("/{user_id}/welcome-email")
async def send_user_welcome_email(
    user_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Resend the welcome email to one managed web user."""

    try:
        actor = require_super_admin(request)
        await _form_values(request)
        user = get_web_user_by_id_or_raise(database_session, user_id)
        await _deliver_welcome_email_for_user(
            database_session,
            actor=actor,
            request=request,
            user=user,
            success_message="Welcome email sent.",
            failure_prefix="Welcome email was not sent:",
            success_category="email-success",
            failure_category="email-error",
        )
    except (HTTPException, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/users", status_code=303)


@router.post("/{user_id}/update")
async def edit_user(
    user_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Update editable managed-user fields."""

    try:
        actor = require_super_admin(request)
        form_values = await _form_values(request)
        user = get_web_user_by_id_or_raise(database_session, user_id)
        update_web_user(
            database_session,
            user,
            full_name=form_values.get("full_name"),
            username=form_values.get("username"),
            password=form_values.get("password") or None,
            autotask_resource_id=form_values.get("autotask_resource_id"),
            autotask_default_service_desk_role_id=_validated_default_service_desk_role_id(form_values),
            email=form_values.get("autotask_resource_email"),
            disabled="disabled" in form_values,
            is_admin="is_admin" in form_values,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="user.web.updated",
            request=request,
            details={
                "web_user_id": user.id,
                "username": user.username,
                "disabled": user.disabled,
                "is_admin": user.is_admin,
                "autotask_resource_id": user.autotask_resource_id,
                "autotask_default_service_desk_role_id": user.autotask_default_service_desk_role_id,
                "email_saved": user.email is not None,
                "password_changed": bool(form_values.get("password")),
            },
        )
        database_session.commit()
        add_flash_message(request, "User updated.", "success")
    except (HTTPException, AutotaskSubmissionError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/users", status_code=303)


@router.post("/{user_id}/delete")
async def delete_user(
    user_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Delete a managed user or hide it when linked jobs must be preserved."""

    try:
        actor = require_super_admin(request)
        await _form_values(request)
        user = get_web_user_by_id_or_raise(database_session, user_id)
        username = user.username
        result = delete_or_disable_web_user(database_session, user)
        record_audit_event(
            database_session,
            actor=actor,
            action="user.web.deleted" if result.deleted else "user.web.archived",
            request=request,
            details={
                "web_user_id": user_id,
                "username": username,
                "deleted": result.deleted,
                "disabled": result.disabled,
                "archived": result.archived,
                "related_job_count": result.related_job_count,
            },
        )
        database_session.commit()
        if result.deleted:
            add_flash_message(request, "User deleted.", "success")
        else:
            add_flash_message(
                request,
                (
                    "User deleted and hidden. "
                    f"{result.related_job_count} linked jobs were preserved for this Autotask resource ID."
                ),
                "success",
            )
    except (HTTPException, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/users", status_code=303)
