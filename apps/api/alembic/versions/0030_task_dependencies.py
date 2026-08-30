"""task dependencies — "depends on", informational not enforced

Revision ID: 0030_task_dependencies
Revises: 0029_handback_and_estimates
Create Date: Phase 25

`task_dependencies` (see `models/task_dependency.py`): `task_id` is the
dependent task, `depends_on_task_id` is what it's waiting on. Cycle
prevention is a recursive query at write time (`services/dependencies.py`),
not a database constraint — Postgres has no built-in way to check "does this
edge close a cycle" declaratively. Every add/remove writes a `task_events`
row, so the CHECK constraint on `kind` needs the same drop/recreate every
other addition to that closed set already uses.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030_task_dependencies"
down_revision = "0029_handback_and_estimates"
branch_labels = None
depends_on = None

OLD_EVENTS = (
    "('created', 'status_changed', 'closed', 'reopened', 'owner_changed', "
    "'action_required_set', 'action_required_cleared', 'moved', 'due_changed', "
    "'renamed', 'access_granted', 'access_revoked', "
    "'time_logged', 'time_edited', 'time_deleted', 'priority_changed', "
    "'hidden', 'unhidden')"
)
NEW_EVENTS = OLD_EVENTS[:-1] + ", 'dependency_added', 'dependency_removed')"


def upgrade() -> None:
    op.create_table(
        "task_dependencies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuidv7()"),
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "depends_on_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "task_id", "depends_on_task_id", name="uq_task_dependencies_task_depends_on"
        ),
        sa.CheckConstraint("task_id != depends_on_task_id", name="ck_task_dependencies_not_self"),
    )
    op.create_index("ix_task_dependencies_task_id", "task_dependencies", ["task_id"])
    op.create_index(
        "ix_task_dependencies_depends_on_task_id", "task_dependencies", ["depends_on_task_id"]
    )

    op.drop_constraint("ck_task_events_kind", "task_events", type_="check")
    op.create_check_constraint("ck_task_events_kind", "task_events", f"kind IN {NEW_EVENTS}")


def downgrade() -> None:
    op.drop_constraint("ck_task_events_kind", "task_events", type_="check")
    op.execute(
        "DELETE FROM task_events WHERE kind IN ('dependency_added', 'dependency_removed')"
    )
    op.create_check_constraint("ck_task_events_kind", "task_events", f"kind IN {OLD_EVENTS}")

    op.drop_index("ix_task_dependencies_depends_on_task_id", table_name="task_dependencies")
    op.drop_index("ix_task_dependencies_task_id", table_name="task_dependencies")
    op.drop_table("task_dependencies")
