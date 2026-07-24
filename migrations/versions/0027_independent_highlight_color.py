"""Store highlight colors independently from background profiles.

Revision ID: 0027_independent_highlight
Revises: 0026_replace_slate
Create Date: 2026-07-23 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_independent_highlight"
down_revision = "0026_replace_slate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a highlight preference while preserving every current appearance."""

    op.add_column(
        "user_preferences",
        sa.Column(
            "highlight_color",
            sa.String(length=16),
            server_default="teal",
            nullable=False,
            comment="Preferred highlight color family for navigation and ordinary actions.",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE user_preferences "
            "SET highlight_color = CASE theme "
            "WHEN 'light-sage' THEN 'sage' "
            "WHEN 'light-sky' THEN 'sky' "
            "WHEN 'dark-midnight' THEN 'blue' "
            "WHEN 'dark-graphite' THEN 'amber' "
            "WHEN 'dark-forest' THEN 'mint' "
            "WHEN 'dark-plum' THEN 'lavender' "
            "ELSE 'teal' END"
        )
    )


def downgrade() -> None:
    """Remove the independent highlight preference."""

    op.drop_column("user_preferences", "highlight_color")
