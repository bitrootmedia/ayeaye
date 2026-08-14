"""One system-generated inbox per person.

Every raise goes through `services/notifications.notify()`, which writes the
row and queues an email nudge. The nudge carries **no detail** — just that
something happened and where to look — so nothing sensitive lives in an inbox
we don't control, and so a notification can't leak a task to someone whose
access was revoked between the raise and the send.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# A closed set, enforced by a CHECK constraint. Adding one means a migration —
# deliberately, because an inbox that can contain anything is one nobody can
# render properly. A unit test pins this tuple against the constraint so the
# two can't drift.
KIND_ACTION_REQUIRED = "task_action_required"
KIND_TASK_OWNER = "task_owner_changed"
KIND_TASK_CLOSED = "task_closed"
KIND_TASK_SHARED = "task_shared"
KIND_PROJECT_SHARED = "project_shared"
# Reminders fire twice: the day before, and on the day. Two kinds rather than
# one with a flag, because the inbox renders them differently and a person
# scanning it should be able to tell "coming" from "here" without reading.
KIND_REMINDER_SOON = "reminder_soon"
KIND_REMINDER_DUE = "reminder_due"
NOTIFICATION_KINDS = (
    KIND_ACTION_REQUIRED,
    KIND_TASK_OWNER,
    KIND_TASK_CLOSED,
    KIND_TASK_SHARED,
    KIND_PROJECT_SHARED,
    KIND_REMINDER_SOON,
    KIND_REMINDER_DUE,
)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(f"kind IN {NOTIFICATION_KINDS!r}", name="ck_notifications_kind"),
        # The inbox query, and the unread badge: one person, newest first.
        Index("ix_notifications_user", "user_id", "created_at"),
        Index(
            "ix_notifications_unread",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where to go. Relative, so it works whatever hostname this is deployed on.
    link_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set once the nudge has actually gone. It is the guard that stops a taskiq
    # retry sending the same message twice.
    emailed: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
