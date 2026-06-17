"""Add selected Autotask ticket titles to jobs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_ticket_title"
down_revision = "0003_autotask_company_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable ticket titles captured from Autotask ticket selection."""

    op.add_column(
        "jobs",
        sa.Column(
            "ticket_title",
            sa.String(length=240),
            nullable=True,
            comment="Selected Autotask ticket title shown as the review detail heading.",
        ),
    )


def downgrade() -> None:
    """Remove selected Autotask ticket titles."""

    op.drop_column("jobs", "ticket_title")
