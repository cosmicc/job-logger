"""Add client references and concurrent job slot support."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_client_name_and_job_slot"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add client and slot fields for overlapping active jobs."""

    op.add_column("jobs", sa.Column("job_slot", sa.Integer(), nullable=True, comment="Mobile concurrent job slot (1 or 2)."))
    op.add_column("jobs", sa.Column("client_name", sa.String(length=120), nullable=True, comment="Client reference typed when work starts."))


def downgrade() -> None:
    """Remove client and slot columns."""

    op.drop_column("jobs", "client_name")
    op.drop_column("jobs", "job_slot")
