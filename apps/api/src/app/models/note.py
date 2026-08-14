"""Private notes: one scratchpad per person per task.

    tasks ──► task_notes ◄── users        UNIQUE (task_id, user_id)

**Nobody else ever reads these, organisation admins included.** That is the
second deliberate exception to "an admin can do anything" (the first is a
hidden task), and it is the whole feature — a private note that a colleague
might read is not a private note, it is a badly-labelled comment.

There is deliberately **one note per person per task**, edited in place,
rather than a list of entries. A list would grow a timestamp, an author, a
delete button and an unread count, and would arrive at being a second comment
thread that only one person can see. If somebody wants dated entries they can
type dates.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskNote(Base):
    __tablename__ = "task_notes"
    __table_args__ = (
        # One per person per task. The upsert in `services/notes.py` relies on
        # this: without it a double-submit makes two notes and the second read
        # picks one at random.
        UniqueConstraint("task_id", "user_id", name="uq_task_notes_task_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # CASCADE, not SET NULL: a note with no owner is a note nobody may read and
    # nobody can delete. Removing the person removes their notes with them.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_func.now(),
        onupdate=sa_func.now(),
    )
