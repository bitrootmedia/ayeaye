"""task priority, and attachments that can hang off a task

Revision ID: 0009_priority_and_files
Revises: 0008_attachments
Create Date: Phase 8

Two changes:

**Priority** on tasks, defaulting to `normal` — the middle of the range, so
raising and lowering are equally easy. A scale whose default sits at one end
only ever moves one way.

**`message_attachments` becomes `attachments`**, anchored to a task *or* a
conversation. One table because the task's Files panel shows both: a file
dropped into a reply is as much "a file on this task" as one added from the
panel. Existing rows are all conversation-anchored, which the new CHECK
already permits, so no data has to move.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_priority_and_files"
down_revision = "0008_attachments"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)

PRIORITIES = "('critical', 'urgent', 'high', 'normal', 'low', 'very_low')"

OLD_EVENTS = (
    "('created', 'status_changed', 'closed', 'reopened', 'owner_changed', "
    "'action_required_set', 'action_required_cleared', 'moved', 'due_changed', "
    "'renamed', 'access_granted', 'access_revoked', "
    "'time_logged', 'time_edited', 'time_deleted')"
)
NEW_EVENTS = OLD_EVENTS[:-1] + ", 'priority_changed')"


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("priority", sa.String(length=16), server_default="normal", nullable=False),
    )
    op.create_check_constraint("ck_tasks_priority", "tasks", f"priority IN {PRIORITIES}")

    op.drop_constraint("ck_task_events_kind", "task_events", type_="check")
    op.create_check_constraint("ck_task_events_kind", "task_events", f"kind IN {NEW_EVENTS}")

    op.rename_table("message_attachments", "attachments")
    op.add_column("attachments", sa.Column("task_id", UUID, nullable=True))
    op.add_column("attachments", sa.Column("thumbnail_key", sa.String(length=400), nullable=True))
    # Was NOT NULL when a conversation was the only possible anchor.
    op.alter_column("attachments", "conversation_id", nullable=True)
    op.create_foreign_key(
        "attachments_task_id_fkey", "attachments", "tasks", ["task_id"], ["id"], ondelete="CASCADE"
    )
    op.create_check_constraint(
        "ck_attachments_one_anchor", "attachments", "num_nonnulls(task_id, conversation_id) = 1"
    )
    op.create_check_constraint(
        "ck_attachments_message_needs_conversation",
        "attachments",
        "message_id IS NULL OR conversation_id IS NOT NULL",
    )
    op.create_index("ix_attachments_task", "attachments", ["task_id", "status"])

    # The old names travelled with the table; rename them so a future reader
    # isn't hunting for a `message_attachments` that no longer exists.
    for old, new in [
        ("ck_message_attachments_status", "ck_attachments_status"),
        ("uq_message_attachments_key", "uq_attachments_key"),
    ]:
        op.execute(f"ALTER TABLE attachments RENAME CONSTRAINT {old} TO {new}")
    for old, new in [
        ("ix_message_attachments_message", "ix_attachments_message"),
        ("ix_message_attachments_pending", "ix_attachments_pending"),
    ]:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")


def downgrade() -> None:
    op.execute("DELETE FROM attachments WHERE task_id IS NOT NULL")
    op.drop_index("ix_attachments_task", table_name="attachments")
    op.drop_constraint("ck_attachments_message_needs_conversation", "attachments", type_="check")
    op.drop_constraint("ck_attachments_one_anchor", "attachments", type_="check")
    op.drop_constraint("attachments_task_id_fkey", "attachments", type_="foreignkey")
    op.drop_column("attachments", "thumbnail_key")
    op.drop_column("attachments", "task_id")
    op.alter_column("attachments", "conversation_id", nullable=False)
    for new, old in [
        ("ck_attachments_status", "ck_message_attachments_status"),
        ("uq_attachments_key", "uq_message_attachments_key"),
    ]:
        op.execute(f"ALTER TABLE attachments RENAME CONSTRAINT {new} TO {old}")
    for new, old in [
        ("ix_attachments_message", "ix_message_attachments_message"),
        ("ix_attachments_pending", "ix_message_attachments_pending"),
    ]:
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    op.rename_table("attachments", "message_attachments")

    op.execute("DELETE FROM task_events WHERE kind = 'priority_changed'")
    op.drop_constraint("ck_task_events_kind", "task_events", type_="check")
    op.create_check_constraint("ck_task_events_kind", "task_events", f"kind IN {OLD_EVENTS}")
    op.drop_constraint("ck_tasks_priority", "tasks", type_="check")
    op.drop_column("tasks", "priority")
