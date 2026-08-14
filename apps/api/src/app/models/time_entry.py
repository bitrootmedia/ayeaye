"""Time logged against a task.

A running timer is a row with `ended_at IS NULL`. That's the whole design, and
it's what makes the one-timer rule a database constraint rather than a
convention someone can forget:

    CREATE UNIQUE INDEX ... ON time_entries (user_id) WHERE ended_at IS NULL

**Global per person, not per organisation.** You are only ever doing one thing
at a time, and a constraint scoped per-org would let someone run three timers
by having three organisations — which is exactly the person the constraint
exists to protect.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimeEntry(Base):
    __tablename__ = "time_entries"
    __table_args__ = (
        # A finished entry must end after it started. Zero-length entries are
        # rejected too: they're always a mistake, and they make averages lie.
        CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at", name="ck_time_entries_range"
        ),
        # THE one-running-timer rule. Partial, so finished entries — of which
        # there are many per person — don't collide.
        Index(
            "uq_time_entries_one_running",
            "user_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        # The rollup query: everything on a task, or everything by a person.
        Index("ix_time_entries_task", "task_id", "started_at"),
        Index("ix_time_entries_user", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # CASCADE: someone's timesheet leaves with them. It is their record of
    # their own work, and the task history keeps the fact that time was logged.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NULL means running. Not a separate boolean: two fields that can disagree
    # about whether a timer is going is a bug with two places to fix it.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Set when someone corrects an entry after the fact — which PLAN.md §9
    # settles as allowed, because people forget to stop timers and the
    # alternative is a timesheet everyone knows is wrong.
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
