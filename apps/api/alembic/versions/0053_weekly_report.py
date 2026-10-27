"""weekly report: Monday's summary of last week, for organisation admins

Revision ID: 0053_weekly_report
Revises: 0052_recall
Create Date: weekly report

See `services/weekly_report.py`. Two columns on `users` (the opt-out and the
claim) and one notification kind. The `enabled_kinds` backfill reaches
**email channels only**: the report was asked for as an email, and a page of
it arriving in a Telegram chat is something to choose, not something to find
one Monday.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053_weekly_report"
down_revision: str | None = "0052_recall"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "('task_action_required', 'task_action_required_cleared', 'task_owner_changed', "
    "'task_closed', 'task_shared', 'project_shared', 'reminder_soon', 'reminder_due', "
    "'task_deadline_tomorrow', 'daily_summary', 'export_ready', 'book_shared', "
    "'comment_mention', 'timer_paused')"
)
NEW_KINDS = OLD_KINDS[:-1] + ", 'weekly_report')"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "weekly_report_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    op.add_column("users", sa.Column("last_weekly_report_sent_on", sa.Date(), nullable=True))

    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {NEW_KINDS}")
    op.execute(
        "UPDATE notification_channels "
        "SET enabled_kinds = array_append(enabled_kinds, 'weekly_report') "
        "WHERE kind = 'email' AND NOT (enabled_kinds @> ARRAY['weekly_report']::text[])"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE notification_channels "
        "SET enabled_kinds = array_remove(enabled_kinds, 'weekly_report')"
    )
    op.execute("DELETE FROM notifications WHERE kind = 'weekly_report'")
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {OLD_KINDS}")
    op.drop_column("users", "last_weekly_report_sent_on")
    op.drop_column("users", "weekly_report_enabled")
