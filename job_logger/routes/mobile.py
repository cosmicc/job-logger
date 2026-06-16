"""Mobile-first job capture routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from job_logger.config import settings
from job_logger.database import get_database_session
from job_logger.security import (
    add_flash_message,
    require_authenticated_username,
    validate_csrf_header,
    validate_csrf_token,
)
from job_logger.services.audit import record_audit_event
from job_logger.services.jobs import (
    JobWorkflowError,
    apply_manual_summary_to_job,
    end_job,
    list_active_jobs,
    adjust_active_job_rounded_start,
    start_job,
    transcribe_active_job_audio,
    update_active_job_ticket_number,
    update_description_text,
)
from job_logger.services.transcription import TranscriptionError
from job_logger.ui import template_context, templates

router = APIRouter(tags=["mobile"])


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect the root URL to the mobile work logger."""

    return RedirectResponse(url="/mobile", status_code=303)


@router.get("/mobile", response_class=HTMLResponse)
def mobile_page(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Render the mobile work logging page."""

    if not require_authenticated_username_or_redirect(request):
        return RedirectResponse(url="/login", status_code=303)

    active_jobs = list_active_jobs(database_session)
    return templates.TemplateResponse(
        request,
        "mobile.html",
        template_context(request, active_jobs=active_jobs),
    )


@router.get("/moble", include_in_schema=False)
def mobile_typo_redirect() -> RedirectResponse:
    """Redirect a common mobile URL typo to the real mobile work logger."""

    return RedirectResponse(url="/mobile", status_code=303)


@router.post("/jobs/start")
async def start_work(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Start a new active work job."""

    actor = require_authenticated_username(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    submitted_ticket_number = str(form_data.get("ticket_number", ""))
    submitted_client_name = str(form_data.get("client_name", ""))

    try:
        job = start_job(database_session, ticket_number=submitted_ticket_number, client_name=submitted_client_name)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.started",
            job_id=job.id,
            request=request,
            details={"ticket_number_present": bool(job.ticket_number)},
        )
        database_session.commit()
        add_flash_message(request, "Work started.", "success")
    except JobWorkflowError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")

    return RedirectResponse(url="/mobile", status_code=303)


@router.post("/jobs/{job_id}/ticket-number")
async def save_ticket_number(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Save active-job edits before completing work."""

    actor = require_authenticated_username(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    submitted_ticket_number = str(form_data.get("ticket_number", ""))
    raw_client_name = form_data.get("client_name")
    submitted_client_name = str(raw_client_name) if raw_client_name is not None else None
    raw_summary_text = form_data.get("summary_notes")

    try:
        job = update_active_job_ticket_number(
            database_session,
            job_id,
            submitted_ticket_number,
            submitted_client_name,
        )
        if raw_summary_text is not None:
            apply_manual_summary_to_job(database_session, job_id, str(raw_summary_text))
        record_audit_event(
            database_session,
            actor=actor,
            action="job.active_edits.saved",
            job_id=job.id,
            request=request,
            details={
                "ticket_number_present": bool(job.ticket_number),
                "client_name_present": bool(job.client_name),
                "summary_present": bool(job.summary_notes),
            },
        )
        database_session.commit()
        add_flash_message(request, "Active job changes saved.", "success")
    except JobWorkflowError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")

    return RedirectResponse(url="/mobile", status_code=303)


@router.post("/jobs/{job_id}/start-time/adjust")
async def adjust_start_time(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Shift the active job rounded start time by a bounded increment."""

    actor = require_authenticated_username(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    delta_minutes = form_data.get("delta_minutes")

    try:
        job = adjust_active_job_rounded_start(database_session, job_id=job_id, delta_minutes=delta_minutes)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.rounded_start.adjusted",
            job_id=job.id,
            request=request,
            details={"delta_minutes": delta_minutes},
        )
        database_session.commit()
        add_flash_message(request, "Rounded start time adjusted.", "success")
    except JobWorkflowError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")

    return RedirectResponse(url="/mobile", status_code=303)


@router.post("/jobs/{job_id}/end")
async def end_work(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """End an active work job and send it to review."""

    actor = require_authenticated_username(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    raw_client_name = form_data.get("client_name")
    submitted_client_name = str(raw_client_name) if raw_client_name is not None else None
    summary_notes = str(form_data.get("summary_notes", ""))

    try:
        job = end_job(database_session, job_id, client_name=submitted_client_name)
        apply_manual_summary_to_job(database_session, job_id=job.id, summary_text=summary_notes)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.ended",
            job_id=job.id,
            request=request,
            details={"client_name_present": bool(job.client_name)},
        )
        database_session.commit()
        add_flash_message(request, "Work ended and moved to review.", "success")
    except JobWorkflowError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")

    return RedirectResponse(url="/mobile", status_code=303)


@router.post("/jobs/{job_id}/description/text")
async def save_browser_description(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Save text returned by typing or browser speech recognition during an active job."""

    actor = require_authenticated_username(request)
    validate_csrf_header(request)
    payload = await request.json()
    description_text = str(payload.get("summary_notes", "")) or str(payload.get("description_text", ""))

    try:
        job = update_description_text(database_session, job_id, description_text)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.description.browser_text_saved",
            job_id=job.id,
            request=request,
            details={"text_length": len(description_text)},
        )
        database_session.commit()
    except JobWorkflowError as exc:
        database_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return JSONResponse({"summary_notes": job.summary_notes or "", "description_text": job.description_text or ""})


@router.post("/jobs/{job_id}/description/audio")
async def upload_audio_description(
    job_id: str,
    request: Request,
    audio: UploadFile = File(...),
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Accept microphone audio and transcribe it using the configured provider."""

    actor = require_authenticated_username(request)
    validate_csrf_header(request)
    content_type = audio.content_type or "application/octet-stream"
    if not (content_type.startswith("audio/") or content_type == "video/webm"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only audio uploads are accepted.")

    audio_bytes = await audio.read(settings.max_audio_upload_bytes + 1)
    if len(audio_bytes) > settings.max_audio_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Audio upload is too large.")

    try:
        job = transcribe_active_job_audio(
            database_session,
            job_id=job_id,
            audio_bytes=audio_bytes,
            filename=audio.filename or "recording.webm",
            content_type=content_type,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="job.description.audio_transcribed",
            job_id=job.id,
            request=request,
            details={"provider": job.transcription_provider, "audio_size_bytes": len(audio_bytes)},
        )
        database_session.commit()
    except (JobWorkflowError, TranscriptionError) as exc:
        database_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return JSONResponse(
        {"summary_notes": job.summary_notes or "", "description_text": job.description_text or "", "provider": job.transcription_provider}
    )


def require_authenticated_username_or_redirect(request: Request) -> bool:
    """Return whether a page request has an authenticated local app user."""

    try:
        require_authenticated_username(request)
    except HTTPException:
        return False

    return True
