"""A recurring task's template, and the cadence that regenerates it.

    tasks ◄── series_id ── task_series ──► owner (RESTRICT, like Task's own)

Deliberately its own table, not a handful of columns on `Task` — the same
reasoning as `task_pins` and `planner_entries` being their own tables rather
than flags on the task. A series outlives any one occurrence: the task it
first attached to can close, or even be deleted, and the series keeps
generating the next one regardless. See `services/recurrence.py`.

**On schedule, regardless of whether the last occurrence closed.** The
product decision, not an oversight: like a calendar event, "pay rent" for
September appears whether or not August's got closed. Two open occurrences
can coexist on the board — that's an honest backlog, not a bug — which is
also why there is no rule tying generation to the previous task's status.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

INTERVAL_DAY = "day"
INTERVAL_WEEK = "week"
INTERVAL_MONTH = "month"
INTERVAL_UNITS = (INTERVAL_DAY, INTERVAL_WEEK, INTERVAL_MONTH)


class TaskSeries(Base):
    __tablename__ = "task_series"
    __table_args__ = (
        CheckConstraint(f"interval_unit IN {INTERVAL_UNITS!r}", name="ck_task_series_unit"),
        CheckConstraint("interval_count > 0", name="ck_task_series_count_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The template. Copied onto every generated task at creation time — never
    # read back off the most recent occurrence, so editing one task's title
    # doesn't quietly change what the series produces next.
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'normal'")
    )

    # RESTRICT, same as `tasks.owner_user_id` and for the identical reason:
    # a series with nobody accountable for its date is a series nobody can
    # administer. `services/organisations.py`'s offboarding reassignment
    # covers this table too — see `recurrence.reassign_owned_series`.
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Whoever set it up. Not the same as `owner_user_id` — an admin could set
    # up a series on someone else's behalf — and it's who `can_manage` checks
    # against, since a series isn't "owned" in the access-model sense the way
    # a task is.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    interval_unit: Mapped[str] = mapped_column(String(8), nullable=False)
    interval_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    # The next occurrence's due date. The sweep's claim: advanced by one
    # conditional UPDATE per series before that occurrence is generated, so a
    # restart or two schedulers racing produces one task, not two. See
    # `recurrence.try_claim` for why this can't be a single shared-value
    # UPDATE the way the reminder/deadline sweeps' claims are — the advance
    # amount differs per row.
    next_due_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Stop, not delete — the same non-destructive default as un-pinning or
    # hiding. A stopped series keeps its history and can't accidentally take
    # already-generated tasks with it (there is nothing here that would).
    active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
