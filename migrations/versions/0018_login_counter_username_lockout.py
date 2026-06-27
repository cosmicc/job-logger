"""Scope failed-login counters to enforcement IP and username.

Revision ID: 0018_login_counter_lockout
Revises: 0017_web_user_debug_admin
Create Date: 2026-06-27 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_login_counter_lockout"
down_revision = "0017_web_user_debug_admin"
branch_labels = None
depends_on = None

SQLITE_NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def upgrade() -> None:
    """Track counters by trusted client IP plus submitted username."""

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "login_failure_counters",
            recreate="always",
            naming_convention=SQLITE_NAMING_CONVENTION,
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "username",
                    sa.String(length=255),
                    server_default="",
                    nullable=False,
                    comment="Case-insensitive submitted username whose consecutive failures are counted.",
                )
            )
            batch_op.drop_constraint("uq_login_failure_counters_client_ip", type_="unique")
            batch_op.create_unique_constraint(
                "uq_login_failure_counters_client_ip_username",
                ["client_ip", "username"],
            )
        return

    with op.batch_alter_table("login_failure_counters") as batch_op:
        batch_op.add_column(
            sa.Column(
                "username",
                sa.String(length=255),
                server_default="",
                nullable=False,
                comment="Case-insensitive submitted username whose consecutive failures are counted.",
            )
        )
        batch_op.drop_constraint("login_failure_counters_client_ip_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_login_failure_counters_client_ip_username",
            ["client_ip", "username"],
        )


def downgrade() -> None:
    """Return counters to the earlier IP-only shape."""

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "login_failure_counters",
            recreate="always",
            naming_convention=SQLITE_NAMING_CONVENTION,
        ) as batch_op:
            batch_op.drop_constraint("uq_login_failure_counters_client_ip_username", type_="unique")
            batch_op.drop_column("username")
            batch_op.create_unique_constraint("uq_login_failure_counters_client_ip", ["client_ip"])
        return

    with op.batch_alter_table("login_failure_counters") as batch_op:
        batch_op.drop_constraint("uq_login_failure_counters_client_ip_username", type_="unique")
        batch_op.drop_column("username")
        batch_op.create_unique_constraint("login_failure_counters_client_ip_key", ["client_ip"])
