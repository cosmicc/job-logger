"""Add entry type and ticket-note submission fields.

Revision ID: 0019_entry_type_notes
Revises: 0018_login_counter_lockout
Create Date: 2026-06-29 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_entry_type_notes"
down_revision = "0018_login_counter_lockout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add persisted fields for time-entry versus ticket-note submission."""

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "entry_type",
                sa.Enum(
                    "time_entry",
                    "ticket_note",
                    name="entrytype",
                    native_enum=False,
                    length=32,
                ),
                server_default="time_entry",
                nullable=False,
                comment="Autotask record type created for this local job.",
            )
        )
        batch_op.add_column(
            sa.Column(
                "note_title",
                sa.String(length=250),
                nullable=True,
                comment="Customer-visible Autotask ticket-note title when this job submits as a note.",
            )
        )
        batch_op.add_column(
            sa.Column(
                "append_to_resolution",
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
                comment="Whether Autotask should append submitted text to the ticket resolution.",
            )
        )


def downgrade() -> None:
    """Remove ticket-note submission fields."""

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("append_to_resolution")
        batch_op.drop_column("note_title")
        batch_op.drop_column("entry_type")
