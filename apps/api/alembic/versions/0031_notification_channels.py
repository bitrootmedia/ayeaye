"""notification channels — email, Telegram, webhook, one table

Revision ID: 0031_notification_channels
Revises: 0030_task_dependencies
Create Date: Phase 25

See `models/notification_channel.py` and `services/notification_channels.py`.
Email becomes a row here too, auto-provisioned lazily — existing behaviour is
unchanged for anyone who never opens the new settings screen, because
`notify()` still ends up queueing the email job for them, just by routing
through this table instead of doing it unconditionally.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_notification_channels"
down_revision = "0030_task_dependencies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_channels",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuidv7()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column(
            "config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "enabled_kinds",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('email', 'telegram', 'webhook')", name="ck_notification_channels_kind"
        ),
    )
    op.create_index(
        "ix_notification_channels_user_id", "notification_channels", ["user_id"]
    )
    op.create_index(
        "uq_notification_channels_user_email",
        "notification_channels",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'email'"),
    )
    op.create_index(
        "uq_notification_channels_user_telegram",
        "notification_channels",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'telegram'"),
    )


def downgrade() -> None:
    op.drop_index("uq_notification_channels_user_telegram", table_name="notification_channels")
    op.drop_index("uq_notification_channels_user_email", table_name="notification_channels")
    op.drop_index("ix_notification_channels_user_id", table_name="notification_channels")
    op.drop_table("notification_channels")
