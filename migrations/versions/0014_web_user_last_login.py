"""Add managed web-user last login timestamp.

Revision ID: 0014_web_user_last_login
Revises: 0013_web_user_default_role
Create Date: 2026-06-23 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_web_user_last_login"
down_revision = "0013_web_user_default_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Store the latest successful managed-user login time."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "last_login_at_utc",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="UTC timestamp for the latest successful managed web-user login.",
            )
        )


def downgrade() -> None:
    """Remove managed-user last login metadata."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.drop_column("last_login_at_utc")
