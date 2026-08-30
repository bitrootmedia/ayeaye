"""two-factor auth: organisations.require_mfa, TOTP devices, backup codes

Revision ID: 0027_mfa
Revises: 0026_personal_notes
Create Date: Phase 23

Three additions for one feature. `organisations.require_mfa` is the
org-level toggle. `mfa_totp_devices` and `mfa_backup_codes` are hand-rolled
— SuperTokens' own `totp`/`multifactorauth` recipes require a paid core
license even self-hosted — and both are keyed on `user_id`, not on any one
organisation, the same way a device or a set of codes covers every
organisation a person is in. See services/mfa.py.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027_mfa"
down_revision = "0026_personal_notes"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "organisations",
        sa.Column("require_mfa", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "mfa_totp_devices",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "mfa_backup_codes",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_mfa_backup_codes_user_id", "mfa_backup_codes", ["user_id"])
    op.create_index(
        "ix_mfa_backup_codes_code_hash", "mfa_backup_codes", ["code_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_table("mfa_backup_codes")
    op.drop_table("mfa_totp_devices")
    op.drop_column("organisations", "require_mfa")
