"""Database models for users, jobs, submissions, and immutable audit events."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from job_logger.database import Base
from job_logger.enums import JobStatus, ThemeMode, TicketStatus, TranscriptionStatus, WorkLocation


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


class WebUser(Base):
    """Database-managed application user allowed to record Autotask work."""

    __tablename__ = "web_users"

    # id is a UUID string so job ownership stays stable if usernames change.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string, comment="Stable web-user UUID.")

    # full_name is the technician display name shown in admin and review views.
    full_name: Mapped[str] = mapped_column(String(160), nullable=False, comment="Required human-readable user name.")

    # username is the local login name. username_normalized enforces
    # case-insensitive uniqueness while preserving the display spelling.
    username: Mapped[str] = mapped_column(String(120), nullable=False, comment="Required local login username.")
    username_normalized: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        unique=True,
        comment="Case-folded username used for unique login lookup.",
    )

    # password_hash stores only a salted verifier, never the submitted password.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="Salted password verifier.")

    # autotask_resource_id is required because web users can create work entries.
    autotask_resource_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Autotask resource ID used for this user's service calls and time entries.",
    )

    # email is captured from Autotask Resource lookup when available. It is not
    # required for login today, but preserving it avoids another directory query
    # for future user-scoped features.
    email: Mapped[str | None] = mapped_column(
        String(254),
        nullable=True,
        comment="Optional email address captured from the linked Autotask resource.",
    )

    # autotask_default_service_desk_role_id is an explicit fallback role chosen
    # by the super admin for TimeEntries.roleID when a ticket omits assigned
    # role context and Autotask cannot return one unambiguous active role.
    autotask_default_service_desk_role_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Optional active ResourceServiceDeskRoles.roleID fallback used for this user's Autotask time entries.",
    )

    # disabled blocks future local login without deleting job/audit history.
    disabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether this user is blocked from logging in.",
    )

    # is_admin grants this managed user full Diagnostics access only. It does
    # not grant config-super-admin-only user management or broader review scope.
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether this managed user may access /debug and /debug/* diagnostics.",
    )

    # sessions_invalidated_at_utc forces existing signed sessions for this user
    # to log in again without storing session tokens server-side. New logins
    # after this timestamp remain valid until timeout or the next invalidation.
    sessions_invalidated_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC cutoff after which existing signed web-user sessions must be renewed.",
    )

    # last_login_at_utc is informational account metadata for the super-admin
    # user list. It is stamped only after a successful managed-user login.
    last_login_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp for the latest successful managed web-user login.",
    )

    # created_at_utc and updated_at_utc support account-management audit review.
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # jobs links work history to the web user whose Autotask resource was used.
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="web_user")

    # webauthn_credentials stores passkeys registered by this managed web user.
    webauthn_credentials: Mapped[list[WebAuthnCredential]] = relationship(
        "WebAuthnCredential",
        back_populates="web_user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_web_users_disabled", "disabled"),
    )


class UserPreference(Base):
    """Per-authenticated-user configuration values."""

    __tablename__ = "user_preferences"

    # id is stable for backups and future preference expansion.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string, comment="Stable preference UUID.")

    # principal_key identifies the managed web user whose preferences are stored.
    principal_key: Mapped[str] = mapped_column(
        String(180),
        nullable=False,
        unique=True,
        comment="Stable authenticated-user key, such as web_user:<uuid>.",
    )

    # theme stores the preferred visual theme for every authenticated page.
    theme: Mapped[ThemeMode] = enum_column(ThemeMode, 16, "Preferred visual theme.")

    # submit_from_work_in_progress lets a technician end and submit an active
    # job in one step. It defaults off so existing review-first behavior is
    # preserved for every current and newly created account.
    submit_from_work_in_progress: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether ending work submits directly to Autotask instead of stopping in review.",
    )

    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class WebAuthnCredential(Base):
    """A passkey public credential registered to one managed web user."""

    __tablename__ = "webauthn_credentials"

    # id is an internal UUID for management actions. The browser credential ID
    # remains separate because it is opaque authenticator data.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string, comment="Stable passkey row UUID.")

    # web_user_id links the passkey to the managed web-user account it can log in.
    web_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("web_users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Managed web-user UUID that owns this passkey.",
    )

    # credential_id is the URL-safe base64 WebAuthn credential ID. It is unique
    # so authentication can find the owning account without a submitted username.
    credential_id: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        unique=True,
        comment="Base64url-encoded WebAuthn credential ID.",
    )

    # credential_public_key is the COSE public key returned by WebAuthn
    # registration. It verifies future signatures and is not a secret.
    credential_public_key: Mapped[str] = mapped_column(Text, nullable=False, comment="Base64url-encoded public key.")

    # sign_count is updated after successful assertions to detect cloned
    # authenticators when the device reports a monotonically increasing counter.
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="Latest authenticator signature counter.")

    aaguid: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="Authenticator AAGUID returned at registration.")
    credential_type: Mapped[str] = mapped_column(String(40), nullable=False, default="public-key", server_default="public-key")
    device_type: Mapped[str | None] = mapped_column(String(40), nullable=True, comment="WebAuthn credential device type.")
    backed_up: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether the passkey is backed up by the provider.",
    )
    transports: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, comment="Browser-reported authenticator transports.")
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Browser user agent that registered the passkey.")
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_used_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    web_user: Mapped[WebUser] = relationship("WebUser", back_populates="webauthn_credentials")

    __table_args__ = (
        Index("ix_webauthn_credentials_web_user_created_at", "web_user_id", "created_at_utc"),
        Index("ix_webauthn_credentials_credential_id", "credential_id"),
    )


class LoginFailureCounter(Base):
    """Persistent consecutive failed-login count for one enforcement IP and username."""

    __tablename__ = "login_failure_counters"

    # id is a UUID so counter rows are portable across PostgreSQL and SQLite tests.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string, comment="Stable counter UUID.")

    # client_ip is the trusted enforcement IP from sanitized proxy headers or the socket peer.
    client_ip: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Trusted login enforcement IP whose consecutive failures are counted.",
    )

    # username is case-folded so username case changes cannot bypass local lockout.
    username: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
        comment="Case-insensitive submitted username whose consecutive failures are counted.",
    )

    # failed_count resets to zero after a successful local login for this IP and username.
    failed_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Consecutive failed local app logins for this client IP and username.",
    )

    last_failed_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp for the most recent failed login for this client IP and username.",
    )
    last_success_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp for the most recent successful login that reset this IP and username counter.",
    )
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("client_ip", "username", name="uq_login_failure_counters_client_ip_username"),
        Index("ix_login_failure_counters_client_ip", "client_ip"),
    )


class CloudflareIPBlock(Base):
    """App-managed Cloudflare zone IP Access Rule block for a failed-login IP."""

    __tablename__ = "cloudflare_ip_blocks"

    # id is a UUID for portable backup/restore and local audit references.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string, comment="Stable Cloudflare block UUID.")

    # ip_address is the normalized IPv4/IPv6 address this app asked Cloudflare to block.
    ip_address: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        comment="Normalized IP address in an app-managed Cloudflare block.",
    )

    # cloudflare_rule_id identifies only the rule created by this app.
    cloudflare_rule_id: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        unique=True,
        comment="Cloudflare zone IP Access Rule ID created by this app.",
    )

    source: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="manual",
        server_default="manual",
        comment="Whether the app-managed Cloudflare block was manual or automatic.",
    )
    reason: Mapped[str] = mapped_column(
        String(180),
        nullable=False,
        default="",
        server_default="",
        comment="Safe reason for the app-managed Cloudflare block.",
    )
    failure_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Consecutive failed-login count that created an automatic block.",
    )
    notes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
        comment="Note submitted to Cloudflare for this app-managed block.",
    )
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_cloudflare_ip_blocks_ip_address", "ip_address"),
        Index("ix_cloudflare_ip_blocks_created_at", "created_at_utc"),
    )


class HiddenLoginFailure(Base):
    """Failed-login log entry hidden from `/debug` while preserving raw JSONL logs."""

    __tablename__ = "hidden_login_failures"

    # id is a UUID for backup portability.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string, comment="Stable hidden login-failure UUID.")

    # entry_id is the SHA-256 hash of the raw JSONL line shown on `/debug`.
    entry_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        comment="Stable hash of the raw failed-login JSONL line hidden from diagnostics.",
    )

    client_ip: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
        comment="Displayed client IP from the hidden failed-login row.",
    )
    occurred_at_utc: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="",
        server_default="",
        comment="Raw UTC timestamp string from the hidden failed-login log row.",
    )
    hidden_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (Index("ix_hidden_login_failures_entry_id", "entry_id"),)


class Job(Base):
    """A locally recorded work session awaiting review and Autotask submission."""

    __tablename__ = "jobs"

    # id is a UUID string so audit references remain stable across databases.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string, comment="Stable job UUID.")

    # status controls allowed workflow transitions and review visibility.
    status: Mapped[JobStatus] = enum_column(JobStatus, 32, "Current local job workflow status.")

    # web_user_id identifies the managed web user who owns this job. It is
    # nullable so existing rows can migrate before the first web user is created.
    web_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("web_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Managed web-user UUID that owns this job.",
    )

    # ticket_number is the human Autotask ticket number entered during review.
    ticket_number: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="Autotask ticket number.")

    # ticket_title stores the selected Autotask ticket title shown in review.
    ticket_title: Mapped[str | None] = mapped_column(
        String(240),
        nullable=True,
        comment="Selected Autotask ticket title shown as the review detail heading.",
    )

    # ticket_description stores bounded read-only context from the selected
    # Autotask ticket. It is displayed to help review the correct ticket but is
    # not submitted as time-entry notes.
    ticket_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Selected Autotask ticket description shown as read-only job context.",
    )

    # job_slot identifies the job position while one or two jobs are active concurrently.
    # Existing jobs are labeled as slot 1 and slot 2 for the overlapping workflow.
    job_slot: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Mobile concurrent job slot (1 for job 1, 2 for job 2).",
    )

    # client_name stores the verified Autotask company display name selected
    # from company lookup, not arbitrary typed reference text.
    client_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        comment="Verified Autotask company display name selected from lookup.",
    )

    # autotask_company_id stores the matching Autotask company/account ID for
    # the selected company name.
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

    # ai_cleanup_original_summary stores the exact editable notes value that
    # existed before the latest successful AI cleanup so the user can revert it
    # after navigation without relying on browser-only state.
    ai_cleanup_original_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Pre-cleanup summary text retained for the explicit Revert cleanup action.",
    )

    # ai_cleanup_pending_summary stores cleaned text only for submitted review
    # entries, where the textarea can reload with pending text but Autotask is
    # not patched until the user clicks Submit changes.
    ai_cleanup_pending_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Pending cleaned summary for submitted entries awaiting explicit Submit changes.",
    )

    ai_cleanup_source: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="UI surface that created the current AI cleanup revert state.",
    )
    ai_cleanup_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the current AI cleanup revert state was created.",
    )

    # work_location stores whether the final Autotask notes should be prefixed
    # with Remote or On-Site. The prefix is intentionally not written into
    # summary_notes so review text stays clean and editable.
    work_location: Mapped[WorkLocation] = mapped_column(
        Enum(
            WorkLocation,
            native_enum=False,
            length=20,
            values_callable=lambda enum_values: [enum_value.value for enum_value in enum_values],
        ),
        nullable=False,
        default=WorkLocation.REMOTE,
        server_default=WorkLocation.REMOTE.value,
        comment="Work location prefix applied only to Autotask summaryNotes.",
    )

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

    # web_user links the job to its technician account.
    web_user: Mapped[WebUser | None] = relationship("WebUser", back_populates="jobs")

    __table_args__ = (
        Index("ix_jobs_status_created_at", "status", "created_at_utc"),
        Index("ix_jobs_ticket_number", "ticket_number"),
        Index("ix_jobs_web_user_status_created_at", "web_user_id", "status", "created_at_utc"),
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
