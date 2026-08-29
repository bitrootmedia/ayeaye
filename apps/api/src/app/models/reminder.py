"""Reminders: "poke me about this task on Friday" — or about nothing in
particular.

    tasks ──► reminders ◄── users
               ▲
               └── organisations (standalone only)

**Personal.** A reminder belongs to whoever set it; nobody else sees it and
nobody else is notified. It is a note to self attached to a piece of work, not
a way to put something in a colleague's queue — that is what action-required
is for, and it already exists.

**Two shapes**, enforced by `ck_reminders_one_anchor`
(`num_nonnulls(task_id, title) = 1`): anchored to a task, the way every
reminder used to be, or standalone with its own `title` — "pack for the
trip" has no task behind it and doesn't need one. `ck_reminders_org_iff_standalone`
(`(task_id IS NULL) = (organisation_id IS NOT NULL)`) is the second half: a
task-anchored reminder gets its organisation from the task, never stored
twice where the two copies could disagree; a standalone one has no task to
ask, so it carries `organisation_id` directly — the calendar is scoped to one
organisation at a time and needs somewhere to read that from.

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

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MAX_NOTE_LENGTH = 300
MAX_TITLE_LENGTH = 200


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint("num_nonnulls(task_id, title) = 1", name="ck_reminders_one_anchor"),
        CheckConstraint(
            "(task_id IS NULL) = (organisation_id IS NOT NULL)",
            name="ck_reminders_org_iff_standalone",
        ),
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
    # NULL for a standalone reminder — see `ck_reminders_one_anchor`.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Only set when `task_id` is NULL: a task-anchored reminder's organisation
    # is the task's own, and storing it a second time here is a second place
    # for the two to disagree. CASCADE, the same as every other organisation_id
    # in this codebase — deleting an organisation takes everything in it with
    # it, and a standalone reminder is no more exempt than a task or a project.
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=True
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
    # A standalone reminder's own "what" — a task-anchored one already has the
    # task's title for that, so this stays NULL there (see `ck_reminders_one_anchor`).
    title: Mapped[str | None] = mapped_column(String(MAX_TITLE_LENGTH), nullable=True)
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
