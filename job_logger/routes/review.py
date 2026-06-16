"""Desktop review and Autotask submission routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from job_logger.database import get_database_session
from job_logger.enums import JobStatus, TicketStatus
from job_logger.models import AuditEvent
from job_logger.security import add_flash_message, require_authenticated_username, validate_csrf_token
from job_logger.services.audit import record_audit_event
from job_logger.services.autotask import AutotaskSubmissionError, get_autotask_provider
from job_logger.services.jobs import (
    JobWorkflowError,
    apply_review_fields,
    get_job_or_raise,
    list_review_jobs,
    purge_job,
    reject_job,
    submit_job_to_autotask,
    validate_review_fields,
)
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


def _selected_review_context(database_session: Session, selected_job_id: str | None) -> tuple[object | None, list[AuditEvent]]:
    """Return the selected job and its newest-first audit events."""

    jobs = list_review_jobs(database_session)
    selected_job = None
    if selected_job_id:
        selected_job = get_job_or_raise(database_session, selected_job_id)
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

    require_authenticated_username(request)
    try:
        job = get_job_or_raise(database_session, job_id)
        if not job.client_name:
            raise JobWorkflowError("Client name is required before searching Autotask tickets.")

        ticket_options = get_autotask_provider().list_open_tickets_for_client(
            job.client_name,
            job.autotask_company_id,
        )
    except (AutotaskSubmissionError, JobWorkflowError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    return JSONResponse(
        {
            "client_name": job.client_name,
            "autotask_company_id": job.autotask_company_id,
            "tickets": [
                {
                    "ticket_number": ticket_option.ticket_number,
                    "title": ticket_option.title,
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

    jobs = list_review_jobs(database_session)
    selected_job, audit_events = _selected_review_context(database_session, selected_job_id)
    return templates.TemplateResponse(
        request,
        "review.html",
        template_context(
            request,
            jobs=jobs,
            selected_job=selected_job,
            audit_events=audit_events,
            ticket_status_options=_ticket_status_options(),
        ),
    )


@router.post("/{job_id}/save")
async def save_review(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Save reviewer edits without submitting to Autotask."""

    actor = require_authenticated_username(request)
    try:
        form_values = await _form_values(request)
        job = get_job_or_raise(database_session, job_id)
        require_end_time_fields = job.status != JobStatus.ACTIVE
        review_fields = validate_review_fields(
            form_values,
            require_ticket_number=False,
            require_end_time_fields=require_end_time_fields,
        )
        apply_review_fields(job, review_fields)
        record_audit_event(database_session, actor=actor, action="job.review.saved", job_id=job.id, request=request)
        database_session.commit()
        add_flash_message(request, "Review edits saved.", "success")
    except JobWorkflowError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")

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
        job = get_job_or_raise(database_session, job_id)
        review_fields = validate_review_fields(form_values, require_ticket_number=True)
        apply_review_fields(job, review_fields)
        submit_job_to_autotask(database_session, job)
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
    except JobWorkflowError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.post("/{job_id}/reject")
async def reject_review(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Reject a reviewed job while preserving its audit history."""

    actor = require_authenticated_username(request)
    form_values = await _form_values(request)
    rejection_reason = form_values.get("rejection_reason", "").strip()
    try:
        job = get_job_or_raise(database_session, job_id)
        reject_job(job)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.review.rejected",
            job_id=job.id,
            request=request,
            details={"reason": rejection_reason},
        )
        database_session.commit()
        add_flash_message(request, "Job rejected and kept for audit.", "success")
    except JobWorkflowError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")

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
        job = get_job_or_raise(database_session, job_id)
        if form_values:
            review_fields = validate_review_fields(form_values, require_ticket_number=True)
            apply_review_fields(job, review_fields)
        submit_job_to_autotask(database_session, job)
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
    except JobWorkflowError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.post("/{job_id}/purge")
async def purge_review_job(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Permanently remove a selected job from local history."""

    actor = require_authenticated_username(request)
    await _form_values(request)
    try:
        # Use the current job state as the immutable source for audit details.
        job = get_job_or_raise(database_session, job_id)
        purge_job(database_session, job)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.review.purged",
            request=request,
            details={"job_status": job.status.value, "ticket_number": job.ticket_number or "No ticket"},
        )
        database_session.commit()
        add_flash_message(request, "Job removed from review history.", "success")
    except JobWorkflowError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")
        return RedirectResponse(url=f"/review/{job_id}", status_code=303)

    return RedirectResponse(url="/review", status_code=303)
