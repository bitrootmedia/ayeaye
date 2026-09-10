"""comment_mention notification kind, and the enabled_kinds backfill it needs

Revision ID: 0045_comment_mention
Revises: 0044_daily_summary_hour
Create Date: Phase 9 follow-up

`services/mentions.py`: naming somebody in a comment notifies them, with its
own kind rather than the generic comment nudge — it is the one comment
notification that ignores the unread-run debounce.

**The `enabled_kinds` backfill is the part that isn't optional.**
`notification_channels.enabled_kinds` is an explicit array, filled with every
kind that existed when the channel row was created (see
`notification_channels.get_or_create_email_channel`) — so a new kind is
*disabled* on every channel that already exists, and the nudge silently never
sends for anybody who has been notified even once before this migration ran.

That has already happened once: `book_shared` arrived in 0037, six migrations
after channels landed in 0031, with no backfill — so every channel created in
between still has no `book_shared` in its list and has never delivered one.
Both kinds are appended here, `book_shared` included, because fixing it is one
more line in a statement that had to run anyway.

Appended only where missing, so re-running is a no-op and somebody who has
deliberately turned a kind off doesn't have it turned back on.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0045_comment_mention"
down_revision: str | None = "0044_daily_summary_hour"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "('task_action_required', 'task_action_required_cleared', 'task_owner_changed', "
    "'task_closed', 'task_shared', 'project_shared', 'reminder_soon', 'reminder_due', "
    "'task_deadline_tomorrow', 'daily_summary', 'export_ready', 'book_shared')"
)
NEW_KINDS = OLD_KINDS[:-1] + ", 'comment_mention')"


def upgrade() -> None:
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {NEW_KINDS}")
    for kind in ("comment_mention", "book_shared"):
        op.execute(
            "UPDATE notification_channels "
            f"SET enabled_kinds = array_append(enabled_kinds, '{kind}') "
            f"WHERE NOT (enabled_kinds @> ARRAY['{kind}']::text[])"
        )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'comment_mention'")
    op.execute(
        "UPDATE notification_channels "
        "SET enabled_kinds = array_remove(enabled_kinds, 'comment_mention')"
    )
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {OLD_KINDS}")
