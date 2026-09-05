"""task revisions — recover a title or description somebody saved over

Revision ID: 0038_task_revisions
Revises: 0037_book_shared_notification
Create Date: Phase 26

`task_revisions` (see `models/task_revision.py`) holds the content a save
*replaced*, so the live values on `tasks` stay the only answer to "what does
this say now". Two new `task_events` kinds come with it — `description_changed`
(a description edit wrote no history row at all before this, which is what
made an overwrite unrecoverable) and `restored` — so the closed set's CHECK
constraint needs the same drop/recreate every other addition to it has used.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0038_task_revisions"
down_revision = "0037_book_shared_notification"
branch_labels = None
depends_on = None

OLD_EVENTS = (
    "('created', 'status_changed', 'closed', 'reopened', 'owner_changed', "
    "'action_required_set', 'action_required_cleared', 'moved', 'due_changed', "
    "'renamed', 'access_granted', 'access_revoked', "
    "'time_logged', 'time_edited', 'time_deleted', 'priority_changed', "
    "'hidden', 'unhidden', 'dependency_added', 'dependency_removed')"
)
NEW_EVENTS = OLD_EVENTS[:-1] + ", 'description_changed', 'restored')"


def upgrade() -> None:
    op.create_table(
        "task_revisions",
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
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "replaced_by_user_id",
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
    )
    op.create_index("ix_task_revisions_task", "task_revisions", ["task_id", "id"])

    op.drop_constraint("ck_task_events_kind", "task_events", type_="check")
    op.create_check_constraint("ck_task_events_kind", "task_events", f"kind IN {NEW_EVENTS}")


def downgrade() -> None:
    op.drop_constraint("ck_task_events_kind", "task_events", type_="check")
    op.execute("DELETE FROM task_events WHERE kind IN ('description_changed', 'restored')")
    op.create_check_constraint("ck_task_events_kind", "task_events", f"kind IN {OLD_EVENTS}")

    op.drop_index("ix_task_revisions_task", table_name="task_revisions")
    op.drop_table("task_revisions")
