"""A personal day planner: five fixed buckets, and everything else in a pool.

    tasks ──► planner_entries ◄── users        UNIQUE (task_id, user_id)

Deliberately not on Task at all — this is who's-planning-what, layered on
top of visibility, not a property of the work. See services/planner.py for
the two rules that matter (one entry per task per user; who besides yourself
may see and move it).

Bucket order is urgency-decreasing, the same convention as STATUS_RANK and
PRIORITY_RANK in models/task.py: a fixed set ordered by what it means, not by
spelling.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

BUCKET_TODAY = "today"
BUCKET_TOMORROW = "tomorrow"
BUCKET_THIS_WEEK = "this_week"
BUCKET_NEXT_WEEK = "next_week"
BUCKET_SOMEDAY = "someday"
BUCKETS = (BUCKET_TODAY, BUCKET_TOMORROW, BUCKET_THIS_WEEK, BUCKET_NEXT_WEEK, BUCKET_SOMEDAY)


class PlannerEntry(Base):
    __tablename__ = "planner_entries"
    __table_args__ = (
        CheckConstraint(f"bucket IN {BUCKETS!r}", name="ck_planner_entries_bucket"),
        # The upsert in services/planner.py names this. A task is unplanned
        # (no row) or in exactly one bucket — never both, never two.
        UniqueConstraint("task_id", "user_id", name="uq_planner_entries_task_user"),
        Index("ix_planner_entries_user_bucket", "user_id", "bucket", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # CASCADE, same reasoning as task_notes.user_id: an entry with no owner is
    # one nobody planned and nobody can move.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    # Plain integer, client-resent absolute value on every drop — same
    # convention as Task.position. No server-side resequencing.
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
    # `onupdate` doesn't fire on a Core upsert, so services/planner.py sets
    # this explicitly on every move — see notes.py's save() for the same note.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
