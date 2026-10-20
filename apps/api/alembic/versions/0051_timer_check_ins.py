"""timer check-ins: "still working on this?", and the timer_paused kind

Revision ID: 0051_timer_check_ins
Revises: 0050_instance_settings
Create Date: Phase 9 follow-up

See `services/check_ins.py`. A running timer asks now and then whether you
are still on it — in Telegram, the menu bar app and the web header — and
nobody answering pauses it, which is what `timer_paused` tells you.

Three columns on `time_entries` (the check-in's state lives on the running
entry it is about), four on `users` (the preference, the daily cap and the
day's count), one notification kind with 0045's `enabled_kinds` backfill —
a kind missing from that list is a kind that never sends.

Timers already running when this lands get their first question an hour
from now rather than immediately: a migration is not a reason to interrupt
everybody at once.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051_timer_check_ins"
down_revision: str | None = "0050_instance_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "('task_action_required', 'task_action_required_cleared', 'task_owner_changed', "
    "'task_closed', 'task_shared', 'project_shared', 'reminder_soon', 'reminder_due', "
    "'task_deadline_tomorrow', 'daily_summary', 'export_ready', 'book_shared', "
    "'comment_mention')"
)
NEW_KINDS = OLD_KINDS[:-1] + ", 'timer_paused')"


def upgrade() -> None:
    for column in ("next_check_in_at", "check_in_asked_at", "check_in_deadline"):
        op.add_column("time_entries", sa.Column(column, sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE time_entries SET next_check_in_at = now() + interval '1 hour' "
        "WHERE ended_at IS NULL"
    )

    op.add_column(
        "users",
        sa.Column(
            "timer_check_ins", sa.String(16), nullable=False, server_default=sa.text("'telegram'")
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "timer_check_ins_per_day",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("6"),
        ),
    )
    op.add_column("users", sa.Column("timer_check_ins_day", sa.Date(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "timer_check_ins_count", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.create_check_constraint(
        "ck_users_timer_check_ins", "users", "timer_check_ins IN ('telegram', 'apps', 'off')"
    )
    op.create_check_constraint(
        "ck_users_timer_check_ins_per_day", "users", "timer_check_ins_per_day BETWEEN 1 AND 24"
    )

    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {NEW_KINDS}")
    op.execute(
        "UPDATE notification_channels "
        "SET enabled_kinds = array_append(enabled_kinds, 'timer_paused') "
        "WHERE NOT (enabled_kinds @> ARRAY['timer_paused']::text[])"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'timer_paused'")
    op.execute(
        "UPDATE notification_channels "
        "SET enabled_kinds = array_remove(enabled_kinds, 'timer_paused')"
    )
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {OLD_KINDS}")

    op.drop_constraint("ck_users_timer_check_ins_per_day", "users", type_="check")
    op.drop_constraint("ck_users_timer_check_ins", "users", type_="check")
    for column in (
        "timer_check_ins_count",
        "timer_check_ins_day",
        "timer_check_ins_per_day",
        "timer_check_ins",
    ):
        op.drop_column("users", column)
    for column in ("check_in_deadline", "check_in_asked_at", "next_check_in_at"):
        op.drop_column("time_entries", column)
