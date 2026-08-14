"""Tags: a shared vocabulary for an organisation, and what carries it.

    organisations ──► tags ◄──┬── task_tags ──► tasks

**Organisation-scoped, not global.** A vocabulary is only useful if it's
shared, and a global namespace would leak one company's tag names to another.

**`off_board` is the whole reason this isn't just a label.** A tag marked that
way takes its tasks off the board and out of the list — which is what "this is
a knowledge base item, not a task" means in practice. The task keeps its
history, its comments and its files; it just stops queueing for attention. One
property on a tag rather than a second entity type, so nothing has to be
migrated the day something stops being reference material and becomes work.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MAX_TAG_LENGTH = 40


def normalise_tag(name: str) -> str:
    """Trim and collapse whitespace. Case is **preserved**, not folded.

    Uniqueness is case-insensitive (see the index below) but display is not:
    somebody typing "Knowledge base" should get "Knowledge base", and the
    second person typing "knowledge base" should get the existing tag rather
    than a duplicate that sorts next to it and means the same thing.
    """
    return " ".join((name or "").split())[:MAX_TAG_LENGTH]


class Tag(Base):
    """One label in an organisation's vocabulary."""

    __tablename__ = "tags"
    __table_args__ = (
        # Case-insensitive, which is the whole game: without it you get `kb`,
        # `KB` and `Kb` inside a week and no filter finds all three.
        Index(
            "uq_tags_org_name",
            "organisation_id",
            text("lower(name)"),
            unique=True,
        ),
        UniqueConstraint("id", "organisation_id", name="uq_tags_id_org"),
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
    name: Mapped[str] = mapped_column(String(MAX_TAG_LENGTH), nullable=False)
    # Tasks carrying this tag leave the board and the list. They stay
    # searchable, reachable by tag filter, and completely normal otherwise.
    off_board: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )


class TaskTag(Base):
    """A tag on a task.

    No access rules of its own: who can see the tagging is who can see the
    task, and applying one needs `write` on the task like any other edit.
    """

    __tablename__ = "task_tags"
    __table_args__ = (
        UniqueConstraint("task_id", "tag_id", name="uq_task_tags_task_tag"),
        # The filter query: every task carrying one tag.
        Index("ix_task_tags_tag", "tag_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
