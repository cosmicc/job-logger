"""Add per-user preferences."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_user_preferences"
down_revision = "0007_web_users_and_job_owners"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create per-login configuration storage with a dark-theme default."""

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable preference UUID."),
        sa.Column(
            "principal_key",
            sa.String(length=180),
            nullable=False,
            comment="Stable authenticated-user key, such as web_user:<uuid> or super_admin:<username>.",
        ),
        sa.Column(
            "theme",
            sa.Enum("dark", "light", native_enum=False, length=16),
            nullable=False,
            comment="Preferred visual theme.",
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("principal_key"),
    )


def downgrade() -> None:
    """Remove per-login configuration storage."""

    op.drop_table("user_preferences")
