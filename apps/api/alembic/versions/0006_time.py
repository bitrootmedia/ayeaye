"""time_entries, and the event kinds that record corrections to them

Revision ID: 0006_time
Revises: 0005_search
Create Date: Phase 5

The interesting line is `uq_time_entries_one_running`: a partial unique index
on `(user_id) WHERE ended_at IS NULL`. That is the one-running-timer rule, in
the database rather than in application code, and it is **global per person**
rather than per organisation — otherwise anyone could run three timers by
belonging to three organisations.

Also widens `ck_task_events_kind` for the three time events. PLAN.md §9
settles that entries stay editable after the fact, so every correction has to
leave a trail; a CHECK constraint that hasn't been widened turns that trail
into an IntegrityError at the worst moment.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_time"
down_revision = "0005_search"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)

OLD_EVENT_KINDS = (
    "('created', 'status_changed', 'closed', 'reopened', 'owner_changed', "
    "'action_required_set', 'action_required_cleared', 'moved', 'due_changed', "
    "'renamed', 'access_granted', 'access_revoked')"
)
NEW_EVENT_KINDS = (
    "('created', 'status_changed', 'closed', 'reopened', 'owner_changed', "
    "'action_required_set', 'action_required_cleared', 'moved', 'due_changed', "
    "'renamed', 'access_granted', 'access_revoked', "
    "'time_logged', 'time_edited', 'time_deleted')"
)


def upgrade() -> None:
    op.create_table(
        "time_entries",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        # NULL means running. Not a separate boolean — two fields that can
        # disagree about whether a timer is going is a bug with two homes.
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at", name="ck_time_entries_range"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_time_entries_task_id"), "time_entries", ["task_id"])
    op.create_index("ix_time_entries_task", "time_entries", ["task_id", "started_at"])
    op.create_index("ix_time_entries_user", "time_entries", ["user_id", "started_at"])
    op.create_index(
        "uq_time_entries_one_running",
        "time_entries",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    op.drop_constraint("ck_task_events_kind", "task_events", type_="check")
    op.create_check_constraint("ck_task_events_kind", "task_events", f"kind IN {NEW_EVENT_KINDS}")


def downgrade() -> None:
    op.drop_constraint("ck_task_events_kind", "task_events", type_="check")
    # The rows have to go before the constraint can come back, or the old
    # CHECK fails validation against history it was never written for.
    op.execute("DELETE FROM task_events WHERE kind IN ('time_logged','time_edited','time_deleted')")
    op.create_check_constraint("ck_task_events_kind", "task_events", f"kind IN {OLD_EVENT_KINDS}")
    op.drop_table("time_entries")
