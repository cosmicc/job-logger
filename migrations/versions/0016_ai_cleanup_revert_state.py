"""Add AI cleanup revert state to jobs.

Revision ID: 0016_ai_cleanup_revert_state
Revises: 0015_cloudflare_login_blocks
Create Date: 2026-06-25 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_ai_cleanup_revert_state"
down_revision = "0015_cloudflare_login_blocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Store per-job AI cleanup undo state for explicit user reverts."""

    op.add_column(
        "jobs",
        sa.Column(
            "ai_cleanup_original_summary",
            sa.Text(),
            nullable=True,
            comment="Pre-cleanup summary text retained for the explicit Revert cleanup action.",
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "ai_cleanup_pending_summary",
            sa.Text(),
            nullable=True,
            comment="Pending cleaned summary for submitted entries awaiting explicit Submit changes.",
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "ai_cleanup_source",
            sa.String(length=20),
            nullable=True,
            comment="UI surface that created the current AI cleanup revert state.",
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "ai_cleanup_at_utc",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the current AI cleanup revert state was created.",
        ),
    )


def downgrade() -> None:
    """Remove AI cleanup undo state from jobs."""

    op.drop_column("jobs", "ai_cleanup_at_utc")
    op.drop_column("jobs", "ai_cleanup_source")
    op.drop_column("jobs", "ai_cleanup_pending_summary")
    op.drop_column("jobs", "ai_cleanup_original_summary")
