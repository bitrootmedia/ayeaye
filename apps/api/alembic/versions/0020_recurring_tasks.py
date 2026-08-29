"""recurring tasks: a template and a cadence, regenerating on schedule

Revision ID: 0020_recurring_tasks
Revises: 0019_deadline_and_daily_summary
Create Date: Phase 15

`task_series` is its own table, not columns on `tasks` — a series outlives
any one occurrence, the same reasoning as `task_pins` and `planner_entries`
being their own tables. `tasks.series_id` is SET NULL on delete: removing a
series stops future generation without touching the tasks it already made.

`next_due_on` is the sweep's claim, same idempotency discipline as
`reminders.notified_ahead_at` — see `services/recurrence.py`.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_recurring_tasks"
down_revision = "0019_deadline_and_daily_summary"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)

INTERVAL_UNITS = "('day', 'week', 'month')"


def upgrade() -> None:
    op.create_table(
        "task_series",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "organisation_id",
            UUID,
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "project_id", UUID, sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "priority", sa.String(length=16), nullable=False, server_default=sa.text("'normal'")
        ),
        sa.Column(
            "owner_user_id", UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "created_by_user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("interval_unit", sa.String(length=8), nullable=False),
        sa.Column("interval_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("next_due_on", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(f"interval_unit IN {INTERVAL_UNITS}", name="ck_task_series_unit"),
        sa.CheckConstraint("interval_count > 0", name="ck_task_series_count_positive"),
    )
    op.create_index("ix_task_series_organisation_id", "task_series", ["organisation_id"])
    op.create_index("ix_task_series_owner_user_id", "task_series", ["owner_user_id"])
    # The sweep's own read: active series whose next occurrence has arrived.
    op.create_index("ix_task_series_next_due_on", "task_series", ["next_due_on"])

    op.add_column(
        "tasks",
        sa.Column(
            "series_id", UUID, sa.ForeignKey("task_series.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.create_index("ix_tasks_series_id", "tasks", ["series_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_series_id", table_name="tasks")
    op.drop_column("tasks", "series_id")
    op.drop_index("ix_task_series_next_due_on", table_name="task_series")
    op.drop_index("ix_task_series_owner_user_id", table_name="task_series")
    op.drop_index("ix_task_series_organisation_id", table_name="task_series")
    op.drop_table("task_series")
