"""Replace Slate Dark preferences with Midnight Black.

Revision ID: 0026_replace_slate
Revises: 0025_full_web_nav
Create Date: 2026-07-22 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_replace_slate"
down_revision = "0025_full_web_nav"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Move every saved Slate Dark selection to Midnight Black."""

    op.execute(
        sa.text(
            "UPDATE user_preferences "
            "SET theme = 'dark-midnight' "
            "WHERE theme = 'dark-slate'"
        )
    )


def downgrade() -> None:
    """Map new dark themes to values understood by the earlier application."""

    op.execute(
        sa.text(
            "UPDATE user_preferences "
            "SET theme = CASE "
            "WHEN theme = 'dark-midnight' THEN 'dark-slate' "
            "WHEN theme = 'dark-graphite' THEN 'dark' "
            "ELSE theme END "
            "WHERE theme IN ('dark-midnight', 'dark-graphite')"
        )
    )
