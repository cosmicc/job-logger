"""Add selected Autotask company IDs to jobs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_autotask_company_id"
down_revision = "0002_client_name_and_job_slot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable Autotask company IDs used for exact ticket lookup."""

    op.add_column(
        "jobs",
        sa.Column(
            "autotask_company_id",
            sa.Integer(),
            nullable=True,
            comment="Selected Autotask company ID for ticket lookup.",
        ),
    )


def downgrade() -> None:
    """Remove selected Autotask company IDs from jobs."""

    op.drop_column("jobs", "autotask_company_id")
