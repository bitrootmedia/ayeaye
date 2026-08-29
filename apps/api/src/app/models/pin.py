"""Personal pins: a bookmark, not a property of the task.

    tasks ──► task_pins ◄── users        UNIQUE (task_id, user_id)

The same shape as `task_notes` and `planner_entries` — one row per person per
task — and for the same reason: pinning is what *you* want surfaced on *your*
dashboard, not a fact about the task that changes what anyone else sees.
Nothing here is denormalised onto `tasks`, and there is no organisation_id
column; scoping happens by joining to `tasks.organisation_id`, same as the
other two.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskPin(Base):
    __tablename__ = "task_pins"
    __table_args__ = (
        # One per person per task — pinning twice is a no-op, not a second row.
        UniqueConstraint("task_id", "user_id", name="uq_task_pins_task_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # CASCADE: a pin with no owner is nobody's bookmark. Removing the person
    # removes their pins with them.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
