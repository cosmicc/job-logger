"""Desktop review and Autotask submission routes."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from job_logger.config import settings
from job_logger.database import get_database_session
from job_logger.enums import EntryType, JobStatus, TicketStatus
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
    AutotaskTicketNote,
    AutotaskTicketOption,
    AutotaskTicketTimeEntry,
    build_autotask_summary_notes,
    filter_displayable_ticket_notes,
    get_autotask_provider,
    resource_name_for_display,
)
from job_logger.services.jobs import (
    JobWorkflowError,
    apply_review_fields,
    apply_selected_ticket_from_lookup,
    apply_unset_review_client,
    delete_submitted_job_autotask_entry,
    display_summary_notes_for_review,
    ensure_job_is_not_locked_after_successful_submission,
    ensure_job_owned_by_web_user,
    expire_ai_cleanup_revert_state,
    expire_stale_ai_cleanup_revert_states,
    get_job_or_raise,
    is_job_locked_after_successful_submission,
    list_review_jobs,
    purge_job,
    purge_submitted_job_after_failed_autotask_delete,
    revert_ai_cleanup_summary,
    rounded_stop_for_active_job,
    store_ai_cleanup_revert_state,
    submit_job_to_autotask,
    update_submitted_job_autotask_entry,
    validate_review_fields,
    verify_autotask_client_selection,
)
from job_logger.services.users import WebUserError, get_enabled_web_user_by_id_or_raise
from job_logger.time_utils import (
    format_local_date,
    format_local_display,
    format_local_time,
    format_rounded_duration_label,
    to_local,
)
from job_logger.ui import template_context, templates

router = APIRouter(prefix="/review", tags=["review"])

SESSION_DELETE_AUTOTASK_FAILED_JOB_ID_KEY = "delete_autotask_failed_job_id"
SESSION_DELETE_AUTOTASK_FAILED_EXTERNAL_ID_KEY = "delete_autotask_failed_external_id"


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
        if not job.client_name or job.autotask_company_id is None:
            raise JobWorkflowError("Select a client from Autotask search results before searching Autotask tickets.")

        ticket_options = get_autotask_provider().list_open_tickets_for_client(
            job.client_name,
            job.autotask_company_id,
            resource_id=web_user.autotask_resource_id,
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
                    "status_id": ticket_option.status_id,
                    "company_name": ticket_option.company_name,
                    "work_location_label": ticket_option.work_location_label,
                    "work_location_class": _ticket_option_location_class(ticket_option),
                }
                for ticket_option in ticket_options
            ],
        }
    )


@router.get("/{job_id}/ticket-notes")
def review_ticket_notes(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Return safe Autotask ticket notes for the selected job's stored ticket."""

    try:
        require_authenticated_username(request)
        job = get_job_or_raise(database_session, job_id)
        resource_id = None
        if not is_super_admin_session(request.session):
            web_user = _current_enabled_web_user(request, database_session)
            ensure_job_owned_by_web_user(job, web_user.id)
            resource_id = web_user.autotask_resource_id
        if not job.ticket_number:
            return JSONResponse({"ticket_number": "", "ticket_title": "", "notes": []})

        ticket_notes = filter_displayable_ticket_notes(
            get_autotask_provider().list_ticket_notes(
                job.ticket_number,
                resource_id=resource_id,
            )
        )
    except HTTPException:
        raise
    except (AutotaskSubmissionError, JobWorkflowError, WebUserError) as exc:
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=400)

    ordered_ticket_notes = sorted(
        ticket_notes,
        key=lambda ticket_note: ticket_note.created_at_utc or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return JSONResponse(
        {
            "ticket_number": job.ticket_number,
            "ticket_title": job.ticket_title or "",
            "notes": [_ticket_note_payload(ticket_note) for ticket_note in ordered_ticket_notes],
        }
    )


@router.get("/{job_id}/ticket-time-entries")
def review_ticket_time_entries(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Return safe Autotask time entries for the selected job's stored ticket."""

    try:
        require_authenticated_username(request)
        job = get_job_or_raise(database_session, job_id)
        resource_id = None
        if not is_super_admin_session(request.session):
            web_user = _current_enabled_web_user(request, database_session)
            ensure_job_owned_by_web_user(job, web_user.id)
            resource_id = web_user.autotask_resource_id
        if not job.ticket_number:
            return JSONResponse({"ticket_number": "", "ticket_title": "", "time_entries": []})

        ticket_time_entries = get_autotask_provider().list_ticket_time_entries(
            job.ticket_number,
            resource_id=resource_id,
        )
    except HTTPException:
        raise
    except (AutotaskSubmissionError, JobWorkflowError, WebUserError) as exc:
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=400)

    ordered_time_entries = sorted(
        ticket_time_entries,
        key=lambda time_entry: time_entry.start_at_utc or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return JSONResponse(
        {
            "ticket_number": job.ticket_number,
            "ticket_title": job.ticket_title or "",
            "time_entries": [_ticket_time_entry_payload(time_entry) for time_entry in ordered_time_entries],
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
    autotask_company_id = getattr(job, "autotask_company_id", None)
    locked_form_values["client_name"] = getattr(job, "client_name", None) or ""
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


def _ticket_option_location_class(ticket_option: AutotaskTicketOption) -> str:
    """Return the CSS class used for open-ticket location treatment."""

    if ticket_option.detected_work_location is None:
        return "ticket-location-unknown"

    return f"ticket-location-{ticket_option.detected_work_location.value}"


def _ticket_note_preview(description: str | None) -> str:
    """Return a short single-line preview from an Autotask ticket note body."""

    safe_description = " ".join(str(description or "").split())
    return safe_description[:180]


def _ticket_note_payload(ticket_note: AutotaskTicketNote) -> dict[str, object]:
    """Return safe ticket-note fields for the authenticated overlay."""

    return {
        "note_id": ticket_note.note_id,
        "title": ticket_note.title,
        "description": ticket_note.description or "",
        "preview": _ticket_note_preview(ticket_note.description),
        "created_by": ticket_note.created_by or "",
        "created_at": format_local_display(ticket_note.created_at_utc) if ticket_note.created_at_utc else "",
        "updated_at": format_local_display(ticket_note.updated_at_utc) if ticket_note.updated_at_utc else "",
        "note_type": ticket_note.note_type or "",
        "publish": ticket_note.publish,
    }


def _format_ticket_time_entry_datetime(timestamp: datetime | None) -> str:
    """Return a numeric local date and time for an Autotask time entry."""

    if timestamp is None:
        return ""

    local_timestamp = to_local(timestamp)
    return local_timestamp.strftime("%m/%d/%Y %I:%M %p")


def _format_ticket_time_entry_time(timestamp: datetime | None) -> str:
    """Return a numeric local time for an Autotask time entry."""

    if timestamp is None:
        return ""

    return to_local(timestamp).strftime("%I:%M %p")


def _format_ticket_time_entry_hours(hours_worked: Decimal | None) -> str:
    """Return Autotask hours with four decimals for time-entry list rows."""

    if hours_worked is None:
        return ""

    return f"{hours_worked:.4f}"


def _ticket_time_entry_display_range(time_entry: AutotaskTicketTimeEntry) -> str:
    """Return the requested time-entry list display string."""

    start_text = _format_ticket_time_entry_datetime(time_entry.start_at_utc)
    end_text = ""
    if time_entry.end_at_utc is not None:
        same_local_date = (
            time_entry.start_at_utc is not None
            and to_local(time_entry.start_at_utc).date() == to_local(time_entry.end_at_utc).date()
        )
        end_text = _format_ticket_time_entry_time(time_entry.end_at_utc) if same_local_date else _format_ticket_time_entry_datetime(time_entry.end_at_utc)

    range_text = (
        f"{start_text} - {end_text}"
        if start_text and end_text
        else start_text or end_text or "No time range"
    )

    hours_text = _format_ticket_time_entry_hours(time_entry.hours_worked)
    if hours_text:
        return f"{range_text} ({hours_text} hours)"

    return range_text


def _ticket_time_entry_payload(time_entry: AutotaskTicketTimeEntry) -> dict[str, object]:
    """Return safe ticket time-entry fields for the authenticated overlay."""

    return {
        "time_entry_id": time_entry.time_entry_id,
        "resource_name": resource_name_for_display(time_entry.resource_name) or "Unknown resource",
        "display_range": _ticket_time_entry_display_range(time_entry),
        "summary_notes": time_entry.summary_notes or "",
        "hours_worked": _format_ticket_time_entry_hours(time_entry.hours_worked),
    }


def _review_save_payload(job: object) -> dict[str, object]:
    """Return non-secret review state after a background save completes."""

    ticket_status = getattr(job, "ticket_status", None)
    entry_type = getattr(job, "entry_type", EntryType.TIME_ENTRY)
    job_status = getattr(job, "status", None)
    rounded_end_utc = _review_display_end_time_utc(job)
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
        "entry_type": entry_type.value if entry_type is not None else EntryType.TIME_ENTRY.value,
        "note_title": getattr(job, "note_title", None) or "",
        "append_to_resolution": bool(getattr(job, "append_to_resolution", True)),
        "summary_notes": (
            str(getattr(job, "summary_notes", None) or getattr(job, "description_text", None) or "").strip()
            if entry_type == EntryType.TICKET_NOTE
            else build_autotask_summary_notes(job)
        ),
        "job_date": job_date,
        "start_time": format_local_time(getattr(job, "rounded_start_utc", None)),
        "end_time": format_local_time(rounded_end_utc),
        "duration_label": (
            ""
            if entry_type == EntryType.TICKET_NOTE
            else format_rounded_duration_label(getattr(job, "rounded_start_utc", None), rounded_end_utc)
        ),
    }


def _review_display_end_time_utc(job: object | None):
    """Return the review-detail end time shown to the user without ending active work."""

    if job is None:
        return None

    if getattr(job, "status", None) == JobStatus.ACTIVE:
        return getattr(job, "rounded_end_utc", None) or rounded_stop_for_active_job(job)

    return getattr(job, "rounded_end_utc", None)


def _entry_type_label(job: object) -> str:
    """Return a user-facing label for the selected local entry type."""

    return "ticket note" if getattr(job, "entry_type", EntryType.TIME_ENTRY) == EntryType.TICKET_NOTE else "time entry"


def _entry_type_sentence_label(job: object) -> str:
    """Return a sentence-case label for the selected local entry type."""

    return "Ticket note" if _entry_type_label(job) == "ticket note" else "Time entry"


def _submitted_delete_failure_purge_available(request: Request, selected_job: object | None) -> bool:
    """Return whether the selected submitted job can show the local-purge fallback."""

    if selected_job is None or not is_job_locked_after_successful_submission(selected_job):
        return False

    failed_job_id = request.session.get(SESSION_DELETE_AUTOTASK_FAILED_JOB_ID_KEY)
    failed_external_id = request.session.get(SESSION_DELETE_AUTOTASK_FAILED_EXTERNAL_ID_KEY)
    return (
        failed_job_id == getattr(selected_job, "id", None)
        and failed_external_id == (getattr(selected_job, "autotask_external_id", None) or "")
        and bool(getattr(selected_job, "autotask_error", None))
    )


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
        if expire_stale_ai_cleanup_revert_states(
            database_session,
            retention_hours=settings.ai_cleanup_revert_retention_hours,
            web_user_id=web_user_id,
        ):
            database_session.commit()
        jobs = list_review_jobs(database_session, web_user_id=web_user_id)
        selected_job, audit_events = _selected_review_context(database_session, selected_job_id, web_user_id=web_user_id)
    except JobWorkflowError:
        return RedirectResponse(url="/review", status_code=303)
    show_delete_failure_purge_prompt = _submitted_delete_failure_purge_available(request, selected_job)

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
                display_summary_notes_for_review(selected_job) if selected_job is not None else ""
            ),
            selected_job_review_end_utc=_review_display_end_time_utc(selected_job),
            can_modify_selected_job=can_modify_jobs and selected_job is not None,
            show_job_owner=is_super_admin,
            audit_events=audit_events,
            ticket_status_options=_ticket_status_options(),
            show_delete_failure_purge_prompt=show_delete_failure_purge_prompt,
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
        locked_form_values = _read_only_review_form_values(form_values, job)
        if job.status == JobStatus.ACTIVE:
            locked_form_values["end_time"] = ""
        review_fields = validate_review_fields(
            locked_form_values,
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
        if expire_ai_cleanup_revert_state(
            job,
            retention_hours=settings.ai_cleanup_revert_retention_hours,
        ):
            database_session.commit()
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
        store_ai_cleanup_revert_state(
            job,
            original_summary_text=submitted_summary_text,
            cleaned_summary_text=cleanup_result.cleaned_text,
            source="review",
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


@router.post("/{job_id}/summary/cleanup/revert")
async def revert_review_summary_cleanup(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Restore the pre-cleanup summary text for the selected review detail."""

    actor = require_authenticated_username(request)
    validate_csrf_header(request)

    try:
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        if expire_ai_cleanup_revert_state(
            job,
            retention_hours=settings.ai_cleanup_revert_retention_hours,
        ):
            database_session.commit()
            raise JobWorkflowError("Cleanup revert has expired. Run AI Cleanup again if needed.")
        restored_summary_text = revert_ai_cleanup_summary(job, source="review")
        record_audit_event(
            database_session,
            actor=actor,
            action="job.summary.ai_cleanup_reverted",
            job_id=job.id,
            request=request,
            details={
                "source": "review",
                "job_status": job.status.value,
                "restored_text_length": len(restored_summary_text),
            },
        )
        database_session.commit()
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=400)

    return JSONResponse(
        {
            "summary_notes": restored_summary_text,
            "description_text": restored_summary_text,
            "reverted": True,
        }
    )


@router.post("/{job_id}/edit-entry")
async def edit_submitted_entry(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Edit the existing Autotask record for an already submitted job."""

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
        update_submitted_job_autotask_entry(
            database_session,
            job,
            review_fields,
            resource_id=web_user.autotask_resource_id,
        )
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
                "entry_type": job.entry_type.value,
            },
        )
        database_session.commit()
        if job.autotask_error:
            add_flash_message(request, f"Autotask entry update failed: {job.autotask_error}", "error")
        else:
            add_flash_message(request, f"Autotask {_entry_type_label(job)} updated.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.post("/{job_id}/client")
async def save_unset_review_client(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Persist the first client selection for an unsubmitted review job."""

    actor = require_authenticated_username(request)
    validate_csrf_header(request)
    payload = await request.json()
    raw_client_name = payload.get("client_name")
    submitted_client_name = "" if raw_client_name is None else str(raw_client_name)
    raw_autotask_company_id = payload.get("autotask_company_id")
    submitted_autotask_company_id = "" if raw_autotask_company_id is None else str(raw_autotask_company_id)

    try:
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        if job.ticket_number or job.client_name or job.autotask_company_id is not None:
            raise JobWorkflowError("Client identity is already selected for this job.")
        verified_client_name, verified_company_id = verify_autotask_client_selection(
            submitted_client_name,
            submitted_autotask_company_id,
            resource_id=web_user.autotask_resource_id,
            required=True,
        )
        apply_unset_review_client(
            job,
            client_name=verified_client_name,
            autotask_company_id=verified_company_id,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="job.review.client_selected",
            job_id=job.id,
            request=request,
            details={
                "client_name_present": bool(job.client_name),
                "autotask_company_selected": job.autotask_company_id is not None,
            },
        )
        database_session.commit()
    except (HTTPException, AutotaskSubmissionError, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=400)

    return JSONResponse(
        {
            "job_id": job.id,
            "client_name": job.client_name,
            "autotask_company_id": job.autotask_company_id,
        }
    )


@router.post("/{job_id}/delete-entry")
async def delete_submitted_entry(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Delete an existing Autotask record while keeping the local job."""

    actor = require_authenticated_username(request)
    try:
        await _form_values(request)
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        original_external_id = job.autotask_external_id
        delete_submitted_job_autotask_entry(
            database_session,
            job,
            resource_id=web_user.autotask_resource_id,
        )
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
                "entry_type": job.entry_type.value,
            },
        )
        database_session.commit()
        if job.autotask_error:
            request.session[SESSION_DELETE_AUTOTASK_FAILED_JOB_ID_KEY] = job.id
            request.session[SESSION_DELETE_AUTOTASK_FAILED_EXTERNAL_ID_KEY] = original_external_id or ""
            add_flash_message(request, f"Autotask entry delete failed: {job.autotask_error}", "error")
        else:
            request.session.pop(SESSION_DELETE_AUTOTASK_FAILED_JOB_ID_KEY, None)
            request.session.pop(SESSION_DELETE_AUTOTASK_FAILED_EXTERNAL_ID_KEY, None)
            add_flash_message(request, f"Autotask {_entry_type_label(job)} deleted; job returned to review.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url=f"/review/{job_id}", status_code=303)


@router.post("/{job_id}/purge-submitted-local")
async def purge_submitted_local_after_delete_failure(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Purge a submitted local review row after Delete From Autotask fails."""

    actor = require_authenticated_username(request)
    await _form_values(request)
    try:
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        failed_job_id = request.session.get(SESSION_DELETE_AUTOTASK_FAILED_JOB_ID_KEY)
        failed_external_id = request.session.get(SESSION_DELETE_AUTOTASK_FAILED_EXTERNAL_ID_KEY)
        if failed_job_id != job.id or failed_external_id != (job.autotask_external_id or ""):
            raise JobWorkflowError("Delete From Autotask must fail before this local purge is available.")

        original_external_id = job.autotask_external_id
        safe_delete_error = job.autotask_error
        purge_submitted_job_after_failed_autotask_delete(database_session, job)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.review.submitted_delete_failed_local_purged",
            request=request,
            details={
                "job_id": job.id,
                "external_id": original_external_id,
                "autotask_delete_error": safe_delete_error,
                "local_only": True,
            },
        )
        database_session.commit()
        request.session.pop(SESSION_DELETE_AUTOTASK_FAILED_JOB_ID_KEY, None)
        request.session.pop(SESSION_DELETE_AUTOTASK_FAILED_EXTERNAL_ID_KEY, None)
        add_flash_message(
            request,
            "Job purged from Job Logger review. The Autotask record may still exist.",
            "success",
        )
        return RedirectResponse(url="/review", status_code=303)
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
        submit_job_to_autotask(
            database_session,
            job,
            resource_id=web_user.autotask_resource_id,
            default_service_desk_role_id=web_user.autotask_default_service_desk_role_id,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="job.review.accepted",
            job_id=job.id,
            request=request,
            details={
                "status": job.status.value,
                "autotask_provider": job.autotask_provider,
                "entry_type": job.entry_type.value,
            },
        )
        database_session.commit()
        if job.autotask_error:
            add_flash_message(request, f"Submission failed: {job.autotask_error}", "error")
        else:
            add_flash_message(request, f"{_entry_type_sentence_label(job)} accepted and submitted.", "success")
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
        submit_job_to_autotask(
            database_session,
            job,
            resource_id=web_user.autotask_resource_id,
            default_service_desk_role_id=web_user.autotask_default_service_desk_role_id,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="job.autotask.retry",
            job_id=job.id,
            request=request,
            details={
                "status": job.status.value,
                "autotask_provider": job.autotask_provider,
                "entry_type": job.entry_type.value,
            },
        )
        database_session.commit()
        if job.autotask_error:
            add_flash_message(request, f"Retry failed: {job.autotask_error}", "error")
        else:
            add_flash_message(request, f"{_entry_type_sentence_label(job)} retry succeeded.", "success")
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
        if not job.client_name or job.autotask_company_id is None:
            raise JobWorkflowError("Select a client from Autotask search results before selecting an Autotask ticket.")

        ticket_options = get_autotask_provider().list_open_tickets_for_client(
            job.client_name,
            job.autotask_company_id,
            resource_id=web_user.autotask_resource_id,
        )
        selected_ticket_option = _find_matching_ticket_option(ticket_options, submitted_ticket_number)
        if selected_ticket_option is None:
            raise JobWorkflowError("Selected ticket was not found in the open-ticket list for this client.")

        selected_ticket_status = TicketStatus.IN_PROGRESS
        apply_selected_ticket_from_lookup(
            job,
            selected_ticket_option.ticket_number,
            selected_ticket_option.title,
            selected_ticket_option.description,
            ticket_status=selected_ticket_status,
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
                "ticket_status": job.ticket_status.value if job.ticket_status else None,
                "ticket_status_source": "local_selection_default",
                "autotask_ticket_status_label": selected_ticket_option.status_label,
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
            "ticket_status": job.ticket_status.value if job.ticket_status else None,
            "ticket_status_label": selected_ticket_option.status_label,
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
