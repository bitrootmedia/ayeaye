"""Working hours: a weekly pattern of when someone plans to be around.

    users ──► working_hours          UNIQUE (user_id, weekday, hour)

Informational only, for now — nothing reads this to decide anything, the
same starting point personal notes and pins had before anything was built on
top of them. The plan this exists for is a later feature that skips sending
someone a notification outside their own hours; until that lands, this is
purely what a colleague sees.

**A cell's existence IS the check**, the identical idiom `task_sheet_cells`
and `task_tags` already use: marking an hour worked inserts a row, clearing
it deletes one — see `services/working_hours.py`. `weekday` is 0=Monday
through 6=Sunday, matching Python's own `date.weekday()`, so nothing here
needs a second day-numbering convention.
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkingHour(Base):
    __tablename__ = "working_hours"
    __table_args__ = (
        # Marking an already-marked hour is a no-op, not a second row — the
        # same reasoning `uq_task_pins_task_user` gives for its own upsert.
        UniqueConstraint("user_id", "weekday", "hour", name="uq_working_hours_user_weekday_hour"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_working_hours_weekday"),
        CheckConstraint("hour BETWEEN 0 AND 23", name="ck_working_hours_hour"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    # CASCADE, the same as every other personal-record user_id in this
    # schema (task_pins, reminders, …).
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hour: Mapped[int] = mapped_column(SmallInteger, nullable=False)
