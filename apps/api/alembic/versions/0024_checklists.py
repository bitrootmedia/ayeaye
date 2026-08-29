"""checklists: a quick todo list under a task, more than one allowed

Revision ID: 0024_checklists
Revises: 0023_standalone_reminders
Create Date: Phase 20

Two tables, `task_checklists` and `task_checklist_items`, ordered by `id`
rather than a `position` column — UUIDv7 sorts chronologically, so creation
order is free. See models/checklist.py.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024_checklists"
down_revision = "0023_standalone_reminders"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "task_checklists",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_task_checklists_task_id", "task_checklists", ["task_id"])

    op.create_table(
        "task_checklist_items",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "checklist_id",
            UUID,
            sa.ForeignKey("task_checklists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_task_checklist_items_checklist_id", "task_checklist_items", ["checklist_id"]
    )


def downgrade() -> None:
    op.drop_table("task_checklist_items")
    op.drop_table("task_checklists")
