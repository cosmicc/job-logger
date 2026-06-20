"""Add managed web users and job ownership."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_web_users_and_job_owners"
down_revision = "0006_ticket_description"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create web users and add nullable job ownership for existing installs."""

    op.create_table(
        "web_users",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable web-user UUID."),
        sa.Column("full_name", sa.String(length=160), nullable=False, comment="Required human-readable user name."),
        sa.Column("username", sa.String(length=120), nullable=False, comment="Required local login username."),
        sa.Column(
            "username_normalized",
            sa.String(length=120),
            nullable=False,
            comment="Case-folded username used for unique login lookup.",
        ),
        sa.Column("password_hash", sa.String(length=255), nullable=False, comment="Salted password verifier."),
        sa.Column(
            "autotask_resource_id",
            sa.Integer(),
            nullable=False,
            comment="Autotask resource ID used for this user's service calls and time entries.",
        ),
        sa.Column(
            "disabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment="Whether this user is blocked from logging in.",
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username_normalized"),
    )
    op.create_index("ix_web_users_disabled", "web_users", ["disabled"])

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "web_user_id",
                sa.String(length=36),
                nullable=True,
                comment="Managed web-user UUID that owns this job.",
            )
        )
        batch_op.create_foreign_key(
            "fk_jobs_web_user_id_web_users",
            "web_users",
            ["web_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_jobs_web_user_status_created_at", ["web_user_id", "status", "created_at_utc"])


def downgrade() -> None:
    """Remove managed web-user ownership."""

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_index("ix_jobs_web_user_status_created_at")
        batch_op.drop_constraint("fk_jobs_web_user_id_web_users", type_="foreignkey")
        batch_op.drop_column("web_user_id")
    op.drop_index("ix_web_users_disabled", table_name="web_users")
    op.drop_table("web_users")
