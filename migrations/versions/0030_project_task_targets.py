"""Add Autotask project-task work targets.

Revision ID: 0030_project_task_targets
Revises: 0029_ticketpilot_2_0_1_prefs
Create Date: 2026-07-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_project_task_targets"
down_revision = "0029_ticketpilot_2_0_1_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add separate, server-verifiable project and task identity fields."""

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "work_target_type",
                sa.Enum(
                    "ticket",
                    "project_task",
                    name="worktargettype",
                    native_enum=False,
                    length=24,
                ),
                server_default="ticket",
                nullable=False,
                comment="Autotask entity that owns this job: ticket or project task.",
            )
        )
        batch_op.add_column(sa.Column("project_task_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("project_task_number", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("project_task_title", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("project_task_description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("project_number", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("project_name", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("task_status_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("task_status_label", sa.String(length=120), nullable=True))
        batch_op.create_index("ix_jobs_project_task_id", ["project_task_id"], unique=False)


def downgrade() -> None:
    """Remove project-task identity while preserving legacy ticket columns."""

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_index("ix_jobs_project_task_id")
        batch_op.drop_column("task_status_label")
        batch_op.drop_column("task_status_id")
        batch_op.drop_column("project_name")
        batch_op.drop_column("project_number")
        batch_op.drop_column("project_id")
        batch_op.drop_column("project_task_description")
        batch_op.drop_column("project_task_title")
        batch_op.drop_column("project_task_number")
        batch_op.drop_column("project_task_id")
        batch_op.drop_column("work_target_type")
