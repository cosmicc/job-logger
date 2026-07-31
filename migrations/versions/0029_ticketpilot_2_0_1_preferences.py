"""Add TicketPilot 2.0.1 navigation and Review preferences.

Revision ID: 0029_ticketpilot_2_0_1_prefs
Revises: 0028_hide_home_office_nav
Create Date: 2026-07-30 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_ticketpilot_2_0_1_prefs"
down_revision = "0028_hide_home_office_nav"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add safe defaults for automatic navigation and Review list preferences."""

    op.add_column(
        "user_preferences",
        sa.Column(
            "automatically_open_onsite_navigation",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
            comment="Whether starting On-Site service-call work automatically opens navigation.",
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "review_hide_submitted_entries",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment="Whether Review hides successfully submitted entries.",
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "review_page_size",
            sa.Integer(),
            nullable=True,
            comment="Explicit Review page size; null uses the browser device default.",
        ),
    )


def downgrade() -> None:
    """Remove TicketPilot 2.0.1 navigation and Review preferences."""

    op.drop_column("user_preferences", "review_page_size")
    op.drop_column("user_preferences", "review_hide_submitted_entries")
    op.drop_column("user_preferences", "automatically_open_onsite_navigation")
