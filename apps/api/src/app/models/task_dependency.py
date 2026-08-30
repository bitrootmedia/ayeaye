"""One task blocking another — informational, not enforced.

    tasks ──► task_dependencies ◄── tasks        UNIQUE (task_id, depends_on_task_id)

`task_id` is the dependent task, `depends_on_task_id` is the one it's waiting
on. Purely a fact people record to see at a glance whether something is
blocked — closing a task with open dependencies still works. See
`services/dependencies.py` for the cycle check that keeps the graph a DAG.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "depends_on_task_id", name="uq_task_dependencies_task_depends_on"
        ),
        # A task cannot block itself — the trivial cycle, refused at the
        # constraint rather than left to the recursive-CTE check to catch.
        CheckConstraint("task_id != depends_on_task_id", name="ck_task_dependencies_not_self"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL, not CASCADE: deleting the person who linked two tasks must not
    # delete the link itself — the same reasoning `task_events.actor_user_id`
    # already documents.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
