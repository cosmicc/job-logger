"""Add managed-user WebAuthn passkey credentials."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_webauthn_credentials"
down_revision = "0010_submit_from_work_in_progress_preference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the passkey credential table for managed web users."""

    op.create_table(
        "webauthn_credentials",
        sa.Column("id", sa.String(length=36), nullable=False, comment="Stable passkey row UUID."),
        sa.Column("web_user_id", sa.String(length=36), nullable=False, comment="Managed web-user UUID that owns this passkey."),
        sa.Column("credential_id", sa.String(length=1024), nullable=False, comment="Base64url-encoded WebAuthn credential ID."),
        sa.Column("credential_public_key", sa.Text(), nullable=False, comment="Base64url-encoded public key."),
        sa.Column("sign_count", sa.Integer(), server_default="0", nullable=False, comment="Latest authenticator signature counter."),
        sa.Column("aaguid", sa.String(length=64), nullable=True, comment="Authenticator AAGUID returned at registration."),
        sa.Column("credential_type", sa.String(length=40), server_default="public-key", nullable=False),
        sa.Column("device_type", sa.String(length=40), nullable=True, comment="WebAuthn credential device type."),
        sa.Column("backed_up", sa.Boolean(), server_default=sa.false(), nullable=False, comment="Whether the passkey is backed up by the provider."),
        sa.Column("transports", sa.JSON(), nullable=True, comment="Browser-reported authenticator transports."),
        sa.Column("user_agent", sa.String(length=255), nullable=True, comment="Browser user agent that registered the passkey."),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["web_user_id"], ["web_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_id"),
    )
    op.create_index(
        "ix_webauthn_credentials_web_user_created_at",
        "webauthn_credentials",
        ["web_user_id", "created_at_utc"],
    )
    op.create_index("ix_webauthn_credentials_credential_id", "webauthn_credentials", ["credential_id"])


def downgrade() -> None:
    """Remove managed-user passkey credentials."""

    op.drop_index("ix_webauthn_credentials_credential_id", table_name="webauthn_credentials")
    op.drop_index("ix_webauthn_credentials_web_user_created_at", table_name="webauthn_credentials")
    op.drop_table("webauthn_credentials")
