"""Create initial job logger schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-16 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create jobs, audit events, and submission attempts."""

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable job UUID."),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "ready_for_review",
                "submitted",
                "submission_failed",
                "rejected",
                name="jobstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
            comment="Current local job workflow status.",
        ),
        sa.Column("ticket_number", sa.String(length=50), nullable=True, comment="Autotask ticket number."),
        sa.Column(
            "ticket_status",
            sa.Enum(
                "in_progress",
                "waiting_customer",
                "waiting_parts",
                "follow_up",
                "complete",
                name="ticketstatus",
                native_enum=False,
                length=32,
            ),
            nullable=True,
            comment="Requested ticket status after review.",
        ),
        sa.Column("summary_notes", sa.Text(), nullable=True, comment="Reviewer-approved time notes."),
        sa.Column("description_text", sa.Text(), nullable=True, comment="Editable transcribed description."),
        sa.Column("raw_start_utc", sa.DateTime(timezone=True), nullable=False, comment="Exact job start timestamp stored in UTC."),
        sa.Column("raw_end_utc", sa.DateTime(timezone=True), nullable=True, comment="Exact job end timestamp stored in UTC."),
        sa.Column("rounded_start_utc", sa.DateTime(timezone=True), nullable=False, comment="Rounded start timestamp stored in UTC."),
        sa.Column("rounded_end_utc", sa.DateTime(timezone=True), nullable=True, comment="Rounded end timestamp stored in UTC."),
        sa.Column("local_work_date", sa.Date(), nullable=True, comment="America/Detroit work date."),
        sa.Column("transcription_provider", sa.String(length=50), nullable=True, comment="Speech provider name."),
        sa.Column(
            "transcription_status",
            sa.Enum(
                "not_requested",
                "succeeded",
                "failed",
                name="transcriptionstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
            comment="Latest transcription attempt status.",
        ),
        sa.Column("transcription_error", sa.Text(), nullable=True, comment="Safe transcription error text."),
        sa.Column("autotask_provider", sa.String(length=50), nullable=True, comment="Autotask provider name."),
        sa.Column("autotask_external_id", sa.String(length=100), nullable=True, comment="Remote time entry ID."),
        sa.Column("autotask_submitted_at_utc", sa.DateTime(timezone=True), nullable=True, comment="UTC timestamp for successful Autotask submission."),
        sa.Column("autotask_error", sa.Text(), nullable=True, comment="Safe Autotask error text."),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False, comment="Stable local idempotency key for Autotask submission."),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at_utc"])
    op.create_index("ix_jobs_ticket_number", "jobs", ["ticket_number"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable audit UUID."),
        sa.Column("job_id", sa.String(length=36), nullable=True, comment="Optional job UUID associated with the event."),
        sa.Column("actor", sa.String(length=120), nullable=False, comment="Authenticated actor or system label."),
        sa.Column("action", sa.String(length=80), nullable=False, comment="Machine-readable audit action."),
        sa.Column("details", sa.JSON(), nullable=False, comment="Sanitized event details."),
        sa.Column("ip_address", sa.String(length=64), nullable=True, comment="Request client IP if available."),
        sa.Column("user_agent", sa.String(length=255), nullable=True, comment="Request user agent if available."),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_action_created_at", "audit_events", ["action", "created_at_utc"])
    op.create_index("ix_audit_events_job_created_at", "audit_events", ["job_id", "created_at_utc"])

    op.create_table(
        "submission_attempts",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable attempt UUID."),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False, comment="Submission provider name."),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False, comment="Submission idempotency key."),
        sa.Column("succeeded", sa.Boolean(), nullable=False, comment="Whether the attempt succeeded."),
        sa.Column("external_id", sa.String(length=100), nullable=True, comment="Remote time entry ID."),
        sa.Column("safe_error", sa.Text(), nullable=True, comment="Safe submission failure detail."),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_submission_attempts_job_created_at", "submission_attempts", ["job_id", "created_at_utc"])


def downgrade() -> None:
    """Drop the initial job logger schema."""

    op.drop_index("ix_submission_attempts_job_created_at", table_name="submission_attempts")
    op.drop_table("submission_attempts")
    op.drop_index("ix_audit_events_job_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_action_created_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_jobs_ticket_number", table_name="jobs")
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_table("jobs")

