"""Reminders: "poke me about this task on Friday".

    tasks ──► reminders ◄── users

**Personal.** A reminder belongs to whoever set it; nobody else sees it and
nobody else is notified. It is a note to self attached to a piece of work, not
a way to put something in a colleague's queue — that is what action-required
is for, and it already exists.

## Two notifications, and why the columns exist

A reminder fires twice: once the day before ("this is coming") and once on the
day ("this is here"). The two `notified_*_at` stamps are what make the sweep
**idempotent**, and that is not optional — a scheduler restart, a container
that comes up twice, or a clock that steps backwards will all re-run the same
window. Without the stamps, each of those is a duplicate email; with them the
second pass claims nothing and does nothing.

`done_at` is what stops the badge being permanently red. A reminder you can
see but not dismiss is an alarm with no off switch.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MAX_NOTE_LENGTH = 300


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        # The sweep: everything unfired up to today, across everybody. Partial,
        # because a reminder that has fired twice and been dismissed is dead
        # weight in the index that matters.
        Index(
            "ix_reminders_pending",
            "remind_on",
            postgresql_where=text("done_at IS NULL"),
        ),
        # The badge and the list: one person's, soonest first.
        Index("ix_reminders_user", "user_id", "remind_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # CASCADE: a reminder with no owner is one nobody can act on or dismiss.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # A **date**, not a timestamp. "Remind me on Friday" is what people mean;
    # asking for a time as well is a field nobody fills in properly. Which
    # moment Friday starts depends on the person, which is what `users.timezone`
    # is for — see services/reminders.py.
    remind_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(MAX_NOTE_LENGTH), nullable=True)

    # The idempotency stamps. Set by the sweep as it claims a row.
    notified_ahead_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notified_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
