"""Where a notification actually goes, once it exists.

    users ──► notification_channels

Email, Telegram and a generic webhook are three rows in ONE table, not a
channel abstraction with email bolted on as a special case. `notify()`
doesn't know "email" — it knows "deliver to every channel with this kind
enabled." See `services/notification_channels.py`.

`config` is JSONB because its shape differs per `kind` and it is only ever
read back whole, never queried on: `{}` for email, `{"chat_id": ...}` for a
linked Telegram channel (or `{"link_code": ...}` while a link is pending and
`verified_at` is still NULL), `{"url": ..., "secret_hash": ...}` for a
webhook. The identical "differs per kind, never filtered on" reasoning
`TaskEvent.data` already documents.
"""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CHANNEL_EMAIL = "email"
CHANNEL_TELEGRAM = "telegram"
CHANNEL_WEBHOOK = "webhook"
CHANNEL_KINDS = (CHANNEL_EMAIL, CHANNEL_TELEGRAM, CHANNEL_WEBHOOK)


class NotificationChannel(Base):
    __tablename__ = "notification_channels"
    __table_args__ = (
        CheckConstraint(f"kind IN {CHANNEL_KINDS!r}", name="ck_notification_channels_kind"),
        # At most one of each — a person has one inbox and, practically, one
        # Telegram account. Webhook carries no such index: several are
        # expected (one relay per destination), so it isn't in this list.
        Index(
            "uq_notification_channels_user_email",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'email'"),
        ),
        Index(
            "uq_notification_channels_user_telegram",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'telegram'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # "Email", "Telegram", or whatever a person names a webhook — the same
    # "which of these do I revoke" reasoning `PersonalAccessToken.name`
    # already documents.
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Which NOTIFICATION_KINDS values this channel receives. Always set
    # explicitly in Python at creation (to the full current set) rather than
    # relied on from a static server default — that set can grow with a
    # migration, and a SQL-level default frozen at table-creation time would
    # go stale the day a new notification kind is added.
    enabled_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    # NULL for a pending Telegram link. Always set immediately for email and
    # webhook — there is nothing to verify for either.
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
