"""Super-admin routes for managing database-backed web users."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from job_logger.database import get_database_session
from job_logger.models import Job, WebUser
from job_logger.security import add_flash_message, require_super_admin, validate_csrf_token
from job_logger.services.audit import record_audit_event
from job_logger.services.autotask import AutotaskSubmissionError, get_autotask_provider
from job_logger.services.users import (
    WebUserError,
    create_web_user,
    delete_or_disable_web_user,
    get_web_user_by_id_or_raise,
    list_web_users,
    update_web_user,
)
from job_logger.ui import template_context, templates

router = APIRouter(prefix="/users", tags=["users"])


@dataclass(frozen=True)
class WebUserListRow:
    """Template row for one managed web user and related job count."""

    # user is the editable managed account.
    user: WebUser

    # job_count is used to explain whether delete will disable instead.
    job_count: int


def _job_counts_by_user(database_session: Session) -> dict[str, int]:
    """Return job counts keyed by managed web-user ID."""

    rows = database_session.execute(select(Job.web_user_id, func.count(Job.id)).group_by(Job.web_user_id)).all()
    return {
        str(web_user_id): int(job_count)
        for web_user_id, job_count in rows
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
    rows = [
        WebUserListRow(user=user, job_count=job_counts.get(user.id, 0))
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
                    "resource_name": resource_option.resource_name,
                    "first_name": resource_option.first_name,
                    "last_name": resource_option.last_name,
                    "email": resource_option.email,
                }
                for resource_option in resource_options
            ],
        }
    )


@router.post("")
async def add_user(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Create a managed web user from the super-admin page."""

    try:
        actor = require_super_admin(request)
        form_values = await _form_values(request)
        result = create_web_user(
            database_session,
            full_name=form_values.get("full_name"),
            username=form_values.get("username"),
            password=form_values.get("password"),
            autotask_resource_id=form_values.get("autotask_resource_id"),
            disabled="disabled" in form_values,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="user.web.created",
            request=request,
            details={
                "web_user_id": result.user.id,
                "username": result.user.username,
                "disabled": result.user.disabled,
                "autotask_resource_id": result.user.autotask_resource_id,
                "claimed_unowned_job_count": result.claimed_unowned_job_count,
            },
        )
        database_session.commit()
        if result.claimed_unowned_job_count:
            add_flash_message(
                request,
                f"User created. Assigned {result.claimed_unowned_job_count} existing jobs to this first web user.",
                "success",
            )
        else:
            add_flash_message(request, "User created.", "success")
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
            disabled="disabled" in form_values,
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
                "autotask_resource_id": user.autotask_resource_id,
                "password_changed": bool(form_values.get("password")),
            },
        )
        database_session.commit()
        add_flash_message(request, "User updated.", "success")
    except (HTTPException, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/users", status_code=303)


@router.post("/{user_id}/delete")
async def delete_user(
    user_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Delete an unused user, or disable it when history must be preserved."""

    try:
        actor = require_super_admin(request)
        await _form_values(request)
        user = get_web_user_by_id_or_raise(database_session, user_id)
        username = user.username
        result = delete_or_disable_web_user(database_session, user)
        record_audit_event(
            database_session,
            actor=actor,
            action="user.web.deleted" if result.deleted else "user.web.disabled_for_history",
            request=request,
            details={
                "web_user_id": user_id,
                "username": username,
                "deleted": result.deleted,
                "disabled": result.disabled,
                "related_job_count": result.related_job_count,
            },
        )
        database_session.commit()
        if result.deleted:
            add_flash_message(request, "User deleted.", "success")
        else:
            add_flash_message(
                request,
                f"User has {result.related_job_count} jobs, so the account was disabled instead of deleted.",
                "success",
            )
    except (HTTPException, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/users", status_code=303)
