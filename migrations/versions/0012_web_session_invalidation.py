"""Add managed web-user session invalidation cutoff.

Revision ID: 0012_web_session_invalidation
Revises: 0011_webauthn_credentials
Create Date: 2026-06-21 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_web_session_invalidation"
down_revision = "0011_webauthn_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a nullable UTC cutoff used to invalidate old web-user sessions."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sessions_invalidated_at_utc",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="UTC cutoff after which existing signed web-user sessions must be renewed.",
            )
        )


def downgrade() -> None:
    """Remove managed web-user session invalidation cutoff."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.drop_column("sessions_invalidated_at_utc")
