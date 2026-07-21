"""Add the full-web navigation opt-in preference.

Revision ID: 0025_full_web_nav
Revises: 0024_navigation_preferences
Create Date: 2026-07-20 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_full_web_nav"
down_revision = "0024_navigation_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Default existing and new users to mobile-only navigation."""

    op.add_column(
        "user_preferences",
        sa.Column(
            "allow_navigation_on_full_web",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment="Whether navigation controls and automatic launches are allowed on full web browsers.",
        ),
    )


def downgrade() -> None:
    """Remove the full-web navigation opt-in preference."""

    op.drop_column("user_preferences", "allow_navigation_on_full_web")
