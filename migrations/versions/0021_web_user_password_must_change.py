"""Add managed web-user temporary-password change flag.

Revision ID: 0021_temp_password_flag
Revises: 0020_database_login_attempts
Create Date: 2026-07-04 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_temp_password_flag"
down_revision = "0020_database_login_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Track whether a managed user must replace a temporary password."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "password_must_change",
                sa.Boolean(),
                server_default="false",
                nullable=False,
                comment="Whether this user must change the temporary password before using the app.",
            )
        )


def downgrade() -> None:
    """Remove temporary-password tracking."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.drop_column("password_must_change")
