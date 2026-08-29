"""Checklists: a quick todo list under a task.

    tasks ──► task_checklists ──► task_checklist_items

More than one per task, on purpose — "packing list" and "before we ship" are
two different lists, not two sections of one. Ordered by `id`: UUIDv7 sorts
chronologically, so creation order falls out for free and there is no
`position` column to keep in sync, the same reasoning `list_members` already
uses for the roster.

Shared task content, not a personal record — closer to the description than
to a private note or a reminder. `write` access is what gates every mutation
here (`services/checklists.py`), the same bar tagging and attaching a file
already clear, and every mutation announces so a second viewer's screen
updates live.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

MAX_TITLE_LENGTH = 200
MAX_ITEM_TEXT_LENGTH = 500


class TaskChecklist(Base):
    __tablename__ = "task_checklists"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(MAX_TITLE_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )

    items: Mapped[list["TaskChecklistItem"]] = relationship(
        back_populates="checklist",
        cascade="all, delete-orphan",
        order_by="TaskChecklistItem.id",
    )


class TaskChecklistItem(Base):
    __tablename__ = "task_checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    checklist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_checklists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(MAX_ITEM_TEXT_LENGTH), nullable=False)
    # NULL means not done. Same shape as Reminder.done_at and TimeEntry's
    # ended_at — a timestamp answers "when", a boolean would have to be paired
    # with one anyway the first time somebody asks when an item was checked off.
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )

    checklist: Mapped[TaskChecklist] = relationship(back_populates="items")
