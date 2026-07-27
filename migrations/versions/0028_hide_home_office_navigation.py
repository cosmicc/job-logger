"""Add the Home and Office quick-navigation visibility preference.

Revision ID: 0028_hide_home_office_nav
Revises: 0027_independent_highlight
Create Date: 2026-07-26 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_hide_home_office_nav"
down_revision = "0027_independent_highlight"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep existing quick destinations visible unless each user opts out."""

    op.add_column(
        "user_preferences",
        sa.Column(
            "hide_home_office_navigation_buttons",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment="Whether Work hides only the Home and Office quick-navigation buttons.",
        ),
    )


def downgrade() -> None:
    """Remove the Home and Office quick-navigation visibility preference."""

    op.drop_column("user_preferences", "hide_home_office_navigation_buttons")
