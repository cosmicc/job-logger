"""Add self-service password reset tables.

Revision ID: 0022_password_reset
Revises: 0021_temp_password_flag
Create Date: 2026-07-08 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_password_reset"
down_revision = "0021_temp_password_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create tables for reset-token hashes and reset request throttles."""

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable password-reset row UUID."),
        sa.Column(
            "web_user_id",
            sa.String(length=36),
            nullable=False,
            comment="Managed web-user UUID that requested the reset.",
        ),
        sa.Column(
            "token_hash",
            sa.String(length=128),
            nullable=False,
            comment="HMAC-SHA256 hash of the reset token keyed by APP_SECRET_KEY.",
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip", sa.String(length=64), nullable=True, comment="Trusted request IP that started the reset."),
        sa.Column("request_user_agent", sa.String(length=255), nullable=True, comment="Bounded browser user agent."),
        sa.Column("sent_to_email", sa.String(length=254), nullable=False, comment="Destination email address used for delivery."),
        sa.Column("delivery_error", sa.Text(), nullable=True, comment="Safe bounded mail delivery error, if delivery failed."),
        sa.ForeignKeyConstraint(["web_user_id"], ["web_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_password_reset_tokens_created_at", "password_reset_tokens", ["created_at_utc"], unique=False)
    op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at_utc"], unique=False)
    op.create_index(
        "ix_password_reset_tokens_web_user_used_at",
        "password_reset_tokens",
        ["web_user_id", "used_at_utc"],
        unique=False,
    )
    op.create_index("ix_password_reset_tokens_web_user_id", "password_reset_tokens", ["web_user_id"], unique=False)

    op.create_table(
        "password_reset_request_counters",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable reset throttle counter UUID."),
        sa.Column("scope", sa.String(length=20), nullable=False, comment="Throttle scope: ip, email, or account."),
        sa.Column("scope_key", sa.String(length=128), nullable=False, comment="Safe throttle key for the scope."),
        sa.Column("window_started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "scope_key", name="uq_password_reset_request_counters_scope_key"),
    )
    op.create_index(
        "ix_password_reset_request_counters_scope_key",
        "password_reset_request_counters",
        ["scope", "scope_key"],
        unique=False,
    )


def downgrade() -> None:
    """Remove self-service password-reset persistence."""

    op.drop_index("ix_password_reset_request_counters_scope_key", table_name="password_reset_request_counters")
    op.drop_table("password_reset_request_counters")
    op.drop_index("ix_password_reset_tokens_web_user_id", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_web_user_used_at", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_expires_at", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_created_at", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
