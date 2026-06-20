"""Add optional Autotask resource email to managed web users."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_web_user_email"
down_revision = "0008_user_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Store the selected Autotask Resource email when resource lookup returns one."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "email",
                sa.String(length=254),
                nullable=True,
                comment="Optional email address captured from the linked Autotask resource.",
            )
        )


def downgrade() -> None:
    """Remove stored Autotask Resource emails from managed web users."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.drop_column("email")
