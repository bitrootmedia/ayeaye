"""Tasks, their per-task grants, and the append-only history of what happened.

    projects ──► tasks ──┬── task_grants   (user XOR team; additive to the project)
                         └── task_events   (append-only; this IS the history)

`project_id` is **nullable**. A task with no project is "loose" — it belongs to
the organisation, and it is deliberately *not* visible to everyone in it. See
`services/access.py` for what does make it visible.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.structure import GRANT_LEVELS, LEVEL_READ

# The fixed status set. Widened from PLAN.md §9 with TODO, because none of the
# other four is a sensible landing spot for a brand-new task — and if ON HOLD
# were the default it would be the commonest status in the system and would
# stop meaning "deliberately parked".
#
#     TODO  →  IN PROGRESS  →  REVIEW
#                  ↕
#          ON HOLD / BLOCKER
#
STATUS_TODO = "todo"
STATUS_IN_PROGRESS = "in_progress"
STATUS_ON_HOLD = "on_hold"
STATUS_REVIEW = "review"
STATUS_BLOCKER = "blocker"
STATUSES = (STATUS_TODO, STATUS_IN_PROGRESS, STATUS_ON_HOLD, STATUS_REVIEW, STATUS_BLOCKER)

# Priority, most urgent first. `NORMAL` is the default and the middle of the
# range, so raising and lowering are equally easy — a scale where the default
# is at one end only ever moves one way.
#
# Rendered as a DIRECTION glyph, not another coloured dot: status already owns
# the only red (blocker) and the only amber (review), and a second dot badge
# per card would make red stop meaning "this needs you". Colour appears on
# CRITICAL and URGENT alone. See PRIORITY_* in the frontend's lib/types.ts.
PRIORITY_CRITICAL = "critical"
PRIORITY_URGENT = "urgent"
PRIORITY_HIGH = "high"
PRIORITY_NORMAL = "normal"
PRIORITY_LOW = "low"
PRIORITY_VERY_LOW = "very_low"
PRIORITIES = (
    PRIORITY_CRITICAL,
    PRIORITY_URGENT,
    PRIORITY_HIGH,
    PRIORITY_NORMAL,
    PRIORITY_LOW,
    PRIORITY_VERY_LOW,
)
# Stored as a name, sorted by a number. A `smallint` column would sort for free
# but would put an ordering decision in every INSERT; this keeps the name
# authoritative and the rank derived.
PRIORITY_RANK = {name: len(PRIORITIES) - i for i, name in enumerate(PRIORITIES)}

# What happened to a task. Append-only; a closed set so the history can be
# rendered without a fallback branch for "some event we don't know about".
EVENT_CREATED = "created"
EVENT_STATUS_CHANGED = "status_changed"
EVENT_CLOSED = "closed"
EVENT_REOPENED = "reopened"
EVENT_OWNER_CHANGED = "owner_changed"
EVENT_ACTION_REQUIRED_SET = "action_required_set"
EVENT_ACTION_REQUIRED_CLEARED = "action_required_cleared"
EVENT_MOVED = "moved"
EVENT_DUE_CHANGED = "due_changed"
EVENT_RENAMED = "renamed"
EVENT_ACCESS_GRANTED = "access_granted"
EVENT_ACCESS_REVOKED = "access_revoked"
# Time. PLAN.md §9 settles that entries stay editable after the fact — people
# forget to stop timers — so every correction leaves a trail here rather than
# quietly changing the numbers.
EVENT_TIME_LOGGED = "time_logged"
EVENT_TIME_EDITED = "time_edited"
EVENT_TIME_DELETED = "time_deleted"
EVENT_PRIORITY_CHANGED = "priority_changed"
EVENT_HIDDEN = "hidden"
EVENT_UNHIDDEN = "unhidden"
EVENT_KINDS = (
    EVENT_CREATED,
    EVENT_STATUS_CHANGED,
    EVENT_CLOSED,
    EVENT_REOPENED,
    EVENT_OWNER_CHANGED,
    EVENT_ACTION_REQUIRED_SET,
    EVENT_ACTION_REQUIRED_CLEARED,
    EVENT_MOVED,
    EVENT_DUE_CHANGED,
    EVENT_RENAMED,
    EVENT_ACCESS_GRANTED,
    EVENT_ACCESS_REVOKED,
    EVENT_TIME_LOGGED,
    EVENT_TIME_EDITED,
    EVENT_TIME_DELETED,
    EVENT_PRIORITY_CHANGED,
    EVENT_HIDDEN,
    EVENT_UNHIDDEN,
)


class Task(Base):
    """One piece of work.

    **Status and open/closed are two different fields, on purpose.** Closing is
    not a transition to a "done" status: a task can be closed from any status,
    and "closed while still BLOCKER" is expressible — which is what actually
    happens when work is abandoned rather than finished. Collapsing them would
    make the board lie about why something stopped.

    **Owner and action-required are also two different things.** The owner is
    responsible and is the only person who may close it. The action-required
    user is at most one person who is being asked to do something *now*, and
    setting it notifies them. Clearing it is not a close.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(f"status IN {STATUSES!r}", name="ck_tasks_status"),
        CheckConstraint(f"priority IN {PRIORITIES!r}", name="ck_tasks_priority"),
        # The board query: everything open in one project, in display order.
        Index("ix_tasks_project_open", "project_id", "closed_at"),
        Index("ix_tasks_org_open", "organisation_id", "closed_at"),
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
    # NULL = a loose task, owned by the organisation rather than a project.
    # CASCADE: deleting a project deletes its tasks. Moving them somewhere
    # would be a decision nobody asked for at the moment of deletion.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=STATUS_TODO)

    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=PRIORITY_NORMAL
    )

    # Hidden. **The one place in this product where access is subtracted.**
    #
    # Set, and nobody but `owner_user_id` can see the task — grants included,
    # project inheritance included, organisation admins included. It is not a
    # deny rule inside the grant algebra (there are none, and there must not
    # be): it is a precondition that short-circuits *before* any route is
    # resolved. See the top of `services/access.py`.
    #
    # A timestamp for the same reason as `closed_at` — the history gets the
    # *when* for free.
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Open/closed. A timestamp rather than a boolean, so the history has the
    # *when* without having to go and read task_events for it.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # RESTRICT: a task with no owner is one nobody may close. Removing someone
    # who owns tasks has to reassign them first — see services/tasks.py.
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # At most one, enforced by being a column rather than a table. A list of
    # people who all need to act is a list of people who each assume it's
    # somebody else.
    action_required_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Manual ordering within a board column. Ties break on `id`, which is
    # UUIDv7 and therefore creation order — so an untouched board is
    # chronological without anyone having to set this.
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_func.now(),
        onupdate=sa_func.now(),
    )

    grants: Mapped[list["TaskGrant"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskGrant(Base):
    """Access to one task, on top of whatever its project already grants.

    Additive only. There is no way to grant *less* on a task than its project
    gives — that would be a deny rule, and rule 2 says most-permissive-wins.
    Same shape and same `num_nonnulls` constraint as `project_members`.
    """

    __tablename__ = "task_grants"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(user_id, team_id) = 1", name="ck_task_grants_one_principal"
        ),
        CheckConstraint(f"level IN {GRANT_LEVELS!r}", name="ck_task_grants_level"),
        Index(
            "uq_task_grants_user",
            "task_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_task_grants_team",
            "task_id",
            "team_id",
            unique=True,
            postgresql_where=text("team_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, server_default=LEVEL_READ)
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )

    task: Mapped[Task] = relationship(back_populates="grants")


class TaskEvent(Base):
    """What happened, in order. **Append-only: never UPDATE, never DELETE.**

    This is the "history of work" from PLAN.md §3 — don't build it a second
    time. Every workflow change writes one of these in the same transaction as
    the change itself, so a row here and the task's state can't disagree.

    `data` is JSONB rather than columns per event kind: the shape differs per
    kind and it is only ever rendered, never queried on. Anything that becomes
    worth filtering by earns a real column.
    """

    __tablename__ = "task_events"
    __table_args__ = (
        CheckConstraint(f"kind IN {EVENT_KINDS!r}", name="ck_task_events_kind"),
        # The history query: one task, oldest first. UUIDv7 sorts by time.
        Index("ix_task_events_task", "task_id", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL, not CASCADE: deleting a person must not rewrite history. The
    # event stays, attributed to nobody.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
