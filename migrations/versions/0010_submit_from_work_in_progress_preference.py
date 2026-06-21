"""Add direct Work in Progress submission preference."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_submit_from_work_in_progress_preference"
down_revision = "0009_web_user_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Default direct Work in Progress submission to off for all users."""

    with op.batch_alter_table("user_preferences") as batch_op:
        batch_op.add_column(
            sa.Column(
                "submit_from_work_in_progress",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
                comment="Whether ending work submits directly to Autotask instead of stopping in review.",
            )
        )


def downgrade() -> None:
    """Remove direct Work in Progress submission preferences."""

    with op.batch_alter_table("user_preferences") as batch_op:
        batch_op.drop_column("submit_from_work_in_progress")
