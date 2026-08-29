"""deadline-tomorrow nudge, and the opt-out daily digest

Revision ID: 0019_deadline_and_daily_summary
Revises: 0018_task_pins
Create Date: Phase 14

Two new claims, same discipline as `reminders.notified_ahead_at`:

`tasks.deadline_notified_at` is set by one conditional UPDATE in the
deadline sweep, so a restart or two schedulers racing fires the "due
tomorrow" nudge once, not twice. `services/tasks.py` clears it whenever
`due_on` changes — see reminders' own `update_one` for why that matters:
without it, rescheduling a task's due date would leave it permanently
silent about the new date.

`users.last_daily_summary_sent_on` is the same idea for the daily
digest, a date rather than a timestamp because the question the sweep
asks is "did they get today's", and a date is the whole answer.
`daily_summary_enabled` defaults **true** — the whole point of a digest
nobody has to remember to check is that almost nobody would ever find
the setting to turn it on.
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_deadline_and_daily_summary"
down_revision = "0018_task_pins"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "('task_action_required', 'task_owner_changed', 'task_closed', "
    "'task_shared', 'project_shared', 'reminder_soon', 'reminder_due')"
)
NEW_KINDS = OLD_KINDS[:-1] + ", 'task_deadline_tomorrow', 'daily_summary')"


def upgrade() -> None:
    op.add_column(
        "tasks", sa.Column("deadline_notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "daily_summary_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column("users", sa.Column("last_daily_summary_sent_on", sa.Date(), nullable=True))

    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {NEW_KINDS}")


def downgrade() -> None:
    op.execute(
        "DELETE FROM notifications WHERE kind IN ('task_deadline_tomorrow', 'daily_summary')"
    )
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {OLD_KINDS}")

    op.drop_column("users", "last_daily_summary_sent_on")
    op.drop_column("users", "daily_summary_enabled")
    op.drop_column("tasks", "deadline_notified_at")
