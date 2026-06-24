"""Add Cloudflare login block tracking tables.

Revision ID: 0015_cloudflare_login_blocks
Revises: 0014_web_user_last_login
Create Date: 2026-06-24 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_cloudflare_login_blocks"
down_revision = "0014_web_user_last_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create app-managed Cloudflare and failed-login diagnostics tables."""

    op.create_table(
        "login_failure_counters",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable counter UUID."),
        sa.Column("client_ip", sa.String(length=64), nullable=False, comment="Displayed login client IP whose consecutive failures are counted."),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False, comment="Consecutive failed local app logins from this client IP."),
        sa.Column(
            "last_failed_at_utc",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp for the most recent failed login from this client IP.",
        ),
        sa.Column(
            "last_success_at_utc",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp for the most recent successful login that reset this counter.",
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_ip"),
    )
    op.create_index("ix_login_failure_counters_client_ip", "login_failure_counters", ["client_ip"])

    op.create_table(
        "cloudflare_ip_blocks",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable Cloudflare block UUID."),
        sa.Column("ip_address", sa.String(length=64), nullable=False, comment="Normalized IP address in an app-managed Cloudflare block."),
        sa.Column("cloudflare_rule_id", sa.String(length=120), nullable=False, comment="Cloudflare zone IP Access Rule ID created by this app."),
        sa.Column(
            "source",
            sa.String(length=40),
            server_default="manual",
            nullable=False,
            comment="Whether the app-managed Cloudflare block was manual or automatic.",
        ),
        sa.Column("reason", sa.String(length=180), server_default="", nullable=False, comment="Safe reason for the app-managed Cloudflare block."),
        sa.Column("failure_count", sa.Integer(), nullable=True, comment="Consecutive failed-login count that created an automatic block."),
        sa.Column("notes", sa.Text(), server_default="", nullable=False, comment="Note submitted to Cloudflare for this app-managed block."),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cloudflare_rule_id"),
        sa.UniqueConstraint("ip_address"),
    )
    op.create_index("ix_cloudflare_ip_blocks_created_at", "cloudflare_ip_blocks", ["created_at_utc"])
    op.create_index("ix_cloudflare_ip_blocks_ip_address", "cloudflare_ip_blocks", ["ip_address"])

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


def downgrade() -> None:
    """Remove app-managed Cloudflare and hidden login diagnostics tables."""

    op.drop_index("ix_hidden_login_failures_entry_id", table_name="hidden_login_failures")
    op.drop_table("hidden_login_failures")
    op.drop_index("ix_cloudflare_ip_blocks_ip_address", table_name="cloudflare_ip_blocks")
    op.drop_index("ix_cloudflare_ip_blocks_created_at", table_name="cloudflare_ip_blocks")
    op.drop_table("cloudflare_ip_blocks")
    op.drop_index("ix_login_failure_counters_client_ip", table_name="login_failure_counters")
    op.drop_table("login_failure_counters")
