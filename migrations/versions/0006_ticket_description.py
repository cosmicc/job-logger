"""Add selected Autotask ticket descriptions to jobs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_ticket_description"
down_revision = "0005_work_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable ticket descriptions captured from Autotask ticket selection."""

    op.add_column(
        "jobs",
        sa.Column(
            "ticket_description",
            sa.Text(),
            nullable=True,
            comment="Selected Autotask ticket description shown as read-only job context.",
        ),
    )


def downgrade() -> None:
    """Remove selected Autotask ticket descriptions."""

    op.drop_column("jobs", "ticket_description")
