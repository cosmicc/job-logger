"""Store login attempts in the database.

Revision ID: 0020_database_login_attempts
Revises: 0019_entry_type_notes
Create Date: 2026-07-02 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_database_login_attempts"
down_revision = "0019_entry_type_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create database-backed login-attempt diagnostics and remove file-hide state."""

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable login-attempt UUID."),
        sa.Column("succeeded", sa.Boolean(), server_default=sa.false(), nullable=False, comment="Whether local authentication succeeded."),
        sa.Column("event", sa.String(length=64), nullable=False, comment="Safe login-attempt event key."),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_ip", sa.String(length=64), server_default="unknown", nullable=False),
        sa.Column("enforcement_client_ip", sa.String(length=64), server_default="unknown", nullable=False),
        sa.Column("direct_client_ip", sa.String(length=64), server_default="", nullable=False),
        sa.Column("x_real_ip", sa.String(length=64), server_default="", nullable=False),
        sa.Column("x_forwarded_for", sa.String(length=512), server_default="", nullable=False),
        sa.Column("forwarded_proto", sa.String(length=64), server_default="", nullable=False),
        sa.Column("host", sa.String(length=512), server_default="", nullable=False),
        sa.Column("username", sa.String(length=255), server_default="", nullable=False),
        sa.Column("user_agent", sa.String(length=255), server_default="", nullable=False),
        sa.Column("method", sa.String(length=24), server_default="", nullable=False),
        sa.Column("path", sa.String(length=512), server_default="", nullable=False),
        sa.Column("user_kind", sa.String(length=64), server_default="", nullable=False),
        sa.Column("web_user_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("authentication_method", sa.String(length=64), server_default="", nullable=False),
        sa.Column("username_length", sa.Integer(), server_default="0", nullable=False),
        sa.Column("username_truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("password_supplied", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("password_length", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_url", sa.String(length=512), server_default="", nullable=False),
        sa.Column("reason", sa.String(length=64), server_default="", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lockout_applied", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("lockout_remaining_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("hidden_at_utc", sa.DateTime(timezone=True), nullable=True, comment="UTC time when this failed-login row was hidden from Diagnostics."),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at_utc"])
    op.create_index("ix_login_attempts_enforcement_client_ip", "login_attempts", ["enforcement_client_ip"])
    op.create_index("ix_login_attempts_hidden_at", "login_attempts", ["hidden_at_utc"])
    op.create_index("ix_login_attempts_succeeded_created_at", "login_attempts", ["succeeded", "created_at_utc"])
    op.drop_index("ix_hidden_login_failures_entry_id", table_name="hidden_login_failures")
    op.drop_table("hidden_login_failures")


def downgrade() -> None:
    """Restore the previous file-backed failed-login hide table."""

    op.create_table(
        "hidden_login_failures",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable hidden login-failure UUID."),
        sa.Column("entry_id", sa.String(length=64), nullable=False, comment="Stable hash of the raw failed-login JSONL line hidden from diagnostics."),
        sa.Column("client_ip", sa.String(length=64), server_default="", nullable=False, comment="Displayed client IP from the hidden failed-login row."),
        sa.Column(
            "occurred_at_utc",
            sa.String(length=40),
            server_default="",
            nullable=False,
            comment="Raw UTC timestamp string from the hidden failed-login log row.",
        ),
        sa.Column("hidden_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_id"),
    )
    op.create_index("ix_hidden_login_failures_entry_id", "hidden_login_failures", ["entry_id"])
    op.drop_index("ix_login_attempts_succeeded_created_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_hidden_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_enforcement_client_ip", table_name="login_attempts")
    op.drop_index("ix_login_attempts_created_at", table_name="login_attempts")
    op.drop_table("login_attempts")
