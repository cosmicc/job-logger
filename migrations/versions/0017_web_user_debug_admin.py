"""Add managed web-user Diagnostics admin flag.

Revision ID: 0017_web_user_debug_admin
Revises: 0016_ai_cleanup_revert_state
Create Date: 2026-06-26 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_web_user_debug_admin"
down_revision = "0016_ai_cleanup_revert_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Grant selected managed users full Diagnostics access when enabled."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_admin",
                sa.Boolean(),
                server_default="false",
                nullable=False,
                comment="Whether this managed user may access /debug and /debug/* diagnostics.",
            )
        )


def downgrade() -> None:
    """Remove managed-user Diagnostics admin grants."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.drop_column("is_admin")
