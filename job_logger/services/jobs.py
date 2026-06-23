"""Business rules for job capture, review, and submission."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy import update as sqlalchemy_update
from sqlalchemy.orm import Session

from job_logger.enums import JobStatus, TicketStatus, TranscriptionStatus, WorkLocation
from job_logger.models import Job, SubmissionAttempt
from job_logger.services.autotask import AutotaskSubmissionError, get_autotask_provider, split_autotask_summary_notes
from job_logger.services.transcription import TranscriptionError, TranscriptionResult, get_transcription_provider
from job_logger.time_utils import (
    enforce_minimum_rounded_end,
    local_date_for,
    now_utc,
    parse_local_form_datetime,
    round_end_for_technician,
    round_start_for_technician,
)

AUTOTASK_TICKET_NUMBER_PATTERN = re.compile(r"^T\d{8}\.\d{4}$")
MAX_ACTIVE_JOBS = 2
MAX_CLIENT_NAME_LENGTH = 120
MAX_TICKET_TITLE_LENGTH = 240
MAX_TICKET_DESCRIPTION_LENGTH = 8000
ALLOWED_WORK_IN_PROGRESS_TIME_MINUTE_DELTA = {-15, 15}
SUCCESSFUL_SUBMISSION_PROTECTED_MESSAGE = (
    "Submitted Autotask jobs cannot be deleted locally, resent, or have ticket identity changed. "
    "Use Submit changes for date, time, summary, or intentional ticket status changes, or Delete From Autotask "
    "to remove the external time entry."
)
RECORDABLE_JOB_STATUSES = {
    JobStatus.ACTIVE,
    JobStatus.READY_FOR_REVIEW,
    JobStatus.SUBMISSION_FAILED,
}
DESCRIPTION_RECORDING_UNAVAILABLE_MESSAGE = (
    "Audio descriptions can only be recorded before the job has been submitted to Autotask."
)
@dataclass(frozen=True)
class ReviewFields:
    """Validated editable fields submitted from the review form."""

    # ticket_number is the reviewed Autotask ticket number.
    ticket_number: str | None

    # ticket_title is the selected Autotask ticket title shown in review.
    ticket_title: str | None

    # ticket_description is read-only context from the selected Autotask ticket.
    ticket_description: str | None

    # ticket_status is the requested ticket status from the allowed enum list.
    ticket_status: TicketStatus

    # summary_notes are submitted to Autotask as the time-entry notes.
    summary_notes: str

    # work_location is parsed from the visible Autotask summary prefix.
    work_location: WorkLocation

    # rounded_start_utc is the reviewer-approved local start time converted to UTC.
    rounded_start_utc: datetime

    # rounded_end_utc is the reviewer-approved local end time converted to UTC.
    # It is optional while a job is still active.
    rounded_end_utc: datetime | None

    # local_work_date is the reviewer-selected America/Detroit date.
    local_work_date: date

    # client_name is the optional client reference captured and editable in review.
    client_name: str | None

    # autotask_company_id is the selected Autotask company when chosen from lookup.
    autotask_company_id: int | None


def _normalize_optional_text(text_value: str | None, *, max_length: int) -> str | None:
    """Trim user text and keep only a bounded value or None."""

    normalized_text = (text_value or "").strip()
    if not normalized_text:
        return None

    if len(normalized_text) > max_length:
        raise JobWorkflowError(f"Text fields must be {max_length} characters or fewer.")

    return normalized_text


def _apply_summary_text(job: Job, summary_text: str | None) -> Job:
    """Apply a summary value to both mutable description fields safely."""

    safe_summary_text = (summary_text or "").strip()
    if not safe_summary_text:
        return job

    if len(safe_summary_text) > 32000:
        raise JobWorkflowError("Summary notes must be 32,000 characters or fewer.")

    job.summary_notes = safe_summary_text
    job.description_text = safe_summary_text
    job.transcription_status = TranscriptionStatus.SUCCEEDED
    job.transcription_provider = "browser"
    job.transcription_error = None
    return job


def _normalize_active_time_delta_minutes(delta_minutes: int | str, *, field_name: str) -> int:
    """Normalize allowed minute deltas for active-job time adjustments."""

    try:
        normalized_delta = int(delta_minutes)
    except (TypeError, ValueError) as exc:
        raise JobWorkflowError("A valid minute delta is required.") from exc

    if normalized_delta not in ALLOWED_WORK_IN_PROGRESS_TIME_MINUTE_DELTA:
        raise JobWorkflowError(f"{field_name} adjustment must be in 15-minute increments.")

    return normalized_delta


def normalize_start_time_delta_minutes(delta_minutes: int | str) -> int:
    """Normalize allowed minute deltas for active-job rounded start adjustments."""

    return _normalize_active_time_delta_minutes(delta_minutes, field_name="Start-time")


def normalize_stop_time_delta_minutes(delta_minutes: int | str) -> int:
    """Normalize allowed minute deltas for active-job rounded stop adjustments."""

    return _normalize_active_time_delta_minutes(delta_minutes, field_name="Stop-time")


class JobWorkflowError(RuntimeError):
    """Raised when a requested job workflow transition is invalid."""


def is_job_locked_after_successful_submission(job: Job) -> bool:
    """Return whether a job has an existing successful Autotask submission."""

    # status_locked covers current records that completed the normal submission
    # path. Once this state is reached, ticket identity and destructive actions
    # stay protected; date/time/status/summary changes must go through the
    # explicit existing-entry update path.
    status_locked = job.status == JobStatus.SUBMITTED

    # external_id_locked preserves immutability for older or partially migrated
    # successful records where the remote Autotask time-entry ID is the strongest
    # evidence that the job has already been accepted externally.
    external_id_locked = bool(job.autotask_external_id)

    # submitted_at_locked covers successful records even if a provider does not
    # return an external identifier. The timestamp is only set after a successful
    # submission in the normal workflow.
    submitted_at_locked = job.autotask_submitted_at_utc is not None

    return status_locked or external_id_locked or submitted_at_locked


def ensure_job_is_not_locked_after_successful_submission(job: Job) -> None:
    """Block review actions that are not valid after successful submission."""

    if is_job_locked_after_successful_submission(job):
        raise JobWorkflowError(SUCCESSFUL_SUBMISSION_PROTECTED_MESSAGE)


def ensure_job_is_successfully_submitted(job: Job) -> None:
    """Require a job with an existing successful Autotask submission."""

    if not is_job_locked_after_successful_submission(job):
        raise JobWorkflowError("Only submitted Autotask jobs can use Submit changes.")


def ensure_job_can_record_description(job: Job) -> None:
    """Allow audio description recording only before successful Autotask submission."""

    ensure_job_is_not_locked_after_successful_submission(job)
    if job.status not in RECORDABLE_JOB_STATUSES:
        raise JobWorkflowError(DESCRIPTION_RECORDING_UNAVAILABLE_MESSAGE)


def ensure_job_ready_for_autotask_submission(job: Job) -> None:
    """Require every local field needed before any Autotask submission attempt."""

    if not job.ticket_number:
        raise JobWorkflowError("Ticket number is required before Autotask submission.")
    if job.ticket_status is None:
        raise JobWorkflowError("Ticket status is required before Autotask submission.")
    if job.rounded_end_utc is None:
        raise JobWorkflowError("End time is required before Autotask submission.")
    if not (job.summary_notes or job.description_text or "").strip():
        raise JobWorkflowError("Summary notes are required before Autotask submission.")


def list_active_jobs(database_session: Session) -> list[Job]:
    """Return all active jobs in slot/date order."""

    active_jobs = list(database_session.execute(select(Job).where(Job.status == JobStatus.ACTIVE)).scalars())
    active_jobs.sort(key=lambda job: ((job.job_slot or 99), job.created_at_utc))
    return active_jobs


def list_active_jobs_for_web_user(database_session: Session, web_user_id: str) -> list[Job]:
    """Return active jobs owned by one managed web user."""

    active_jobs = list(
        database_session.execute(
            select(Job).where(Job.status == JobStatus.ACTIVE, Job.web_user_id == web_user_id)
        ).scalars()
    )
    active_jobs.sort(key=lambda job: ((job.job_slot or 99), job.created_at_utc))
    return active_jobs


def get_active_job(database_session: Session, web_user_id: str | None = None) -> Job | None:
    """Return the first active job, if any."""

    active_jobs = list_active_jobs_for_web_user(database_session, web_user_id) if web_user_id else list_active_jobs(database_session)
    if not active_jobs:
        return None

    return active_jobs[0]


def _next_active_job_slot(active_jobs: list[Job]) -> int:
    """Return the next available active slot between 1 and 2."""

    if len(active_jobs) >= MAX_ACTIVE_JOBS:
        raise JobWorkflowError("A maximum of two jobs can be active at one time.")

    if len(active_jobs) == 0:
        return 1

    if len(active_jobs) == 1:
        existing_slot = active_jobs[0].job_slot
        if existing_slot == 1:
            return 2
        if existing_slot == 2:
            return 1
        return 2

    occupied_slots = {job.job_slot for job in active_jobs if job.job_slot in {1, 2}}
    for slot_number in (1, 2):
        if slot_number not in occupied_slots:
            return slot_number

    raise JobWorkflowError("No active job slots are available.")


def get_job_or_raise(database_session: Session, job_id: str) -> Job:
    """Return a job by ID or raise a workflow error."""

    job = database_session.get(Job, job_id)
    if job is None:
        raise JobWorkflowError("Job was not found.")

    return job


def ensure_job_owned_by_web_user(job: Job, web_user_id: str) -> None:
    """Require that a job belongs to the current managed web user."""

    if job.web_user_id != web_user_id:
        raise JobWorkflowError("This job belongs to another web user.")


def list_review_jobs(database_session: Session, web_user_id: str | None = None) -> list[Job]:
    """Return jobs in newest-first order for the desktop review page."""

    statement = select(Job).order_by(desc(Job.created_at_utc))
    if web_user_id is not None:
        statement = statement.where(Job.web_user_id == web_user_id)
    return list(database_session.execute(statement).scalars())


def completed_ticket_numbers_for_web_user(
    database_session: Session,
    *,
    web_user_id: str,
    ticket_numbers: set[str],
) -> set[str]:
    """Return local ticket numbers that have any Complete time entry for one user."""

    normalized_ticket_numbers = {
        ticket_number.strip().upper()
        for ticket_number in ticket_numbers
        if ticket_number and ticket_number.strip()
    }
    if not normalized_ticket_numbers:
        return set()

    rows = database_session.execute(
        select(Job.ticket_number).where(
            Job.web_user_id == web_user_id,
            Job.ticket_status == TicketStatus.COMPLETE,
            Job.ticket_number.in_(normalized_ticket_numbers),
        )
    ).scalars()
    return {
        ticket_number.strip().upper()
        for ticket_number in rows
        if ticket_number and ticket_number.strip()
    }


def normalize_ticket_number(ticket_number: str | None, *, required: bool) -> str | None:
    """Return a normalized Autotask ticket number or raise a workflow error."""

    normalized_ticket_number = (ticket_number or "").strip().upper()
    if not normalized_ticket_number:
        if required:
            raise JobWorkflowError("Ticket number is required.")
        return None

    if len(normalized_ticket_number) > 50:
        raise JobWorkflowError("Ticket number must be 50 characters or fewer.")

    if not AUTOTASK_TICKET_NUMBER_PATTERN.fullmatch(normalized_ticket_number):
        raise JobWorkflowError("Ticket number must match the Autotask format TYYYYMMDD.####, such as T20260326.0018.")

    return normalized_ticket_number


def normalize_ticket_status(ticket_status: TicketStatus | str | None, *, required: bool = False) -> TicketStatus | None:
    """Return a supported local ticket status or raise a workflow error."""

    if isinstance(ticket_status, TicketStatus):
        return ticket_status

    normalized_ticket_status = str(ticket_status or "").strip()
    if not normalized_ticket_status:
        if required:
            raise JobWorkflowError("Ticket status is required.")
        return None

    try:
        return TicketStatus(normalized_ticket_status)
    except ValueError as exc:
        raise JobWorkflowError("Ticket status is invalid.") from exc


def normalize_ticket_title(ticket_title: str | None) -> str | None:
    """Return a bounded Autotask ticket title captured from ticket lookup."""

    return _normalize_optional_text(ticket_title, max_length=MAX_TICKET_TITLE_LENGTH)


def normalize_ticket_description(ticket_description: str | None) -> str | None:
    """Return a bounded Autotask ticket description captured from ticket lookup."""

    return _normalize_optional_text(ticket_description, max_length=MAX_TICKET_DESCRIPTION_LENGTH)


def normalize_client_name(client_name: str | None) -> str | None:
    """Return a safe client name value for persistence."""

    return _normalize_optional_text(client_name, max_length=MAX_CLIENT_NAME_LENGTH)


def normalize_autotask_company_id(autotask_company_id: int | str | None) -> int | None:
    """Return a positive Autotask company ID or None for manual client names."""

    if autotask_company_id is None:
        return None

    if isinstance(autotask_company_id, str) and not autotask_company_id.strip():
        return None

    try:
        normalized_company_id = int(autotask_company_id)
    except (TypeError, ValueError) as exc:
        raise JobWorkflowError("Autotask company selection is invalid.") from exc

    if normalized_company_id <= 0:
        raise JobWorkflowError("Autotask company selection is invalid.")

    return normalized_company_id


def normalize_work_location(work_location: WorkLocation | str | None) -> WorkLocation:
    """Return a supported work-location mode for Autotask note prefixing."""

    if isinstance(work_location, WorkLocation):
        return work_location

    normalized_location = (work_location or WorkLocation.REMOTE.value).strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return WorkLocation(normalized_location)
    except ValueError as exc:
        raise JobWorkflowError("Work location must be Remote or On-Site.") from exc


def normalize_client_name_required(client_name: str | None) -> str:
    """Require a non-empty client name when transitioning a job to review."""

    normalized_client_name = normalize_client_name(client_name)
    if normalized_client_name is None:
        raise JobWorkflowError("Client name is required when ending work.")

    return normalized_client_name


def preserve_locked_active_autotask_client(
    job: Job,
    client_name: str | None,
    autotask_company_id: int | str | None,
) -> bool:
    """Validate submitted active-job client fields when an Autotask company is locked.

    Active mobile jobs lock the selected Autotask company after lookup so the
    operator cannot accidentally drift the visible client name away from the
    company ID used for ticket lookup. The UI submits hidden copies for normal
    form flow, but this service-level check is the authoritative guard against
    crafted requests that try to replace the selected company while the job is
    still active.
    """

    if job.autotask_company_id is None:
        return False

    submitted_autotask_company_id = normalize_autotask_company_id(autotask_company_id)
    if submitted_autotask_company_id is not None and submitted_autotask_company_id != job.autotask_company_id:
        raise JobWorkflowError("The selected Autotask company is locked for this active job.")

    submitted_client_name = normalize_client_name(client_name)
    if submitted_client_name is not None and job.client_name and submitted_client_name != job.client_name:
        raise JobWorkflowError("The selected Autotask client is locked for this active job.")

    if submitted_client_name is not None and not job.client_name:
        job.client_name = submitted_client_name

    return True


def start_job(
    database_session: Session,
    web_user_id: str | None = None,
    ticket_number: str | None = None,
    client_name: str | None = None,
    autotask_company_id: int | str | None = None,
    work_location: WorkLocation | str | None = WorkLocation.REMOTE,
    ticket_status: TicketStatus | str | None = None,
) -> Job:
    """Create a new active job while enforcing the two-job overlap limit."""

    active_jobs = list_active_jobs_for_web_user(database_session, web_user_id) if web_user_id else list_active_jobs(database_session)
    job_slot = _next_active_job_slot(active_jobs)
    normalized_ticket_number = normalize_ticket_number(ticket_number, required=False)
    normalized_client_name = normalize_client_name(client_name)
    normalized_autotask_company_id = normalize_autotask_company_id(autotask_company_id)
    normalized_work_location = normalize_work_location(work_location)
    normalized_ticket_status = normalize_ticket_status(ticket_status)
    start_timestamp = now_utc()
    rounded_start_timestamp = round_start_for_technician(start_timestamp)
    job = Job(
        status=JobStatus.ACTIVE,
        web_user_id=web_user_id,
        ticket_number=normalized_ticket_number,
        ticket_status=normalized_ticket_status,
        job_slot=job_slot,
        client_name=normalized_client_name,
        autotask_company_id=normalized_autotask_company_id,
        work_location=normalized_work_location,
        raw_start_utc=start_timestamp,
        rounded_start_utc=rounded_start_timestamp,
        local_work_date=local_date_for(rounded_start_timestamp),
    )
    database_session.add(job)
    database_session.flush()
    return job


def update_active_job_ticket_number(
    database_session: Session,
    job_id: str,
    ticket_number: str | None,
    client_name: str | None = None,
    autotask_company_id: int | str | None = None,
    ticket_title: str | None = None,
    ticket_description: str | None = None,
    work_location: WorkLocation | str | None = None,
    ticket_status: TicketStatus | str | None = None,
) -> Job:
    """Update the optional Autotask ticket number and client while a job is active."""

    job = get_job_or_raise(database_session, job_id)
    if job.status != JobStatus.ACTIVE:
        raise JobWorkflowError("Ticket numbers can only be updated from mobile during an active job.")

    locked_autotask_client_preserved = False
    if client_name is not None:
        locked_autotask_client_preserved = preserve_locked_active_autotask_client(job, client_name, autotask_company_id)

    if ticket_number is not None:
        previous_ticket_number = job.ticket_number
        normalized_ticket_number = normalize_ticket_number(ticket_number, required=False)
        normalized_ticket_title = normalize_ticket_title(ticket_title) if normalized_ticket_number else None
        normalized_ticket_description = normalize_ticket_description(ticket_description) if normalized_ticket_number else None
        job.ticket_number = normalized_ticket_number
        if normalized_ticket_number is None:
            job.ticket_title = None
            job.ticket_description = None
        else:
            ticket_number_changed = normalized_ticket_number != previous_ticket_number
            if normalized_ticket_title is not None:
                job.ticket_title = normalized_ticket_title
            elif ticket_number_changed:
                job.ticket_title = None
            if normalized_ticket_description is not None:
                job.ticket_description = normalized_ticket_description
            elif ticket_number_changed:
                job.ticket_description = None

    if client_name is not None and not locked_autotask_client_preserved:
        job.client_name = normalize_client_name(client_name)
        job.autotask_company_id = normalize_autotask_company_id(autotask_company_id)

    if work_location is not None:
        job.work_location = normalize_work_location(work_location)

    if ticket_status is not None:
        job.ticket_status = normalize_ticket_status(ticket_status)

    return job


def delete_active_job(database_session: Session, job: Job) -> Job:
    """Delete an active in-progress job that the user explicitly discarded."""

    if job.status != JobStatus.ACTIVE:
        raise JobWorkflowError("Only an active job can be deleted from the mobile work page.")

    database_session.delete(job)
    return job


def apply_manual_summary_to_job(
    database_session: Session,
    job_id: str,
    summary_text: str,
) -> Job:
    """Persist manual summary text on completion when browser text was typed."""

    job = get_job_or_raise(database_session, job_id)
    # Keep the completion path permissive because description capture should not
    # block the ability to end work if no manual text was entered.
    return _apply_summary_text(job, summary_text)


def adjust_active_job_rounded_start(database_session: Session, job_id: str, delta_minutes: int | str) -> Job:
    """Shift the active rounded start time by a constrained minute delta."""

    job = get_job_or_raise(database_session, job_id)
    if job.status != JobStatus.ACTIVE:
        raise JobWorkflowError("Only active jobs can have rounded start times adjusted.")

    normalized_delta = normalize_start_time_delta_minutes(delta_minutes)
    job.rounded_start_utc = round_start_for_technician(
        job.rounded_start_utc + timedelta(minutes=normalized_delta)
    )
    if job.rounded_end_utc is not None:
        job.rounded_end_utc = enforce_minimum_rounded_end(job.rounded_start_utc, job.rounded_end_utc)
    job.local_work_date = local_date_for(job.rounded_start_utc)
    return job


def rounded_stop_for_active_job(job: Job, timestamp: datetime | None = None) -> datetime:
    """Return the current technician-favoring rounded stop for an active job."""

    if job.status != JobStatus.ACTIVE:
        raise JobWorkflowError("Only active jobs can have a live rounded stop time.")

    stop_timestamp = timestamp or now_utc()
    rounded_stop_timestamp = round_end_for_technician(stop_timestamp)
    return enforce_minimum_rounded_end(job.rounded_start_utc, rounded_stop_timestamp)


def adjust_active_job_rounded_stop(database_session: Session, job_id: str, delta_minutes: int | str) -> Job:
    """Shift the active rounded stop time by a constrained minute delta."""

    job = get_job_or_raise(database_session, job_id)
    if job.status != JobStatus.ACTIVE:
        raise JobWorkflowError("Only active jobs can have rounded stop times adjusted.")

    normalized_delta = normalize_stop_time_delta_minutes(delta_minutes)
    current_rounded_stop = job.rounded_end_utc or rounded_stop_for_active_job(job)
    requested_rounded_stop = round_end_for_technician(
        current_rounded_stop + timedelta(minutes=normalized_delta)
    )
    job.rounded_end_utc = enforce_minimum_rounded_end(job.rounded_start_utc, requested_rounded_stop)
    return job


def end_job(
    database_session: Session,
    job_id: str,
    client_name: str | None = None,
    autotask_company_id: int | str | None = None,
) -> Job:
    """End an active job and move it to review."""

    job = get_job_or_raise(database_session, job_id)
    if job.status != JobStatus.ACTIVE:
        raise JobWorkflowError("Only an active job can be ended.")

    locked_autotask_client_preserved = preserve_locked_active_autotask_client(job, client_name, autotask_company_id)
    submitted_client_name = normalize_client_name(client_name)
    if submitted_client_name is not None and not locked_autotask_client_preserved:
        job.client_name = submitted_client_name
        job.autotask_company_id = normalize_autotask_company_id(autotask_company_id)
    elif not job.client_name:
        # Require an explicit name here if no name was previously captured.
        job.client_name = normalize_client_name_required(job.client_name)

    end_timestamp = now_utc()
    rounded_end_timestamp = job.rounded_end_utc or round_end_for_technician(end_timestamp)
    job.raw_end_utc = end_timestamp
    job.rounded_end_utc = enforce_minimum_rounded_end(job.rounded_start_utc, rounded_end_timestamp)
    job.local_work_date = local_date_for(job.rounded_start_utc)
    job.status = JobStatus.READY_FOR_REVIEW
    return job


def update_description_text(database_session: Session, job_id: str, description_text: str) -> Job:
    """Replace the active-job summary notes from browser text input."""

    job = get_job_or_raise(database_session, job_id)
    if job.status != JobStatus.ACTIVE:
        raise JobWorkflowError("Summary notes can only be recorded during an active job.")

    safe_description_text = description_text.strip()
    if not safe_description_text:
        raise JobWorkflowError("Summary notes cannot be empty.")

    return _apply_summary_text(job, safe_description_text)


def apply_transcription_result_to_job(
    database_session: Session,
    *,
    job_id: str,
    transcription_result: TranscriptionResult,
) -> Job:
    """Persist a completed speech-to-text result on a recordable job."""

    job = get_job_or_raise(database_session, job_id)
    ensure_job_can_record_description(job)

    job.summary_notes = transcription_result.text
    job.description_text = transcription_result.text
    job.transcription_provider = transcription_result.provider
    job.transcription_status = TranscriptionStatus.SUCCEEDED
    job.transcription_error = None
    return job


def apply_transcription_result_to_active_job(
    database_session: Session,
    *,
    job_id: str,
    transcription_result: TranscriptionResult,
) -> Job:
    """Persist a completed speech-to-text result on an active or review job."""

    return apply_transcription_result_to_job(
        database_session,
        job_id=job_id,
        transcription_result=transcription_result,
    )


def mark_job_transcription_failed(
    database_session: Session,
    *,
    job_id: str,
    error_message: str,
) -> Job:
    """Persist a safe transcription failure message on a recordable job."""

    job = get_job_or_raise(database_session, job_id)
    ensure_job_can_record_description(job)

    job.transcription_status = TranscriptionStatus.FAILED
    job.transcription_error = error_message
    return job


def mark_active_job_transcription_failed(
    database_session: Session,
    *,
    job_id: str,
    error_message: str,
) -> Job:
    """Persist a safe transcription failure message on an active or review job."""

    return mark_job_transcription_failed(
        database_session,
        job_id=job_id,
        error_message=error_message,
    )


def transcribe_job_audio(
    database_session: Session,
    *,
    job_id: str,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
) -> Job:
    """Transcribe uploaded audio for a recordable job without storing raw audio."""

    job = get_job_or_raise(database_session, job_id)
    ensure_job_can_record_description(job)

    try:
        transcription_result = get_transcription_provider().transcribe(
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
        )
    except TranscriptionError as exc:
        mark_job_transcription_failed(database_session, job_id=job_id, error_message=str(exc))
        raise

    return apply_transcription_result_to_job(
        database_session,
        job_id=job_id,
        transcription_result=transcription_result,
    )


def transcribe_active_job_audio(
    database_session: Session,
    *,
    job_id: str,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
) -> Job:
    """Transcribe uploaded audio for an active or review job without storing raw audio."""

    return transcribe_job_audio(
        database_session,
        job_id=job_id,
        audio_bytes=audio_bytes,
        filename=filename,
        content_type=content_type,
    )


def validate_review_fields(
    form_values: dict[str, str],
    *,
    require_ticket_number: bool = False,
    require_end_time_fields: bool = True,
) -> ReviewFields:
    """Validate and normalize editable review form values."""

    ticket_number = normalize_ticket_number(form_values.get("ticket_number"), required=require_ticket_number)
    if ticket_number is None and require_ticket_number:
        raise JobWorkflowError("Ticket number is required.")
    ticket_title = normalize_ticket_title(form_values.get("ticket_title")) if ticket_number else None
    ticket_description = normalize_ticket_description(form_values.get("ticket_description")) if ticket_number else None

    ticket_status = normalize_ticket_status(form_values.get("ticket_status"), required=True)
    if ticket_status is None:
        raise JobWorkflowError("Ticket status is required.")

    submitted_summary_notes = form_values.get("summary_notes", "").strip()
    if not submitted_summary_notes:
        submitted_summary_notes = form_values.get("description_text", "").strip()
    fallback_work_location = normalize_work_location(form_values.get("work_location"))
    work_location, summary_notes = split_autotask_summary_notes(
        submitted_summary_notes,
        fallback_work_location,
    )
    if not summary_notes:
        raise JobWorkflowError("Summary notes are required.")

    if len(summary_notes) > 32000:
        raise JobWorkflowError("Summary notes must be 32,000 characters or fewer.")

    job_date = form_values.get("job_date", "") or form_values.get("start_date", "")
    start_time = form_values.get("start_time", "")
    end_time = form_values.get("end_time", "")
    client_name = normalize_client_name(form_values.get("client_name"))
    autotask_company_id = normalize_autotask_company_id(form_values.get("autotask_company_id"))
    legacy_end_date = form_values.get("end_date", "")
    if legacy_end_date and job_date and legacy_end_date != job_date:
        raise JobWorkflowError("Jobs cannot span multiple dates. Use one job date with start and end times.")
    if not job_date or not start_time:
        raise JobWorkflowError("Job date and start time fields are required.")

    try:
        rounded_start_utc = round_start_for_technician(parse_local_form_datetime(job_date, start_time))
    except ValueError as exc:
        raise JobWorkflowError("Job date or time is invalid.") from exc

    local_work_date = local_date_for(rounded_start_utc)
    if str(local_work_date) != job_date:
        raise JobWorkflowError("Rounded start time must stay on the selected job date.")

    rounded_end_utc = None
    should_parse_end_time = require_end_time_fields or bool(end_time)
    if should_parse_end_time:
        if not end_time:
            raise JobWorkflowError("End time is required.")

        try:
            rounded_end_utc = round_end_for_technician(parse_local_form_datetime(job_date, end_time))
        except ValueError as exc:
            raise JobWorkflowError("Job date or time is invalid.") from exc

        if str(local_date_for(rounded_end_utc)) != job_date:
            raise JobWorkflowError("Rounded end time must stay on the selected job date.")
        if rounded_end_utc <= rounded_start_utc:
            raise JobWorkflowError("End time must be after start time on the same job date.")
    return ReviewFields(
        ticket_number=ticket_number,
        ticket_title=ticket_title,
        ticket_description=ticket_description,
        ticket_status=ticket_status,
        summary_notes=summary_notes,
        work_location=work_location,
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_end_utc,
        local_work_date=local_work_date,
        client_name=client_name,
        autotask_company_id=autotask_company_id,
    )


def apply_review_fields(job: Job, review_fields: ReviewFields) -> Job:
    """Apply validated review fields to a job."""

    ensure_job_is_not_locked_after_successful_submission(job)

    if job.status == JobStatus.ACTIVE and review_fields.rounded_end_utc is not None:
        raise JobWorkflowError("Active jobs cannot receive an end time while active.")

    if review_fields.ticket_number is not None:
        ticket_number_changed = review_fields.ticket_number != job.ticket_number
        job.ticket_number = review_fields.ticket_number
        if review_fields.ticket_title is not None:
            job.ticket_title = review_fields.ticket_title
        if review_fields.ticket_description is not None:
            job.ticket_description = review_fields.ticket_description
        elif ticket_number_changed:
            job.ticket_title = None
            job.ticket_description = None
    job.ticket_status = review_fields.ticket_status
    job.summary_notes = review_fields.summary_notes
    job.description_text = review_fields.summary_notes
    job.work_location = review_fields.work_location
    job.rounded_start_utc = review_fields.rounded_start_utc
    if review_fields.rounded_end_utc is not None:
        job.rounded_end_utc = review_fields.rounded_end_utc
    elif job.status == JobStatus.ACTIVE and job.rounded_end_utc is not None:
        job.rounded_end_utc = enforce_minimum_rounded_end(job.rounded_start_utc, job.rounded_end_utc)
    job.local_work_date = review_fields.local_work_date
    job.client_name = review_fields.client_name
    job.autotask_company_id = review_fields.autotask_company_id
    return job


def _apply_submitted_entry_fields(job: Job, review_fields: ReviewFields) -> Job:
    """Apply only fields that can be synced to an existing Autotask time entry."""

    ensure_job_is_successfully_submitted(job)
    if review_fields.rounded_end_utc is None:
        raise JobWorkflowError("End time is required before editing a submitted Autotask entry.")

    job.ticket_status = review_fields.ticket_status
    job.summary_notes = review_fields.summary_notes
    job.description_text = review_fields.summary_notes
    job.work_location = review_fields.work_location
    job.rounded_start_utc = review_fields.rounded_start_utc
    job.rounded_end_utc = review_fields.rounded_end_utc
    job.local_work_date = review_fields.local_work_date
    return job


def update_submitted_job_autotask_entry(
    database_session: Session,
    job: Job,
    review_fields: ReviewFields,
    *,
    resource_id: int,
) -> Job:
    """Update the existing external Autotask time entry for a submitted job."""

    ensure_job_is_successfully_submitted(job)
    external_id = (job.autotask_external_id or "").strip()
    if not external_id:
        raise JobWorkflowError("This submitted job does not have an Autotask time entry ID to update.")

    previous_values = {
        "ticket_status": job.ticket_status,
        "summary_notes": job.summary_notes,
        "description_text": job.description_text,
        "work_location": job.work_location,
        "rounded_start_utc": job.rounded_start_utc,
        "rounded_end_utc": job.rounded_end_utc,
        "local_work_date": job.local_work_date,
    }
    _apply_submitted_entry_fields(job, review_fields)

    try:
        submission_result = get_autotask_provider().update_time_entry(
            job,
            external_id,
            resource_id=resource_id,
            previous_ticket_status=previous_values["ticket_status"],
        )
    except AutotaskSubmissionError as exc:
        submission_result = None
        for field_name, previous_value in previous_values.items():
            setattr(job, field_name, previous_value)
        job.autotask_error = str(exc)
        job.autotask_provider = "configuration"
        database_session.add(
            SubmissionAttempt(
                job_id=job.id,
                provider="configuration",
                idempotency_key=job.idempotency_key,
                succeeded=False,
                external_id=external_id,
                safe_error=str(exc),
                request_snapshot={},
            )
        )
        return job

    database_session.add(
        SubmissionAttempt(
            job_id=job.id,
            provider=submission_result.provider,
            idempotency_key=job.idempotency_key,
            succeeded=submission_result.succeeded,
            external_id=submission_result.external_id,
            safe_error=submission_result.safe_error,
            request_snapshot=submission_result.request_snapshot,
        )
    )
    job.autotask_provider = submission_result.provider
    if submission_result.succeeded:
        job.status = JobStatus.SUBMITTED
        job.autotask_external_id = submission_result.external_id or external_id
        job.autotask_error = None
    else:
        for field_name, previous_value in previous_values.items():
            setattr(job, field_name, previous_value)
        job.autotask_error = submission_result.safe_error

    return job


def delete_submitted_job_autotask_entry(database_session: Session, job: Job, *, resource_id: int) -> Job:
    """Delete a submitted job's external time entry and return it to review."""

    ensure_job_is_successfully_submitted(job)
    external_id = (job.autotask_external_id or "").strip()
    if not external_id:
        raise JobWorkflowError("This submitted job does not have an Autotask time entry ID to delete.")

    try:
        submission_result = get_autotask_provider().delete_time_entry(job, external_id, resource_id=resource_id)
    except AutotaskSubmissionError as exc:
        job.autotask_error = str(exc)
        job.autotask_provider = "configuration"
        database_session.add(
            SubmissionAttempt(
                job_id=job.id,
                provider="configuration",
                idempotency_key=job.idempotency_key,
                succeeded=False,
                external_id=external_id,
                safe_error=str(exc),
                request_snapshot={},
            )
        )
        return job

    database_session.add(
        SubmissionAttempt(
            job_id=job.id,
            provider=submission_result.provider,
            idempotency_key=job.idempotency_key,
            succeeded=submission_result.succeeded,
            external_id=external_id,
            safe_error=submission_result.safe_error,
            request_snapshot=submission_result.request_snapshot,
        )
    )
    job.autotask_provider = submission_result.provider
    if submission_result.succeeded:
        job.status = JobStatus.READY_FOR_REVIEW
        job.autotask_external_id = None
        job.autotask_submitted_at_utc = None
        job.autotask_error = None
    else:
        job.autotask_error = submission_result.safe_error

    return job


def apply_selected_ticket_from_lookup(
    job: Job,
    ticket_number: str,
    ticket_title: str | None,
    ticket_description: str | None,
    ticket_status: TicketStatus | str | None = None,
) -> Job:
    """Store a ticket selected from the server-side Autotask open-ticket lookup."""

    ensure_job_is_not_locked_after_successful_submission(job)

    normalized_ticket_number = normalize_ticket_number(ticket_number, required=True)
    normalized_ticket_title = normalize_ticket_title(ticket_title)
    normalized_ticket_description = normalize_ticket_description(ticket_description)
    job.ticket_number = normalized_ticket_number
    job.ticket_title = normalized_ticket_title
    job.ticket_description = normalized_ticket_description
    if ticket_status is not None:
        job.ticket_status = normalize_ticket_status(ticket_status)
    return job


def purge_job(database_session: Session, job: Job) -> Job:
    """Delete a local unsubmitted job and related submission attempts from storage."""

    ensure_job_is_not_locked_after_successful_submission(job)

    # Remove dependent submission attempts explicitly so deletion works even when the
    # database does not enforce cascading deletes (for example in sqlite tests).
    database_session.query(SubmissionAttempt).filter_by(job_id=job.id).delete(synchronize_session=False)

    # Keep audit history intact by leaving audit event rows in place; they remain
    # with a NULLed job_id so security and troubleshooting context is preserved.
    database_session.delete(job)
    return job


def purge_submitted_job_after_failed_autotask_delete(database_session: Session, job: Job) -> Job:
    """Delete a submitted local job only after its Autotask delete path failed."""

    ensure_job_is_successfully_submitted(job)
    if not (job.autotask_external_id or "").strip():
        raise JobWorkflowError("This submitted job no longer has an Autotask time entry ID.")
    if not (job.autotask_error or "").strip():
        raise JobWorkflowError("Delete From Autotask must fail before this local purge is available.")

    # This is intentionally separate from purge_job because submitted jobs are
    # normally protected. It is a last-resort local cleanup after the remote
    # delete failed and the user explicitly confirms the local-only removal.
    database_session.query(SubmissionAttempt).filter_by(job_id=job.id).delete(synchronize_session=False)
    database_session.delete(job)
    return job


def reset_ticket_data(database_session: Session) -> dict[str, int]:
    """Clear persisted ticket and Autotask submission-state fields for a fresh debug state."""

    jobs_reset = (
        database_session.execute(
            sqlalchemy_update(Job).values(
                ticket_number=None,
                ticket_title=None,
                ticket_description=None,
                autotask_company_id=None,
                ticket_status=None,
                autotask_provider=None,
                autotask_external_id=None,
                autotask_submitted_at_utc=None,
                autotask_error=None,
            )
        ).rowcount
        or 0
    )
    attempts_removed = database_session.query(SubmissionAttempt).delete(synchronize_session=False)

    return {
        "jobs_reset": int(jobs_reset),
        "submission_attempts_removed": int(attempts_removed),
    }


def submit_job_to_autotask(
    database_session: Session,
    job: Job,
    *,
    resource_id: int,
    default_service_desk_role_id: int | None = None,
) -> Job:
    """Submit a locally completed job to the configured Autotask provider."""

    if job.status == JobStatus.ACTIVE:
        raise JobWorkflowError("Active jobs cannot be submitted.")
    ensure_job_is_not_locked_after_successful_submission(job)
    ensure_job_ready_for_autotask_submission(job)

    try:
        submission_result = get_autotask_provider().submit_job(
            job,
            resource_id=resource_id,
            default_service_desk_role_id=default_service_desk_role_id,
        )
    except AutotaskSubmissionError as exc:
        submission_result = None
        job.status = JobStatus.SUBMISSION_FAILED
        job.autotask_error = str(exc)
        job.autotask_provider = "configuration"
        database_session.add(
            SubmissionAttempt(
                job_id=job.id,
                provider="configuration",
                idempotency_key=job.idempotency_key,
                succeeded=False,
                safe_error=str(exc),
                request_snapshot={},
            )
        )
        return job

    database_session.add(
        SubmissionAttempt(
            job_id=job.id,
            provider=submission_result.provider,
            idempotency_key=job.idempotency_key,
            succeeded=submission_result.succeeded,
            external_id=submission_result.external_id,
            safe_error=submission_result.safe_error,
            request_snapshot=submission_result.request_snapshot,
        )
    )

    job.autotask_provider = submission_result.provider
    if submission_result.succeeded:
        job.status = JobStatus.SUBMITTED
        job.autotask_external_id = submission_result.external_id
        job.autotask_submitted_at_utc = datetime.now(UTC)
        job.autotask_error = None
    else:
        job.status = JobStatus.SUBMISSION_FAILED
        job.autotask_error = submission_result.safe_error

    return job
