"""Add work-location mode for Autotask time notes."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_work_location"
down_revision = "0004_ticket_title"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a non-null work location with Remote as the existing-job default."""

    op.add_column(
        "jobs",
        sa.Column(
            "work_location",
            sa.Enum("remote", "on_site", native_enum=False, length=20),
            nullable=False,
            server_default="remote",
            comment="Work location prefix applied only to Autotask summaryNotes.",
        ),
    )


def downgrade() -> None:
    """Remove the work-location mode from jobs."""

    op.drop_column("jobs", "work_location")
