"""personal task pins: a bookmark, not a property of the task

Revision ID: 0018_task_pins
Revises: 0017_planner
Create Date: Phase 13

One row per person per task, the same shape as task_notes and
planner_entries and for the same reason: pinning is what *you* want on
*your* dashboard, not a fact about the task everyone else sees. See
services/pins.py.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_task_pins"
down_revision = "0017_planner"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "task_pins",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("task_id", "user_id", name="uq_task_pins_task_user"),
    )
    op.create_index("ix_task_pins_task_id", "task_pins", ["task_id"])
    op.create_index("ix_task_pins_user_id", "task_pins", ["user_id"])


def downgrade() -> None:
    op.drop_table("task_pins")
