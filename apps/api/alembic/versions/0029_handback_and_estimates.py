"""action-required handback notification, task estimate fields

Revision ID: 0029_handback_and_estimates
Revises: 0028_exports
Create Date: Phase 25

Two small, unrelated additions landed together because they were asked for
in the same batch. `task_action_required_cleared` is the other half of the
existing action-required notification — see
`services/tasks.py::should_notify_handback`. `estimated_start_on` and
`estimated_hours` are purely informational planning fields, deliberately
not wired into any event/history row — see `services/tasks.py::update()`'s
own comment for why they get the same silent-set treatment `position`
already has.
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_handback_and_estimates"
down_revision = "0028_exports"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "('task_action_required', 'task_owner_changed', 'task_closed', "
    "'task_shared', 'project_shared', 'reminder_soon', 'reminder_due', "
    "'task_deadline_tomorrow', 'daily_summary', 'export_ready')"
)
NEW_KINDS = OLD_KINDS[:-1] + ", 'task_action_required_cleared')"


def upgrade() -> None:
    op.add_column("tasks", sa.Column("estimated_start_on", sa.Date(), nullable=True))
    op.add_column("tasks", sa.Column("estimated_hours", sa.Numeric(6, 1), nullable=True))

    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {NEW_KINDS}")


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'task_action_required_cleared'")
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {OLD_KINDS}")

    op.drop_column("tasks", "estimated_hours")
    op.drop_column("tasks", "estimated_start_on")
