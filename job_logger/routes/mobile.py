"""Mobile-first job capture routes."""

from __future__ import annotations

import asyncio
import json
import time as monotonic_time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from job_logger.config import settings
from job_logger.database import get_database_session
from job_logger.enums import JobStatus, TicketStatus, WorkLocation
from job_logger.security import (
    SESSION_SHOW_PASSKEY_SETUP_PROMPT_KEY,
    add_flash_message,
    is_super_admin_session,
    logout_session,
    require_authenticated_username,
    require_authenticated_username_from_session,
    require_web_user_id,
    require_web_user_id_from_session,
    validate_csrf_header,
    validate_csrf_session_token,
    validate_csrf_token,
)
from job_logger.services.ai_cleanup import AiCleanupContext, AiCleanupError, cleanup_summary_text
from job_logger.services.audit import record_audit_event
from job_logger.services.autotask import (
    AutotaskServiceCallOption,
    AutotaskSubmissionError,
    AutotaskTicketOption,
    get_autotask_provider,
)
from job_logger.services.jobs import (
    MAX_ACTIVE_JOBS,
    JobWorkflowError,
    adjust_active_job_rounded_start,
    adjust_active_job_rounded_stop,
    apply_manual_summary_to_job,
    apply_selected_ticket_from_lookup,
    apply_transcription_result_to_job,
    delete_active_job,
    end_job,
    ensure_job_can_record_description,
    ensure_job_owned_by_web_user,
    get_job_or_raise,
    list_active_jobs_for_web_user,
    mark_job_transcription_failed,
    rounded_stop_for_active_job,
    start_job,
    submit_job_to_autotask,
    ticket_status_from_autotask_label,
    transcribe_active_job_audio,
    update_active_job_ticket_number,
    update_description_text,
)
from job_logger.services.passkeys import passkey_credential_count_for_user
from job_logger.services.preferences import (
    get_submit_from_work_in_progress_for_principal,
    get_submit_from_work_in_progress_for_session,
    preference_principal_from_session,
)
from job_logger.services.transcription import TranscriptionError, TranscriptionResult, get_transcription_provider
from job_logger.services.users import WebUserError, get_enabled_web_user_by_id_or_raise
from job_logger.time_utils import format_local_compact_time_range, local_date_for, now_utc
from job_logger.ui import template_context, templates

router = APIRouter(tags=["mobile"])

AUDIO_STREAM_PARTIAL_INTERVAL_SECONDS = 12.0
SUPPORTED_AUDIO_STREAM_SUFFIXES = {".webm", ".ogg", ".mp3", ".m4a", ".wav", ".mp4"}


class AudioStreamProtocolError(RuntimeError):
    """Raised when a WebSocket audio client sends an invalid stream message."""


def _find_matching_ticket_option(ticket_options: list[AutotaskTicketOption], ticket_number: str) -> AutotaskTicketOption | None:
    """Return a selected open-ticket option by normalized ticket number."""

    normalized_ticket_number = ticket_number.strip().upper()
    for ticket_option in ticket_options:
        if ticket_option.ticket_number.strip().upper() == normalized_ticket_number:
            return ticket_option

    return None


def _find_matching_service_call_option(
    service_call_options: list[AutotaskServiceCallOption],
    service_call_ticket_id: int,
) -> AutotaskServiceCallOption | None:
    """Return a service-call option by the server-rendered ticket association ID."""

    for service_call_option in service_call_options:
        if service_call_option.service_call_ticket_id == service_call_ticket_id:
            return service_call_option

    return None


def _service_call_start_work_location(service_call_option: AutotaskServiceCallOption) -> WorkLocation:
    """Return the work-location mode stored when a service call starts a job."""

    return service_call_option.detected_work_location or WorkLocation.REMOTE


def _ticket_status_options() -> list[tuple[str, str]]:
    """Return ticket status options for active mobile jobs."""

    return [
        (TicketStatus.IN_PROGRESS.value, "In progress"),
        (TicketStatus.WAITING_CUSTOMER.value, "Waiting customer"),
        (TicketStatus.WAITING_PARTS.value, "Waiting parts"),
        (TicketStatus.FOLLOW_UP.value, "Follow up"),
        (TicketStatus.COMPLETE.value, "Complete"),
    ]


def _status_for_started_autotask_ticket(
    ticket_number: str,
    status_label: str | None,
    *,
    resource_id: int,
) -> tuple[TicketStatus | None, bool]:
    """Return the local status after starting work on a selected Autotask ticket."""

    provider = get_autotask_provider()
    ticket_was_new = provider.mark_ticket_in_progress_if_new(
        ticket_number,
        current_status_label=status_label,
        resource_id=resource_id,
    )
    if ticket_was_new:
        return TicketStatus.IN_PROGRESS, True

    return ticket_status_from_autotask_label(status_label), False


def _current_enabled_web_user(request: Request, database_session: Session):
    """Return the enabled managed web user for a work route."""

    web_user_id = require_web_user_id(request)
    return get_enabled_web_user_by_id_or_raise(database_session, web_user_id)


def _parse_service_call_local_date(raw_service_call_date: str | None) -> date:
    """Return the selected local service-call date or today's local date."""

    normalized_service_call_date = (raw_service_call_date or "").strip()
    if not normalized_service_call_date:
        return local_date_for(now_utc())
    if len(normalized_service_call_date) > 10:
        raise ValueError("Selected service-call date is invalid.")

    try:
        return date.fromisoformat(normalized_service_call_date)
    except ValueError as exc:
        raise ValueError("Selected service-call date is invalid.") from exc


def _format_service_call_calendar_date(selected_service_call_date: date) -> str:
    """Return a compact user-facing date for service-call day navigation."""

    return f"{selected_service_call_date.strftime('%b')} {selected_service_call_date.day}, {selected_service_call_date.year}"


def _service_call_date_label(selected_service_call_date: date) -> str:
    """Return the mobile day label for service-call date navigation."""

    current_local_date = local_date_for(now_utc())
    current_week_start = current_local_date - timedelta(days=current_local_date.weekday())
    current_week_end = current_week_start + timedelta(days=6)
    if not current_week_start <= selected_service_call_date <= current_week_end:
        return _format_service_call_calendar_date(selected_service_call_date)

    day_label = selected_service_call_date.strftime("%A")
    relative_day_delta = (selected_service_call_date - current_local_date).days
    relative_labels = {
        -1: "Yesterday",
        0: "Today",
        1: "Tomorrow",
    }
    relative_label = relative_labels.get(relative_day_delta)
    if relative_label:
        return f"{day_label} ({relative_label})"

    return day_label


def _service_call_date_payload(selected_service_call_date: date) -> dict[str, str]:
    """Return date-navigation metadata for the mobile service-call panel."""

    previous_service_call_date = selected_service_call_date - timedelta(days=1)
    next_service_call_date = selected_service_call_date + timedelta(days=1)
    date_label = _service_call_date_label(selected_service_call_date)
    return {
        "selected_date": selected_service_call_date.isoformat(),
        "previous_date": previous_service_call_date.isoformat(),
        "next_date": next_service_call_date.isoformat(),
        "date_label": date_label,
        "empty_message": f"No service calls are scheduled for {date_label}.",
    }


def _load_service_calls_for_mobile_start(
    resource_id: int,
    selected_service_call_date: date,
) -> tuple[list[AutotaskServiceCallOption], str | None]:
    """Return service calls for the selected day and a safe display error."""

    try:
        return get_autotask_provider().list_todays_service_calls_for_resource(
            resource_id=resource_id,
            local_service_date=selected_service_call_date,
        ), None
    except AutotaskSubmissionError as exc:
        return [], str(exc)


def _service_call_location_class(service_call_option: AutotaskServiceCallOption) -> str:
    """Return the CSS class used for the mobile service-call location treatment."""

    if service_call_option.detected_work_location is None:
        return "service-call-location-unknown"

    return f"service-call-location-{service_call_option.detected_work_location.value}"


def _service_call_option_payload(service_call_option: AutotaskServiceCallOption) -> dict[str, object]:
    """Return the non-secret service-call fields needed by mobile JavaScript."""

    return {
        "service_call_ticket_id": service_call_option.service_call_ticket_id,
        "client_name": service_call_option.client_name,
        "ticket_title": service_call_option.ticket_title,
        "scheduled_time_range": format_local_compact_time_range(
            service_call_option.start_datetime_utc,
            service_call_option.end_datetime_utc,
        ),
        "work_location_label": service_call_option.work_location_label,
        "work_location_class": _service_call_location_class(service_call_option),
        "ticket_status_label": service_call_option.ticket_status_label,
    }


def _normalize_audio_stream_content_type(raw_content_type: Any) -> str:
    """Return a bounded audio content type accepted by the streaming endpoint."""

    content_type = str(raw_content_type or "audio/webm").strip()[:120]
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type.startswith("audio/") or media_type == "video/webm":
        return content_type

    raise AudioStreamProtocolError("Only audio streams are accepted.")


def _safe_audio_stream_filename(raw_filename: Any) -> str:
    """Return a server-controlled filename with only a safe media suffix kept."""

    submitted_suffix = Path(str(raw_filename or "")).suffix.lower()
    if submitted_suffix not in SUPPORTED_AUDIO_STREAM_SUFFIXES:
        submitted_suffix = ".webm"

    return f"streamed-recording{submitted_suffix}"


def _json_dict_from_websocket_text(message_text: str | None) -> dict[str, Any]:
    """Decode a text WebSocket message into a JSON object."""

    if message_text is None:
        raise AudioStreamProtocolError("Audio stream metadata must be sent as JSON text.")

    try:
        decoded_message = json.loads(message_text)
    except json.JSONDecodeError as exc:
        raise AudioStreamProtocolError("Audio stream metadata must be valid JSON.") from exc

    if not isinstance(decoded_message, dict):
        raise AudioStreamProtocolError("Audio stream metadata must be a JSON object.")

    return decoded_message


async def _receive_audio_stream_json(websocket: WebSocket) -> dict[str, Any]:
    """Receive one JSON object from an audio WebSocket."""

    websocket_message = await websocket.receive()
    if websocket_message.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect()

    return _json_dict_from_websocket_text(websocket_message.get("text"))


async def _send_audio_stream_error(websocket: WebSocket, detail: str, close_code: int) -> None:
    """Send a safe WebSocket error response and close the connection."""

    try:
        await websocket.send_json({"type": "error", "detail": detail})
    except RuntimeError:
        return

    try:
        await websocket.close(code=close_code)
    except RuntimeError:
        return


async def _transcribe_audio_snapshot(audio_bytes: bytes, filename: str, content_type: str) -> TranscriptionResult:
    """Run the configured synchronous transcription provider without blocking the event loop."""

    return await asyncio.to_thread(
        get_transcription_provider().transcribe,
        audio_bytes=audio_bytes,
        filename=filename,
        content_type=content_type,
    )


def _record_audio_stream_failure(
    database_session: Session,
    *,
    actor: str,
    job_id: str,
    safe_error: str,
    audio_size_bytes: int,
    chunk_count: int,
) -> None:
    """Persist safe failure status for a streamed transcription attempt."""

    job = mark_job_transcription_failed(
        database_session,
        job_id=job_id,
        error_message=safe_error,
    )
    record_audit_event(
        database_session,
        actor=actor,
        action="job.description.audio_stream_failed",
        job_id=job.id,
        details={
            "audio_size_bytes": audio_size_bytes,
            "chunk_count": chunk_count,
            "error": safe_error,
        },
    )
    database_session.commit()


async def _receive_audio_stream_chunks(
    *,
    websocket: WebSocket,
    database_session: Session,
    actor: str,
    job_id: str,
    filename: str,
    content_type: str,
) -> None:
    """Receive audio chunks, start early transcription, and save the final transcript."""

    # audio_buffer is intentionally process memory only. It is cleared when the
    # WebSocket handler exits, and raw audio is never written to the database.
    audio_buffer = bytearray()
    chunk_count = 0
    partial_snapshot_bytes = 0
    last_partial_started_at = 0.0
    partial_wait_notice_sent = False
    stream_finished = False
    partial_task: asyncio.Task[TranscriptionResult] | None = None

    async def collect_completed_partial_transcription() -> None:
        """Send a completed interim transcription result if one is available."""

        nonlocal partial_task, partial_wait_notice_sent
        if partial_task is None or not partial_task.done():
            return

        try:
            partial_result = partial_task.result()
        except TranscriptionError:
            # Early media snapshots can be too short for faster-whisper or ffmpeg
            # to decode. That is not a final failure; the route continues
            # buffering and will make the final attempt with the full recording.
            if not partial_wait_notice_sent:
                await websocket.send_json(
                    {
                        "type": "partial_pending",
                        "detail": "Collecting enough audio to return transcription text.",
                    }
                )
                partial_wait_notice_sent = True
        else:
            await websocket.send_json(
                {
                    "type": "partial",
                    "summary_notes": partial_result.text,
                    "description_text": partial_result.text,
                    "provider": partial_result.provider,
                    "bytes_transcribed": partial_snapshot_bytes,
                }
            )
        finally:
            partial_task = None

    async def start_partial_transcription_if_ready() -> None:
        """Start a throttled interim transcription on the buffered audio."""

        nonlocal last_partial_started_at, partial_snapshot_bytes, partial_task
        if partial_task is not None or not audio_buffer:
            return

        current_time = monotonic_time.monotonic()
        if chunk_count != 1 and current_time - last_partial_started_at < AUDIO_STREAM_PARTIAL_INTERVAL_SECONDS:
            return

        partial_audio_bytes = bytes(audio_buffer)
        partial_snapshot_bytes = len(partial_audio_bytes)
        last_partial_started_at = current_time
        partial_task = asyncio.create_task(
            _transcribe_audio_snapshot(partial_audio_bytes, filename, content_type)
        )
        await websocket.send_json(
            {
                "type": "transcription_started",
                "phase": "partial",
                "bytes_queued": partial_snapshot_bytes,
            }
        )

    try:
        while True:
            await collect_completed_partial_transcription()
            try:
                websocket_message = await asyncio.wait_for(websocket.receive(), timeout=0.25)
            except TimeoutError:
                continue

            if websocket_message.get("type") == "websocket.disconnect":
                if audio_buffer:
                    record_audit_event(
                        database_session,
                        actor=actor,
                        action="job.description.audio_stream_canceled",
                        job_id=job_id,
                        details={
                            "audio_size_bytes": len(audio_buffer),
                            "chunk_count": chunk_count,
                        },
                    )
                    database_session.commit()
                return

            binary_chunk = websocket_message.get("bytes")
            if binary_chunk:
                audio_buffer.extend(binary_chunk)
                chunk_count += 1
                if len(audio_buffer) > settings.max_audio_upload_bytes:
                    database_session.rollback()
                    _record_audio_stream_failure(
                        database_session,
                        actor=actor,
                        job_id=job_id,
                        safe_error="Audio upload is too large.",
                        audio_size_bytes=len(audio_buffer),
                        chunk_count=chunk_count,
                    )
                    await _send_audio_stream_error(
                        websocket,
                        "Audio upload is too large.",
                        status.WS_1009_MESSAGE_TOO_BIG,
                    )
                    return

                await websocket.send_json(
                    {
                        "type": "chunk_received",
                        "bytes_received": len(audio_buffer),
                        "chunk_count": chunk_count,
                    }
                )
                await start_partial_transcription_if_ready()
                continue

            websocket_payload = _json_dict_from_websocket_text(websocket_message.get("text"))
            message_type = str(websocket_payload.get("type", "")).strip().lower()
            if message_type == "finish":
                stream_finished = True
                break

            if message_type == "cancel":
                record_audit_event(
                    database_session,
                    actor=actor,
                    action="job.description.audio_stream_canceled",
                    job_id=job_id,
                    details={
                        "audio_size_bytes": len(audio_buffer),
                        "chunk_count": chunk_count,
                    },
                )
                database_session.commit()
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                return

            raise AudioStreamProtocolError("Unsupported audio stream command.")
    finally:
        if not stream_finished and partial_task is not None and not partial_task.done():
            partial_task.cancel()

    if not audio_buffer:
        database_session.rollback()
        _record_audio_stream_failure(
            database_session,
            actor=actor,
            job_id=job_id,
            safe_error="No audio was recorded.",
            audio_size_bytes=0,
            chunk_count=chunk_count,
        )
        await _send_audio_stream_error(
            websocket,
            "No audio was recorded. Press Record and try again.",
            status.WS_1008_POLICY_VIOLATION,
        )
        return

    await collect_completed_partial_transcription()
    if partial_task is not None:
        try:
            partial_result = await partial_task
        except TranscriptionError:
            pass
        else:
            await websocket.send_json(
                {
                    "type": "partial",
                    "summary_notes": partial_result.text,
                    "description_text": partial_result.text,
                    "provider": partial_result.provider,
                    "bytes_transcribed": partial_snapshot_bytes,
                }
            )
        finally:
            partial_task = None

    await websocket.send_json(
        {
            "type": "transcription_started",
            "phase": "final",
            "bytes_queued": len(audio_buffer),
        }
    )
    try:
        final_result = await _transcribe_audio_snapshot(bytes(audio_buffer), filename, content_type)
        job = apply_transcription_result_to_job(
            database_session,
            job_id=job_id,
            transcription_result=final_result,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="job.description.audio_stream_transcribed",
            job_id=job.id,
            details={
                "provider": job.transcription_provider,
                "audio_size_bytes": len(audio_buffer),
                "chunk_count": chunk_count,
            },
        )
        database_session.commit()
    except (JobWorkflowError, TranscriptionError) as exc:
        database_session.rollback()
        safe_error = str(exc)
        try:
            _record_audio_stream_failure(
                database_session,
                actor=actor,
                job_id=job_id,
                safe_error=safe_error,
                audio_size_bytes=len(audio_buffer),
                chunk_count=chunk_count,
            )
        except JobWorkflowError:
            database_session.rollback()
        await _send_audio_stream_error(websocket, safe_error, status.WS_1011_INTERNAL_ERROR)
        return

    await websocket.send_json(
        {
            "type": "final",
            "summary_notes": job.summary_notes or "",
            "description_text": job.description_text or "",
            "provider": job.transcription_provider,
        }
    )
    await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect the root URL to the home work logger."""

    return RedirectResponse(url="/home", status_code=303)


@router.get("/home", response_class=HTMLResponse)
def home_page(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Render the authenticated home work logging page."""

    if not require_authenticated_username_or_redirect(request):
        return RedirectResponse(url="/login", status_code=303)

    try:
        web_user = _current_enabled_web_user(request, database_session)
    except (HTTPException, WebUserError):
        if not is_super_admin_session(request.session):
            logout_session(request)
            add_flash_message(request, "This user account is disabled.", "error")
            return RedirectResponse(url="/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "mobile.html",
            template_context(
                request,
                database_session=database_session,
                active_jobs=[],
                active_rounded_stop_times={},
                ticket_status_options=_ticket_status_options(),
                submit_from_work_in_progress_enabled=False,
                can_start_jobs=False,
                start_block_reason="The config super admin can view jobs, but cannot start work because it has no Autotask resource ID.",
            ),
        )

    active_jobs = list_active_jobs_for_web_user(database_session, web_user.id)
    active_rounded_stop_times = {
        active_job.id: active_job.rounded_end_utc or rounded_stop_for_active_job(active_job)
        for active_job in active_jobs
    }
    principal = preference_principal_from_session(request.session)
    submit_from_work_in_progress_enabled = get_submit_from_work_in_progress_for_principal(
        database_session,
        principal.key if principal else None,
    )
    show_passkey_setup_prompt = (
        bool(request.session.pop(SESSION_SHOW_PASSKEY_SETUP_PROMPT_KEY, False))
        and passkey_credential_count_for_user(database_session, web_user.id) == 0
    )

    return templates.TemplateResponse(
        request,
        "mobile.html",
        template_context(
            request,
            database_session=database_session,
            active_jobs=active_jobs,
            active_rounded_stop_times=active_rounded_stop_times,
            ticket_status_options=_ticket_status_options(),
            submit_from_work_in_progress_enabled=submit_from_work_in_progress_enabled,
            show_passkey_setup_prompt=show_passkey_setup_prompt,
            can_start_jobs=True,
            start_block_reason=None,
        ),
    )


@router.get("/home/service-calls")
def home_service_call_options(
    request: Request,
    service_call_date: str | None = Query(default=None, alias="date"),
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Return service-call start options for the already-rendered home page."""

    try:
        web_user = _current_enabled_web_user(request, database_session)
    except (HTTPException, WebUserError) as exc:
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=403)

    try:
        selected_service_call_date = _parse_service_call_local_date(service_call_date)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc), "service_calls": []}, status_code=400)

    service_call_date_context = _service_call_date_payload(selected_service_call_date)
    active_jobs = list_active_jobs_for_web_user(database_session, web_user.id)
    if len(active_jobs) >= MAX_ACTIVE_JOBS:
        return JSONResponse(
            {
                **service_call_date_context,
                "service_calls": [],
                "active_job_slots_available": False,
            }
        )

    service_call_options, service_call_error = _load_service_calls_for_mobile_start(
        web_user.autotask_resource_id,
        selected_service_call_date,
    )
    if service_call_error:
        return JSONResponse(
            {**service_call_date_context, "detail": service_call_error, "service_calls": []},
            status_code=400,
        )

    return JSONResponse(
        {
            **service_call_date_context,
            "active_job_slots_available": True,
            "service_calls": [
                _service_call_option_payload(service_call_option)
                for service_call_option in service_call_options
            ],
        }
    )


@router.get("/mobile", include_in_schema=False)
def legacy_mobile_page_redirect() -> RedirectResponse:
    """Redirect the old route name to the canonical home route."""

    return RedirectResponse(url="/home", status_code=308)


@router.get("/mobile/service-calls", include_in_schema=False)
def legacy_mobile_service_call_redirect(request: Request) -> RedirectResponse:
    """Redirect the old service-call endpoint to the canonical home endpoint."""

    query_string = request.url.query
    redirect_url = "/home/service-calls"
    if query_string:
        redirect_url = f"{redirect_url}?{query_string}"
    return RedirectResponse(url=redirect_url, status_code=308)


@router.get("/moble", include_in_schema=False)
def mobile_typo_redirect() -> RedirectResponse:
    """Redirect a common old home URL typo to the canonical home work logger."""

    return RedirectResponse(url="/home", status_code=303)


@router.get("/autotask/companies")
def autotask_company_options(
    request: Request,
    query: str = "",
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Return safe Autotask company options for authenticated autocomplete."""

    try:
        web_user = _current_enabled_web_user(request, database_session)
    except (HTTPException, WebUserError) as exc:
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=403)
    try:
        company_options = get_autotask_provider().search_companies(
            query,
            resource_id=web_user.autotask_resource_id,
        )
    except AutotaskSubmissionError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    return JSONResponse(
        {
            "companies": [
                {
                    "company_id": company_option.company_id,
                    "company_name": company_option.company_name,
                }
                for company_option in company_options
            ],
        }
    )


@router.post("/jobs/start")
async def start_work(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Start a new active work job."""

    actor = require_authenticated_username(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    try:
        web_user = _current_enabled_web_user(request, database_session)
        # New mobile jobs intentionally start blank. Client and ticket data are
        # selected while the job is active so stale or crafted pre-start fields
        # cannot attach the job to the wrong Autotask customer or ticket.
        job = start_job(database_session, web_user_id=web_user.id)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.started",
            job_id=job.id,
            request=request,
            details={
                "web_user_id": web_user.id,
                "autotask_resource_id": web_user.autotask_resource_id,
                "ticket_number_present": bool(job.ticket_number),
                "autotask_company_selected": job.autotask_company_id is not None,
            },
        )
        database_session.commit()
        add_flash_message(request, "Work started.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/home", status_code=303)


@router.post("/jobs/start/service-call")
async def start_work_from_service_call(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Start a new active work job from a server-verified Autotask service call."""

    actor = require_authenticated_username(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    raw_service_call_ticket_id = form_data.get("service_call_ticket_id")
    try:
        service_call_ticket_id = int(str(raw_service_call_ticket_id or "").strip())
    except ValueError:
        add_flash_message(request, "Selected service call is invalid.", "error")
        return RedirectResponse(url="/home", status_code=303)

    if service_call_ticket_id <= 0:
        add_flash_message(request, "Selected service call is invalid.", "error")
        return RedirectResponse(url="/home", status_code=303)

    try:
        selected_service_call_date = _parse_service_call_local_date(str(form_data.get("service_call_date") or ""))
    except ValueError as exc:
        add_flash_message(request, str(exc), "error")
        return RedirectResponse(url="/home", status_code=303)

    try:
        web_user = _current_enabled_web_user(request, database_session)
        service_call_options = get_autotask_provider().list_todays_service_calls_for_resource(
            resource_id=web_user.autotask_resource_id,
            local_service_date=selected_service_call_date,
        )
        selected_service_call = _find_matching_service_call_option(service_call_options, service_call_ticket_id)
        if selected_service_call is None:
            raise JobWorkflowError("Selected service call is not assigned to this resource for that date.")

        ticket_status, ticket_status_changed_in_autotask = _status_for_started_autotask_ticket(
            selected_service_call.ticket_number,
            selected_service_call.ticket_status_label,
            resource_id=web_user.autotask_resource_id,
        )
        job = start_job(
            database_session,
            web_user_id=web_user.id,
            ticket_number=selected_service_call.ticket_number,
            client_name=selected_service_call.client_name,
            autotask_company_id=selected_service_call.autotask_company_id,
            work_location=_service_call_start_work_location(selected_service_call),
            ticket_status=ticket_status,
        )
        apply_selected_ticket_from_lookup(
            job,
            selected_service_call.ticket_number,
            selected_service_call.ticket_title,
            selected_service_call.ticket_description,
            ticket_status=ticket_status,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="job.started",
            job_id=job.id,
            request=request,
            details={
                "source": "autotask_service_call",
                "web_user_id": web_user.id,
                "autotask_resource_id": web_user.autotask_resource_id,
                "service_call_id": selected_service_call.service_call_id,
                "service_call_ticket_id": selected_service_call.service_call_ticket_id,
                "service_call_date": selected_service_call_date.isoformat(),
                "ticket_number": job.ticket_number,
                "ticket_status": job.ticket_status.value if job.ticket_status else None,
                "autotask_ticket_status_label": selected_service_call.ticket_status_label,
                "autotask_ticket_status_changed_to_in_progress": ticket_status_changed_in_autotask,
                "autotask_company_selected": job.autotask_company_id is not None,
                "work_location": job.work_location.value,
                "work_location_detected": selected_service_call.detected_work_location is not None,
            },
        )
        database_session.commit()
        add_flash_message(request, "Work started from service call.", "success")
    except (HTTPException, AutotaskSubmissionError, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/home", status_code=303)


@router.post("/jobs/{job_id}/ticket-number")
async def save_ticket_number(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Save active-job edits before completing work."""

    actor = require_authenticated_username(request)
    wants_json_response = "application/json" in request.headers.get("accept", "").lower()
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    raw_client_name = form_data.get("client_name")
    submitted_client_name = str(raw_client_name) if raw_client_name is not None else None
    raw_autotask_company_id = form_data.get("autotask_company_id")
    submitted_autotask_company_id = str(raw_autotask_company_id) if raw_autotask_company_id is not None else None
    raw_summary_text = form_data.get("summary_notes")
    raw_work_location = form_data.get("work_location")
    submitted_work_location = str(raw_work_location) if raw_work_location is not None else None
    raw_ticket_status = form_data.get("ticket_status")
    submitted_ticket_status = str(raw_ticket_status) if raw_ticket_status is not None else None

    try:
        web_user = _current_enabled_web_user(request, database_session)
        existing_job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(existing_job, web_user.id)
        job = update_active_job_ticket_number(
            database_session,
            job_id,
            ticket_number=None,
            client_name=submitted_client_name,
            autotask_company_id=submitted_autotask_company_id,
            ticket_title=None,
            work_location=submitted_work_location,
            ticket_status=submitted_ticket_status,
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
                "autotask_company_selected": job.autotask_company_id is not None,
                "summary_present": bool(job.summary_notes),
                "work_location": job.work_location.value,
                "ticket_status": job.ticket_status.value if job.ticket_status else None,
            },
        )
        database_session.commit()
        if wants_json_response:
            return JSONResponse(
                {
                    "job_id": job.id,
                    "client_name": job.client_name,
                    "autotask_company_id": job.autotask_company_id,
                    "ticket_number": job.ticket_number,
                    "ticket_title": job.ticket_title,
                    "ticket_description": job.ticket_description,
                    "work_location": job.work_location.value,
                    "ticket_status": job.ticket_status.value if job.ticket_status else None,
                }
            )
        add_flash_message(request, "Active job changes saved.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        if wants_json_response:
            return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=400)
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/home", status_code=303)


@router.post("/jobs/{job_id}/ticket")
async def select_active_ticket(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Persist an active-job ticket chosen from the server-verified open-ticket list."""

    actor = require_authenticated_username(request)
    validate_csrf_header(request)
    payload = await request.json()
    submitted_ticket_number = str(payload.get("ticket_number", ""))
    try:
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        if job.status != JobStatus.ACTIVE:
            raise JobWorkflowError("Tickets can only be selected from mobile during an active job.")
        if not job.client_name:
            raise JobWorkflowError("Client name is required before selecting an Autotask ticket.")

        ticket_options = get_autotask_provider().list_open_tickets_for_client(
            job.client_name,
            job.autotask_company_id,
            resource_id=web_user.autotask_resource_id,
        )
        selected_ticket_option = _find_matching_ticket_option(ticket_options, submitted_ticket_number)
        if selected_ticket_option is None:
            raise JobWorkflowError("Selected ticket was not found in the open-ticket list for this client.")

        ticket_status, ticket_status_changed_in_autotask = _status_for_started_autotask_ticket(
            selected_ticket_option.ticket_number,
            selected_ticket_option.status_label,
            resource_id=web_user.autotask_resource_id,
        )
        apply_selected_ticket_from_lookup(
            job,
            selected_ticket_option.ticket_number,
            selected_ticket_option.title,
            selected_ticket_option.description,
            ticket_status=ticket_status,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="job.active.ticket_selected",
            job_id=job.id,
            request=request,
            details={
                "ticket_number": job.ticket_number,
                "ticket_title_present": bool(job.ticket_title),
                "ticket_description_present": bool(job.ticket_description),
                "ticket_status": job.ticket_status.value if job.ticket_status else None,
                "autotask_ticket_status_label": selected_ticket_option.status_label,
                "autotask_ticket_status_changed_to_in_progress": ticket_status_changed_in_autotask,
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


@router.post("/jobs/{job_id}/delete")
async def delete_open_job(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Discard an active in-progress job from the mobile workflow."""

    actor = require_authenticated_username(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    try:
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        audit_details = {
            "job_id": job.id,
            "job_status": job.status.value,
            "ticket_number_present": bool(job.ticket_number),
            "client_name_present": bool(job.client_name),
            "autotask_company_selected": job.autotask_company_id is not None,
        }
        delete_active_job(database_session, job)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.active.deleted",
            request=request,
            details=audit_details,
        )
        database_session.commit()
        add_flash_message(request, "Open job deleted.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/home", status_code=303)


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
        web_user = _current_enabled_web_user(request, database_session)
        existing_job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(existing_job, web_user.id)
        job = adjust_active_job_rounded_start(database_session, job_id=job_id, delta_minutes=delta_minutes)
        audit_details = {"delta_minutes": delta_minutes}
        record_audit_event(
            database_session,
            actor=actor,
            action="job.rounded_start.adjusted",
            job_id=job.id,
            request=request,
            details=audit_details,
        )
        database_session.commit()
        add_flash_message(request, "Rounded start time adjusted.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/home", status_code=303)


@router.post("/jobs/{job_id}/stop-time/adjust")
async def adjust_stop_time(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Shift the active job rounded stop time by a bounded increment."""

    actor = require_authenticated_username(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    delta_minutes = form_data.get("delta_minutes")

    try:
        web_user = _current_enabled_web_user(request, database_session)
        existing_job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(existing_job, web_user.id)
        job = adjust_active_job_rounded_stop(database_session, job_id=job_id, delta_minutes=delta_minutes)
        audit_details = {"delta_minutes": delta_minutes}
        record_audit_event(
            database_session,
            actor=actor,
            action="job.rounded_stop.adjusted",
            job_id=job.id,
            request=request,
            details=audit_details,
        )
        database_session.commit()
        add_flash_message(request, "Rounded stop time adjusted.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/home", status_code=303)


@router.post("/jobs/{job_id}/end")
async def end_work(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """End an active work job, optionally submitting it directly to Autotask."""

    actor = require_authenticated_username(request)
    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    raw_client_name = form_data.get("client_name")
    submitted_client_name = str(raw_client_name) if raw_client_name is not None else None
    raw_autotask_company_id = form_data.get("autotask_company_id")
    submitted_autotask_company_id = str(raw_autotask_company_id) if raw_autotask_company_id is not None else None
    summary_notes = str(form_data.get("summary_notes", ""))
    raw_work_location = form_data.get("work_location")
    submitted_work_location = str(raw_work_location) if raw_work_location is not None else None
    raw_ticket_status = form_data.get("ticket_status")
    submitted_ticket_status = str(raw_ticket_status) if raw_ticket_status is not None else None

    try:
        web_user = _current_enabled_web_user(request, database_session)
        existing_job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(existing_job, web_user.id)
        update_active_job_ticket_number(
            database_session,
            job_id,
            ticket_number=None,
            client_name=submitted_client_name,
            autotask_company_id=submitted_autotask_company_id,
            work_location=submitted_work_location,
            ticket_status=submitted_ticket_status,
        )
        job = end_job(
            database_session,
            job_id,
            client_name=submitted_client_name,
            autotask_company_id=submitted_autotask_company_id,
        )
        apply_manual_summary_to_job(database_session, job_id=job.id, summary_text=summary_notes)
        submit_from_work_in_progress = get_submit_from_work_in_progress_for_session(database_session, request.session)
        if submit_from_work_in_progress:
            submit_job_to_autotask(database_session, job, resource_id=web_user.autotask_resource_id)
        record_audit_event(
            database_session,
            actor=actor,
            action="job.ended",
            job_id=job.id,
            request=request,
            details={
                "client_name_present": bool(job.client_name),
                "autotask_company_selected": job.autotask_company_id is not None,
                "submit_from_work_in_progress": submit_from_work_in_progress,
                "status": job.status.value,
            },
        )
        if submit_from_work_in_progress:
            record_audit_event(
                database_session,
                actor=actor,
                action="job.autotask.direct_submit",
                job_id=job.id,
                request=request,
                details={
                    "status": job.status.value,
                    "autotask_provider": job.autotask_provider,
                    "succeeded": job.autotask_error is None,
                },
            )
        database_session.commit()
        if submit_from_work_in_progress:
            if job.autotask_error:
                add_flash_message(request, f"Autotask submission failed: {job.autotask_error}", "error")
            else:
                add_flash_message(request, "Work ended and submitted to Autotask.", "success")
        else:
            add_flash_message(request, "Work ended and moved to review.", "success")
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/home", status_code=303)


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
        web_user = _current_enabled_web_user(request, database_session)
        existing_job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(existing_job, web_user.id)
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
    except (HTTPException, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(getattr(exc, "detail", exc))) from exc

    return JSONResponse({"summary_notes": job.summary_notes or "", "description_text": job.description_text or ""})


@router.post("/jobs/{job_id}/summary/cleanup")
async def cleanup_active_job_summary(
    job_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Return AI-cleaned summary text for an active mobile job."""

    actor = require_authenticated_username(request)
    validate_csrf_header(request)
    payload = await request.json()
    submitted_summary_text = str(payload.get("summary_notes", "")) or str(payload.get("description_text", ""))

    try:
        web_user = _current_enabled_web_user(request, database_session)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        if job.status != JobStatus.ACTIVE:
            raise JobWorkflowError("AI cleanup is only available for active mobile jobs from this page.")

        cleanup_result = cleanup_summary_text(
            summary_text=submitted_summary_text,
            cleanup_context=AiCleanupContext(
                job_id=job.id,
                source="mobile",
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
                "source": "mobile",
                "provider": cleanup_result.provider,
                "model": cleanup_result.model,
                "input_text_length": len(submitted_summary_text),
                "output_text_length": len(cleanup_result.cleaned_text),
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


@router.websocket("/jobs/{job_id}/description/audio/stream")
async def stream_audio_description(
    job_id: str,
    websocket: WebSocket,
    database_session: Session = Depends(get_database_session),
) -> None:
    """Accept chunked microphone audio over WebSocket and transcribe it."""

    await websocket.accept()
    try:
        actor = require_authenticated_username_from_session(websocket.session)
        web_user_id = require_web_user_id_from_session(websocket.session)
    except HTTPException as exc:
        await _send_audio_stream_error(websocket, str(exc.detail), status.WS_1008_POLICY_VIOLATION)
        return

    try:
        start_payload = await _receive_audio_stream_json(websocket)
        if str(start_payload.get("type", "")).strip().lower() != "start":
            raise AudioStreamProtocolError("Audio stream must start with metadata.")

        # Browser WebSocket APIs cannot send custom CSRF headers. The token is
        # therefore sent in the first JSON message rather than the URL, keeping
        # it out of reverse-proxy access logs while still validating before any
        # audio bytes are accepted or transcribed.
        validate_csrf_session_token(websocket.session, str(start_payload.get("csrf_token", "")))
        content_type = _normalize_audio_stream_content_type(start_payload.get("content_type"))
        filename = _safe_audio_stream_filename(start_payload.get("filename"))

        web_user = get_enabled_web_user_by_id_or_raise(database_session, web_user_id)
        job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(job, web_user.id)
        ensure_job_can_record_description(job)

        record_audit_event(
            database_session,
            actor=actor,
            action="job.description.audio_stream_started",
            job_id=job.id,
            details={
                "content_type": content_type,
                "max_audio_bytes": settings.max_audio_upload_bytes,
            },
        )
        database_session.commit()
        await websocket.send_json(
            {
                "type": "ready",
                "max_audio_bytes": settings.max_audio_upload_bytes,
            }
        )
        await _receive_audio_stream_chunks(
            websocket=websocket,
            database_session=database_session,
            actor=actor,
            job_id=job_id,
            filename=filename,
            content_type=content_type,
        )
    except WebSocketDisconnect:
        database_session.rollback()
    except HTTPException as exc:
        database_session.rollback()
        await _send_audio_stream_error(websocket, str(exc.detail), status.WS_1008_POLICY_VIOLATION)
    except (AudioStreamProtocolError, JobWorkflowError, WebUserError) as exc:
        database_session.rollback()
        await _send_audio_stream_error(websocket, str(exc), status.WS_1008_POLICY_VIOLATION)


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
        web_user = _current_enabled_web_user(request, database_session)
        existing_job = get_job_or_raise(database_session, job_id)
        ensure_job_owned_by_web_user(existing_job, web_user.id)
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
    except (HTTPException, JobWorkflowError, TranscriptionError, WebUserError) as exc:
        database_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(getattr(exc, "detail", exc))) from exc

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
