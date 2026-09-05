"""What a save replaced — the recoverable half of editing a task.

    tasks ──► task_revisions        one row per save that changed content

**A row here holds the *outgoing* content, not the new content.** That is the
whole reason this table can exist without introducing a second answer to
"what does this task say now": `tasks.title` and `tasks.description` stay the
only source of the current version, and every row here is strictly a version
that has already been overwritten. Storing the *new* content instead — the
shape `article_revisions` uses, where the latest revision *is* the live body —
would mean the newest row and the task row both claiming to be current, and
this codebase has been bitten by two answers that can disagree often enough
to not invite it again.

So `created_at` and `replaced_by_user_id` describe the *overwrite*, not the
authorship of the content in the row: "this is what the task said until
Bob saved over it at 14:03". Which is exactly the question somebody asks when
a description they wrote has vanished.

Deliberately no `description_text` generated column, unlike
`article_revisions.body_text`: search matches the live content only — the same
"search the live content, not history" rule the knowledge base already
follows — so there is nothing here to index.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskRevision(Base):
    __tablename__ = "task_revisions"
    __table_args__ = (
        # The history query: one task, newest first. UUIDv7 sorts by time.
        Index("ix_task_revisions_task", "task_id", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    # The content as it was. Same column types as `Task.title`/
    # `Task.description`, so nothing can be stored here that couldn't be put
    # back — a restore is a plain update with these two values.
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SET NULL, not CASCADE: the same "deleting a person must not rewrite
    # history" rule `TaskEvent.actor_user_id` states. The recoverable version
    # outlives the account of whoever overwrote it.
    replaced_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
