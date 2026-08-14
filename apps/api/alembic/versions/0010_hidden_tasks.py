"""tasks that only their owner can see

Revision ID: 0010_hidden_tasks
Revises: 0009_priority_and_files
Create Date: Phase 9

One nullable timestamp, and it carries the only subtraction of access in the
product. Set, and `services/access.py` short-circuits every route in except
ownership — grants, project inheritance and organisation admins included.

Deliberately a column on `tasks` rather than a row somewhere, because the
access expression has to consult it on **every** task query and a join would
put it behind a NULL check in five more places.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_hidden_tasks"
down_revision = "0009_priority_and_files"
branch_labels = None
depends_on = None

OLD_EVENTS = (
    "('created', 'status_changed', 'closed', 'reopened', 'owner_changed', "
    "'action_required_set', 'action_required_cleared', 'moved', 'due_changed', "
    "'renamed', 'access_granted', 'access_revoked', "
    "'time_logged', 'time_edited', 'time_deleted', 'priority_changed')"
)
NEW_EVENTS = OLD_EVENTS[:-1] + ", 'hidden', 'unhidden')"


def upgrade() -> None:
    op.add_column("tasks", sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))
    # Partial: hidden tasks are the rare case, and the index only ever serves
    # queries looking for them.
    op.create_index(
        "ix_tasks_hidden",
        "tasks",
        ["owner_user_id"],
        postgresql_where=sa.text("hidden_at IS NOT NULL"),
    )

    op.drop_constraint("ck_task_events_kind", "task_events", type_="check")
    op.create_check_constraint("ck_task_events_kind", "task_events", f"kind IN {NEW_EVENTS}")


def downgrade() -> None:
    # Un-hide on the way down. Dropping the column silently makes every hidden
    # task visible to the whole organisation, and doing it explicitly is the
    # difference between a decision and an accident.
    op.execute("UPDATE tasks SET hidden_at = NULL WHERE hidden_at IS NOT NULL")
    op.drop_constraint("ck_task_events_kind", "task_events", type_="check")
    op.execute("DELETE FROM task_events WHERE kind IN ('hidden', 'unhidden')")
    op.create_check_constraint("ck_task_events_kind", "task_events", f"kind IN {OLD_EVENTS}")
    op.drop_index("ix_tasks_hidden", table_name="tasks")
    op.drop_column("tasks", "hidden_at")
