"""Desktop review and Autotask submission routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from job_logger.database import get_database_session
from job_logger.enums import JobStatus, TicketStatus
from job_logger.models import AuditEvent
from job_logger.security import (
    add_flash_message,
    is_super_admin_session,
    require_authenticated_username,
    require_web_user_id,
    validate_csrf_header,
    validate_csrf_token,
)
from job_logger.services.ai_cleanup import AiCleanupContext, AiCleanupError, cleanup_summary_text
from job_logger.services.audit import record_audit_event
from job_logger.services.autotask import (
    AutotaskSubmissionError,
    AutotaskTicketOption,
    build_autotask_summary_notes,
    get_autotask_provider,
)
from job_logger.services.jobs import (
    JobWorkflowError,
    apply_review_fields,
    apply_selected_ticket_from_lookup,
    delete_submitted_job_autotask_entry,
    ensure_job_is_not_locked_after_successful_submission,
    ensure_job_owned_by_web_user,
    get_job_or_raise,
    is_job_locked_after_successful_submission,
    list_review_jobs,
    purge_job,
    submit_job_to_autotask,
    update_submitted_job_autotask_entry,
    validate_review_fields,
)
from job_logger.services.users import WebUserError, get_enabled_web_user_by_id_or_raise
from job_logger.time_utils import format_local_date, format_local_time
from job_logger.ui import template_context, templates

router = APIRouter(prefix="/review", tags=["review"])


def _ticket_status_options() -> list[tuple[str, str]]:
    """Return ticket status options for the review form."""

    return [
        (TicketStatus.IN_PROGRESS.value, "In progress"),
        (TicketStatus.WAITING_CUSTOMER.value, "Waiting customer"),
        (TicketStatus.WAITING_PARTS.value, "Waiting parts"),
        (TicketStatus.FOLLOW_UP.value, "Follow up"),
        (TicketStatus.COMPLETE.value, "Complete"),
    ]


def _current_enabled_web_user(request: Request, database_session: Session):
    """Return the enabled managed web user for review mutation routes."""

    web_user_id = require_web_user_id(request)
    return get_enabled_web_user_by_id_or_raise(database_session, web_user_id)


def _selected_review_context(
    database_session: Session,
    selected_job_id: str | None,
    *,
    web_user_id: str | None = None,
) -> tuple[object | None, list[AuditEvent]]:
    """Return the selected job and its newest-first audit events."""

    jobs = list_review_jobs(database_session, web_user_id=web_user_id)
    selected_job = None
    if selected_job_id:
        selected_job = get_job_or_raise(database_session, selected_job_id)
        if web_user_id is not None:
            ensure_job_owned_by_web_user(selected_job, web_user_id)
    elif jobs:
        selected_job = jobs[0]

    audit_events: list[AuditEvent] = []
    if selected_job is not None:
        audit_events = list(
            database_session.execute(
                select(AuditEvent).where(AuditEvent.job_id == selected_job.id).order_by(desc(AuditEvent.created_at_utc))
            ).scalars()
        )

    return selected_job, audit_events


@router.get("", response_class=HTMLResponse)
def review_page(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Render the desktop review page."""

    return _render_review(request, database_session, None)


@router.get("/{job_id}", response_class=HTMLResponse)
def selected_review_page(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Render the desktop review page with a selected job."""

    return _render_review(request, database_session, job_id)


@router.get("/{job_id}/tickets")
def review_ticket_options(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Return open Autotask tickets for the selected job's stored client name."""

    try:
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        ensure_job_is_not_locked_after_successful_submission(job)
        if not job.client_name:
            raise JobWorkflowError("Client name is required before searching Autotask tickets.")

        ticket_options = get_autotask_provider().list_open_tickets_for_client(
            job.client_name,
            job.autotask_company_id,
        )
    except (HTTPException, AutotaskSubmissionError, JobWorkflowError, WebUserError) as exc:
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=400)

    return JSONResponse(
        {
            "client_name": job.client_name,
            "autotask_company_id": job.autotask_company_id,
            "tickets": [
                {
                    "ticket_number": ticket_option.ticket_number,
                    "title": ticket_option.title,
                    "description": ticket_option.description,
                    "status_label": ticket_option.status_label,
                    "company_name": ticket_option.company_name,
                }
                for ticket_option in ticket_options
            ],
        }
    )


async def _form_values(request: Request) -> dict[str, str]:
    """Return submitted form values as a plain string dictionary."""

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    return {key: str(value) for key, value in form_data.items()}


def _read_only_review_form_values(form_values: dict[str, str], job: object) -> dict[str, str]:
    """Overlay read-only job identity fields before review validation."""

    locked_form_values = dict(form_values)
    locked_form_values["ticket_number"] = getattr(job, "ticket_number", None) or ""
    locked_form_values["ticket_title"] = getattr(job, "ticket_title", None) or ""
    locked_form_values["ticket_description"] = getattr(job, "ticket_description", None) or ""
    locked_form_values["client_name"] = getattr(job, "client_name", None) or ""
    autotask_company_id = getattr(job, "autotask_company_id", None)
    locked_form_values["autotask_company_id"] = str(autotask_company_id) if autotask_company_id is not None else ""
    work_location = getattr(job, "work_location", None)
    locked_form_values["work_location"] = work_location.value if work_location is not None else "remote"
    return locked_form_values


def _find_matching_ticket_option(ticket_options: list[AutotaskTicketOption], ticket_number: str) -> AutotaskTicketOption | None:
    """Return a selected open-ticket option by normalized ticket number."""

    normalized_ticket_number = ticket_number.strip().upper()
    for ticket_option in ticket_options:
        if ticket_option.ticket_number.strip().upper() == normalized_ticket_number:
            return ticket_option

    return None


def _review_save_payload(job: object) -> dict[str, object]:
    """Return non-secret review state after a background save completes."""

    rounded_end_utc = getattr(job, "rounded_end_utc", None)
    ticket_status = getattr(job, "ticket_status", None)
    job_status = getattr(job, "status", None)
    local_work_date = getattr(job, "local_work_date", None)
    job_date = (
        str(local_work_date)
        if local_work_date is not None
        else format_local_date(getattr(job, "rounded_start_utc", None))
    )
    return {
        "job_id": getattr(job, "id", ""),
        "status": job_status.value if job_status is not None else "",
        "ticket_status": ticket_status.value if ticket_status is not None else "",
        "summary_notes": build_autotask_summary_notes(job),
        "job_date": job_date,
        "start_time": format_local_time(getattr(job, "rounded_start_utc", None)),
        "end_time": format_local_time(rounded_end_utc),
    }


def _render_review(
    request: Request,
    database_session: Session,
    selected_job_id: str | None,
) -> Response:
    """Render review state or redirect anonymous users to login."""

    try:
        require_authenticated_username(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)

    is_super_admin = is_super_admin_session(request.session)
    web_user_id = None
    can_modify_jobs = False
    if not is_super_admin:
        try:
            web_user = _current_enabled_web_user(request, database_session)
        except (HTTPException, WebUserError):
            return RedirectResponse(url="/login", status_code=303)
        web_user_id = web_user.id
        can_modify_jobs = True

    try:
        jobs = list_review_jobs(database_session, web_user_id=web_user_id)
        selected_job, audit_events = _selected_review_context(database_session, selected_job_id, web_user_id=web_user_id)
    except JobWorkflowError:
        return RedirectResponse(url="/review", status_code=303)

    return templates.TemplateResponse(
        request,
        "review.html",
        template_context(
            request,
            database_session=database_session,
            jobs=jobs,
            selected_job=selected_job,
            selected_job_submitted=(
                is_job_locked_after_successful_submission(selected_job) if selected_job is not None else False
            ),
            selected_job_autotask_summary_notes=(
                build_autotask_summary_notes(selected_job) if selected_job is not None else ""
            ),
            can_modify_selected_job=can_modify_jobs and selected_job is not None,
            show_job_owner=is_super_admin,
            audit_events=audit_events,
            ticket_status_options=_ticket_status_options(),
        ),
    )


@router.post("/{job_id}/save")
async def save_review(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Save reviewer edits without submitting to Autotask."""

    actor = require_authenticated_username(request)
    wants_json_response = "application/json" in request.headers.get("accept", "").lower()
    try:
        form_values = await _form_values(request)
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        ensure_job_is_not_locked_after_successful_submission(job)
        require_end_time_fields = job.status != JobStatus.ACTIVE
        review_fields = validate_review_fields(
            _read_only_review_form_values(form_values, job),
            require_ticket_number=False,
            require_end_time_fields=require_end_time_fields,
        )
        apply_review_fields(job, review_fields)
        record_audit_event(database_session, actor=actor, action="job.review.saved", job_id=job.id, request=request)
        database_session.commit()
        if wants_json_response:
            return JSONResponse(_review_save_payload(job))
        add_flash_message(request, "Review edits saved.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        if wants_json_response:
            return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=400)
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.post("/{job_id}/summary/cleanup")
async def cleanup_review_summary(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Return AI-cleaned summary text for the selected review detail."""

    actor = require_authenticated_username(request)
    validate_csrf_header(request)
    payload = await request.json()
    submitted_summary_text = str(payload.get("summary_notes", "")) or str(payload.get("description_text", ""))

    try:
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        cleanup_result = cleanup_summary_text(
            summary_text=submitted_summary_text,
            cleanup_context=AiCleanupContext(
                job_id=job.id,
                source="review",
                job_status=job.status.value,
                client_name=job.client_name,
                ticket_number=job.ticket_number,
                ticket_title=job.ticket_title,
                work_location=job.work_location.value if job.work_location else None,
            ),
            actor=actor,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="job.summary.ai_cleanup",
            job_id=job.id,
            request=request,
            details={
                "source": "review",
                "provider": cleanup_result.provider,
                "model": cleanup_result.model,
                "input_text_length": len(submitted_summary_text),
                "output_text_length": len(cleanup_result.cleaned_text),
                "job_status": job.status.value,
            },
        )
        database_session.commit()
    except (HTTPException, AiCleanupError, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=400)

    return JSONResponse(
        {
            "summary_notes": cleanup_result.cleaned_text,
            "description_text": cleanup_result.cleaned_text,
            "provider": cleanup_result.provider,
            "model": cleanup_result.model,
        }
    )


@router.post("/{job_id}/edit-entry")
async def edit_submitted_entry(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Edit the existing Autotask time entry for an already submitted job."""

    actor = require_authenticated_username(request)
    try:
        form_values = await _form_values(request)
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        review_fields = validate_review_fields(
            _read_only_review_form_values(form_values, job),
            require_ticket_number=True,
        )
        update_submitted_job_autotask_entry(database_session, job, review_fields)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.autotask.entry_update",
            job_id=job.id,
            request=request,
            details={
                "succeeded": job.autotask_error is None,
                "autotask_provider": job.autotask_provider,
                "external_id": job.autotask_external_id,
            },
        )
        database_session.commit()
        if job.autotask_error:
            add_flash_message(request, f"Autotask entry update failed: {job.autotask_error}", "error")
        else:
            add_flash_message(request, "Autotask entry updated.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.post("/{job_id}/delete-entry")
async def delete_submitted_entry(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Delete an existing Autotask time entry while keeping the local job."""

    actor = require_authenticated_username(request)
    try:
        await _form_values(request)
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        original_external_id = job.autotask_external_id
        delete_submitted_job_autotask_entry(database_session, job)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.autotask.entry_deleted",
            job_id=job.id,
            request=request,
            details={
                "succeeded": job.autotask_error is None,
                "autotask_provider": job.autotask_provider,
                "external_id": original_external_id,
                "status": job.status.value,
            },
        )
        database_session.commit()
        if job.autotask_error:
            add_flash_message(request, f"Autotask entry delete failed: {job.autotask_error}", "error")
        else:
            add_flash_message(request, "Autotask entry deleted; job returned to review.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.post("/{job_id}/accept")
async def accept_review(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Save review fields, submit to Autotask, and preserve outcome."""

    actor = require_authenticated_username(request)
    try:
        form_values = await _form_values(request)
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        ensure_job_is_not_locked_after_successful_submission(job)
        review_fields = validate_review_fields(_read_only_review_form_values(form_values, job), require_ticket_number=True)
        apply_review_fields(job, review_fields)
        submit_job_to_autotask(database_session, job, resource_id=web_user.autotask_resource_id)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.review.accepted",
            job_id=job.id,
            request=request,
            details={"status": job.status.value, "autotask_provider": job.autotask_provider},
        )
        database_session.commit()
        if job.autotask_error:
            add_flash_message(request, f"Submission failed: {job.autotask_error}", "error")
        else:
            add_flash_message(request, "Job accepted and submitted.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.post("/{job_id}/retry")
async def retry_submission(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Retry a failed Autotask submission without creating duplicates."""

    actor = require_authenticated_username(request)
    form_values = await _form_values(request)
    try:
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        ensure_job_is_not_locked_after_successful_submission(job)
        if form_values:
            review_fields = validate_review_fields(_read_only_review_form_values(form_values, job), require_ticket_number=True)
            apply_review_fields(job, review_fields)
        submit_job_to_autotask(database_session, job, resource_id=web_user.autotask_resource_id)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.autotask.retry",
            job_id=job.id,
            request=request,
            details={"status": job.status.value, "autotask_provider": job.autotask_provider},
        )
        database_session.commit()
        if job.autotask_error:
            add_flash_message(request, f"Retry failed: {job.autotask_error}", "error")
        else:
            add_flash_message(request, "Submission retry succeeded.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.post("/{job_id}/ticket")
async def select_review_ticket(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Persist a ticket chosen from the selected job's open-ticket lookup."""

    actor = require_authenticated_username(request)
    validate_csrf_header(request)
    payload = await request.json()
    submitted_ticket_number = str(payload.get("ticket_number", ""))
    try:
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        ensure_job_is_not_locked_after_successful_submission(job)
        if not job.client_name:
            raise JobWorkflowError("Client name is required before selecting an Autotask ticket.")

        ticket_options = get_autotask_provider().list_open_tickets_for_client(
            job.client_name,
            job.autotask_company_id,
        )
        selected_ticket_option = _find_matching_ticket_option(ticket_options, submitted_ticket_number)
        if selected_ticket_option is None:
            raise JobWorkflowError("Selected ticket was not found in the open-ticket list for this client.")

        apply_selected_ticket_from_lookup(
            job,
            selected_ticket_option.ticket_number,
            selected_ticket_option.title,
            selected_ticket_option.description,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="job.review.ticket_selected",
            job_id=job.id,
            request=request,
            details={
                "ticket_number": job.ticket_number,
                "ticket_title_present": bool(job.ticket_title),
                "ticket_description_present": bool(job.ticket_description),
                "autotask_company_selected": job.autotask_company_id is not None,
            },
        )
        database_session.commit()
    except (HTTPException, AutotaskSubmissionError, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=400)

    return JSONResponse(
        {
            "ticket_number": job.ticket_number,
            "ticket_title": job.ticket_title,
            "ticket_description": job.ticket_description,
        }
    )


@router.post("/{job_id}/purge")
async def purge_review_job(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Permanently remove a selected local unsubmitted time entry."""

    actor = require_authenticated_username(request)
    await _form_values(request)
    try:
        web_user = _current_enabled_web_user(request, database_session)
        # Use the current job state as the immutable source for audit details.
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        ensure_job_is_not_locked_after_successful_submission(job)
        purge_job(database_session, job)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.review.deleted",
            request=request,
            details={"job_status": job.status.value, "ticket_number": job.ticket_number or "No ticket"},
        )
        database_session.commit()
        add_flash_message(request, "Time entry removed from review history.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")
        return RedirectResponse(url=f"/review/{job_id}", status_code=303)

    return RedirectResponse(url="/review", status_code=303)
