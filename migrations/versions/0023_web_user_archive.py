"""Add hidden archive state for managed web users.

Revision ID: 0023_web_user_archive
Revises: 0022_password_reset
Create Date: 2026-07-10 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_web_user_archive"
down_revision = "0022_password_reset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable hidden-delete timestamp to managed web users."""

    op.add_column(
        "web_users",
        sa.Column(
            "archived_at_utc",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when this user was hidden while preserving linked job history.",
        ),
    )
    op.create_index("ix_web_users_archived_at", "web_users", ["archived_at_utc"], unique=False)


def downgrade() -> None:
    """Remove the managed web-user archive marker."""

    op.drop_index("ix_web_users_archived_at", table_name="web_users")
    op.drop_column("web_users", "archived_at_utc")
