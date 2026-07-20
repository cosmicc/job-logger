"""Add per-user navigation application and destination preferences.

Revision ID: 0024_navigation_preferences
Revises: 0023_web_user_archive
Create Date: 2026-07-20 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_navigation_preferences"
down_revision = "0023_web_user_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add opt-in navigation settings to managed-user preferences."""

    op.add_column(
        "user_preferences",
        sa.Column(
            "navigation_app",
            sa.String(length=32),
            server_default="none",
            nullable=False,
            comment="Preferred navigation application.",
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "home_address",
            sa.String(length=300),
            nullable=True,
            comment="Private user home navigation destination.",
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "office_address",
            sa.String(length=300),
            nullable=True,
            comment="Optional private user override for the global office destination.",
        ),
    )


def downgrade() -> None:
    """Remove per-user navigation settings."""

    op.drop_column("user_preferences", "office_address")
    op.drop_column("user_preferences", "home_address")
    op.drop_column("user_preferences", "navigation_app")
