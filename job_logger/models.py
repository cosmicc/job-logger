"""Database models for jobs, submissions, and immutable audit events."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from job_logger.database import Base
from job_logger.enums import JobStatus, TicketStatus, TranscriptionStatus


def utc_now() -> datetime:
    """Return an aware UTC timestamp for database-created audit fields."""

    return datetime.now(UTC)


def uuid_string() -> str:
    """Return a random UUID string that works across PostgreSQL and SQLite tests."""

    return str(uuid.uuid4())


def enum_column(enum_type: type[Any], length: int, comment: str) -> Mapped[Any]:
    """Create a non-native enum column with readable string values."""

    return mapped_column(
        Enum(
            enum_type,
            native_enum=False,
            length=length,
            values_callable=lambda enum_values: [enum_value.value for enum_value in enum_values],
        ),
        nullable=False,
        comment=comment,
    )


class Job(Base):
    """A locally recorded work session awaiting review and Autotask submission."""

    __tablename__ = "jobs"

    # id is a UUID string so audit references remain stable across databases.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string, comment="Stable job UUID.")

    # status controls allowed workflow transitions and review visibility.
    status: Mapped[JobStatus] = enum_column(JobStatus, 32, "Current local job workflow status.")

    # ticket_number is the human Autotask ticket number entered during review.
    ticket_number: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="Autotask ticket number.")

    # job_slot identifies the job position while one or two jobs are active concurrently.
    # Existing jobs are labeled as slot 1 and slot 2 for the overlapping workflow.
    job_slot: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Mobile concurrent job slot (1 for job 1, 2 for job 2).",
    )

    # client_name stores user-provided client context for quick reference at review time.
    client_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        comment="Client reference typed when work starts.",
    )

    # autotask_company_id stores the selected Autotask company/account ID when a
    # user chooses a company from server-side Autotask search results.
    autotask_company_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Selected Autotask company ID for ticket lookup.",
    )

    # ticket_status is the requested local ticket status selected during review.
    ticket_status: Mapped[TicketStatus | None] = mapped_column(
        Enum(
            TicketStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum_values: [enum_value.value for enum_value in enum_values],
        ),
        nullable=True,
        comment="Requested ticket status after review.",
    )

    # summary_notes become Autotask summaryNotes when the job is accepted.
    summary_notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Reviewer-approved time notes.")

    # description_text mirrors summary_notes for compatibility with legacy clients.
    description_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Compatibility mirror of summary_notes for legacy data and payload paths.",
    )

    # raw_start_utc is the exact time the user tapped Start Work.
    raw_start_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Exact job start timestamp stored in UTC.",
    )

    # raw_end_utc is the exact time the user tapped End Work.
    raw_end_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Exact job end timestamp stored in UTC.",
    )

    # rounded_start_utc is the reviewed start rounded to the nearest 15 minutes.
    rounded_start_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Rounded start timestamp stored in UTC.",
    )

    # rounded_end_utc is the reviewed end rounded to the nearest 15 minutes.
    rounded_end_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Rounded end timestamp stored in UTC.",
    )

    # local_work_date is the America/Detroit date shown in review and used for Autotask date context.
    local_work_date: Mapped[Any | None] = mapped_column(Date, nullable=True, comment="America/Detroit work date.")

    # transcription_provider records which provider generated the current text.
    transcription_provider: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="Speech provider name.")

    # transcription_status records success/failure of the latest transcription attempt.
    transcription_status: Mapped[TranscriptionStatus] = mapped_column(
        Enum(
            TranscriptionStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum_values: [enum_value.value for enum_value in enum_values],
        ),
        nullable=False,
        default=TranscriptionStatus.NOT_REQUESTED,
        comment="Latest transcription attempt status.",
    )

    # transcription_error stores a safe diagnostic message without raw audio or provider secrets.
    transcription_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Safe transcription error text.")

    # autotask_provider records whether mock or live Autotask submission was used.
    autotask_provider: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="Autotask provider name.")

    # autotask_external_id stores the remote Autotask time entry ID after successful submission.
    autotask_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="Remote time entry ID.")

    # autotask_submitted_at_utc records when the accepted job was successfully submitted.
    autotask_submitted_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp for successful Autotask submission.",
    )

    # autotask_error stores safe submission diagnostics for reviewer troubleshooting.
    autotask_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Safe Autotask error text.")

    # idempotency_key prevents duplicate remote submissions during retries.
    idempotency_key: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        unique=True,
        default=lambda: f"job-{uuid_string()}",
        comment="Stable local idempotency key for Autotask submission.",
    )

    # created_at_utc and updated_at_utc support audit and troubleshooting.
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # audit_events links immutable job changes to the owning job.
    audit_events: Mapped[list[AuditEvent]] = relationship("AuditEvent", back_populates="job", cascade="save-update")

    __table_args__ = (
        Index("ix_jobs_status_created_at", "status", "created_at_utc"),
        Index("ix_jobs_ticket_number", "ticket_number"),
    )


class AuditEvent(Base):
    """Immutable audit event for security, review, and troubleshooting."""

    __tablename__ = "audit_events"

    # id is a stable UUID so audit rows can be referenced externally if needed.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string, comment="Stable audit UUID.")

    # job_id is nullable for authentication or system-level audit events.
    job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        comment="Optional job UUID associated with the event.",
    )

    # actor stores the authenticated local username or a system actor label.
    actor: Mapped[str] = mapped_column(String(120), nullable=False, comment="Authenticated actor or system label.")

    # action is a compact machine-readable event name.
    action: Mapped[str] = mapped_column(String(80), nullable=False, comment="Machine-readable audit action.")

    # details stores sanitized event context without secrets or raw audio.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, comment="Sanitized event details.")

    # ip_address stores the request IP when available for security review.
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Request client IP if available.")

    # user_agent stores a short browser fingerprint for security troubleshooting.
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Request user agent if available.")

    # created_at_utc is immutable event time.
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # job links audit rows to their parent job.
    job: Mapped[Job | None] = relationship("Job", back_populates="audit_events")

    __table_args__ = (
        Index("ix_audit_events_job_created_at", "job_id", "created_at_utc"),
        Index("ix_audit_events_action_created_at", "action", "created_at_utc"),
    )


class SubmissionAttempt(Base):
    """Append-only record of Autotask submission attempts."""

    __tablename__ = "submission_attempts"

    # id is a stable UUID for troubleshooting individual submission attempts.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string, comment="Stable attempt UUID.")

    # job_id references the accepted job being submitted.
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    # provider stores mock or live Autotask provider identity.
    provider: Mapped[str] = mapped_column(String(50), nullable=False, comment="Submission provider name.")

    # idempotency_key mirrors the job idempotency key used for duplicate prevention.
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False, comment="Submission idempotency key.")

    # succeeded records whether the remote submission completed successfully.
    succeeded: Mapped[bool] = mapped_column(nullable=False, comment="Whether the attempt succeeded.")

    # external_id stores the remote time entry ID when the provider returns one.
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="Remote time entry ID.")

    # safe_error stores non-secret failure detail.
    safe_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Safe submission failure detail.")

    # request_snapshot stores sanitized non-secret request context for audits.
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # created_at_utc records when the attempt happened.
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (Index("ix_submission_attempts_job_created_at", "job_id", "created_at_utc"),)
