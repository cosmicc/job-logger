"""Business rules for job capture, review, and submission."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from job_logger.enums import JobStatus, TicketStatus, TranscriptionStatus
from job_logger.models import Job, SubmissionAttempt
from job_logger.services.autotask import AutotaskSubmissionError, get_autotask_provider
from job_logger.services.transcription import TranscriptionError, get_transcription_provider
from job_logger.time_utils import (
    enforce_minimum_rounded_end,
    local_date_for,
    now_utc,
    parse_local_form_datetime,
    round_to_nearest_quarter_hour,
)

AUTOTASK_TICKET_NUMBER_PATTERN = re.compile(r"^T\d{8}\.\d{4}$")


@dataclass(frozen=True)
class ReviewFields:
    """Validated editable fields submitted from the review form."""

    # ticket_number is the reviewed Autotask ticket number.
    ticket_number: str

    # ticket_status is the requested ticket status from the allowed enum list.
    ticket_status: TicketStatus

    # summary_notes are submitted to Autotask as the time-entry notes.
    summary_notes: str

    # rounded_start_utc is the reviewer-approved local start time converted to UTC.
    rounded_start_utc: datetime

    # rounded_end_utc is the reviewer-approved local end time converted to UTC.
    rounded_end_utc: datetime

    # local_work_date is the reviewer-selected America/Detroit date.
    local_work_date: date


class JobWorkflowError(RuntimeError):
    """Raised when a requested job workflow transition is invalid."""


def get_active_job(database_session: Session) -> Job | None:
    """Return the currently active job, if one exists."""

    return database_session.execute(select(Job).where(Job.status == JobStatus.ACTIVE)).scalar_one_or_none()


def get_job_or_raise(database_session: Session, job_id: str) -> Job:
    """Return a job by ID or raise a workflow error."""

    job = database_session.get(Job, job_id)
    if job is None:
        raise JobWorkflowError("Job was not found.")

    return job


def list_review_jobs(database_session: Session) -> list[Job]:
    """Return jobs in newest-first order for the desktop review page."""

    return list(database_session.execute(select(Job).order_by(desc(Job.created_at_utc))).scalars())


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


def start_job(database_session: Session, ticket_number: str | None = None) -> Job:
    """Create a new active job after ensuring only one job is active."""

    existing_active_job = get_active_job(database_session)
    if existing_active_job is not None:
        raise JobWorkflowError("A job is already active.")

    normalized_ticket_number = normalize_ticket_number(ticket_number, required=False)
    start_timestamp = now_utc()
    rounded_start_timestamp = round_to_nearest_quarter_hour(start_timestamp)
    job = Job(
        status=JobStatus.ACTIVE,
        ticket_number=normalized_ticket_number,
        raw_start_utc=start_timestamp,
        rounded_start_utc=rounded_start_timestamp,
        local_work_date=local_date_for(rounded_start_timestamp),
    )
    database_session.add(job)
    database_session.flush()
    return job


def update_active_job_ticket_number(database_session: Session, job_id: str, ticket_number: str | None) -> Job:
    """Update the optional Autotask ticket number while a job is active."""

    job = get_job_or_raise(database_session, job_id)
    if job.status != JobStatus.ACTIVE:
        raise JobWorkflowError("Ticket numbers can only be updated from mobile during an active job.")

    job.ticket_number = normalize_ticket_number(ticket_number, required=False)
    return job


def end_job(database_session: Session, job_id: str) -> Job:
    """End an active job and move it to review."""

    job = get_job_or_raise(database_session, job_id)
    if job.status != JobStatus.ACTIVE:
        raise JobWorkflowError("Only an active job can be ended.")

    end_timestamp = now_utc()
    rounded_end_timestamp = round_to_nearest_quarter_hour(end_timestamp)
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

    job.summary_notes = safe_description_text
    job.description_text = safe_description_text
    job.transcription_status = TranscriptionStatus.SUCCEEDED
    job.transcription_provider = "browser"
    job.transcription_error = None
    return job


def transcribe_active_job_audio(
    database_session: Session,
    *,
    job_id: str,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
) -> Job:
    """Transcribe uploaded audio for an active job without storing raw audio."""

    job = get_job_or_raise(database_session, job_id)
    if job.status != JobStatus.ACTIVE:
        raise JobWorkflowError("Audio descriptions can only be recorded during an active job.")

    try:
        transcription_result = get_transcription_provider().transcribe(
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
        )
    except TranscriptionError as exc:
        job.transcription_status = TranscriptionStatus.FAILED
        job.transcription_error = str(exc)
        raise

    job.summary_notes = transcription_result.text
    job.description_text = transcription_result.text
    job.transcription_provider = transcription_result.provider
    job.transcription_status = TranscriptionStatus.SUCCEEDED
    job.transcription_error = None
    return job


def validate_review_fields(form_values: dict[str, str]) -> ReviewFields:
    """Validate and normalize editable review form values."""

    ticket_number = normalize_ticket_number(form_values.get("ticket_number"), required=True)
    if ticket_number is None:
        raise JobWorkflowError("Ticket number is required.")

    try:
        ticket_status = TicketStatus(form_values.get("ticket_status", ""))
    except ValueError as exc:
        raise JobWorkflowError("Ticket status is invalid.") from exc

    summary_notes = form_values.get("summary_notes", "").strip()
    if not summary_notes:
        summary_notes = form_values.get("description_text", "").strip()
    if not summary_notes:
        raise JobWorkflowError("Summary notes are required.")

    if len(summary_notes) > 32000:
        raise JobWorkflowError("Summary notes must be 32,000 characters or fewer.")

    start_date = form_values.get("start_date", "")
    start_time = form_values.get("start_time", "")
    end_date = form_values.get("end_date", "")
    end_time = form_values.get("end_time", "")
    if not start_date or not start_time or not end_date or not end_time:
        raise JobWorkflowError("Start and end date/time fields are required.")

    try:
        rounded_start_utc = round_to_nearest_quarter_hour(parse_local_form_datetime(start_date, start_time))
        rounded_end_utc = round_to_nearest_quarter_hour(parse_local_form_datetime(end_date, end_time))
    except ValueError as exc:
        raise JobWorkflowError("Start or end date/time is invalid.") from exc

    rounded_end_utc = enforce_minimum_rounded_end(rounded_start_utc, rounded_end_utc)
    return ReviewFields(
        ticket_number=ticket_number,
        ticket_status=ticket_status,
        summary_notes=summary_notes,
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_end_utc,
        local_work_date=local_date_for(rounded_start_utc),
    )


def apply_review_fields(job: Job, review_fields: ReviewFields) -> Job:
    """Apply validated review fields to a job."""

    if job.status == JobStatus.ACTIVE:
        raise JobWorkflowError("Active jobs must be ended before review.")

    job.ticket_number = review_fields.ticket_number
    job.ticket_status = review_fields.ticket_status
    job.summary_notes = review_fields.summary_notes
    job.description_text = review_fields.summary_notes
    job.rounded_start_utc = review_fields.rounded_start_utc
    job.rounded_end_utc = review_fields.rounded_end_utc
    job.local_work_date = review_fields.local_work_date
    return job


def reject_job(job: Job) -> Job:
    """Mark a non-active job rejected while preserving audit history."""

    if job.status == JobStatus.ACTIVE:
        raise JobWorkflowError("Active jobs must be ended before rejection.")

    job.status = JobStatus.REJECTED
    return job


def submit_job_to_autotask(database_session: Session, job: Job) -> Job:
    """Submit a reviewed job to the configured Autotask provider."""

    if job.status == JobStatus.ACTIVE:
        raise JobWorkflowError("Active jobs cannot be submitted.")

    if job.autotask_external_id:
        job.status = JobStatus.SUBMITTED
        return job

    try:
        submission_result = get_autotask_provider().submit_job(job)
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
