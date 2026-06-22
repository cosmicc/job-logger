"""Add per-user default Autotask service-desk role.

Revision ID: 0013_web_user_default_role
Revises: 0012_web_session_invalidation
Create Date: 2026-06-22 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_web_user_default_role"
down_revision = "0012_web_session_invalidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Store an optional explicit ResourceServiceDeskRoles fallback per user."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "autotask_default_service_desk_role_id",
                sa.Integer(),
                nullable=True,
                comment="Optional active ResourceServiceDeskRoles.roleID fallback used for this user's Autotask time entries.",
            )
        )


def downgrade() -> None:
    """Remove the optional per-user Autotask role fallback."""

    with op.batch_alter_table("web_users") as batch_op:
        batch_op.drop_column("autotask_default_service_desk_role_id")
