"""book_shared notification kind

Revision ID: 0037_book_shared_notification
Revises: 0036_article_attachments
Create Date: Phase 26

`services/books.py::grant` now notifies a person directly granted access —
the identical `KIND_TASK_SHARED` shape, just naming a book. No new kind for
articles: publishing/privatising is the owner's own action on their own
thing, the same "no notification on generation" reasoning recurring tasks
already document.
"""

from alembic import op

revision = "0037_book_shared_notification"
down_revision = "0036_article_attachments"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "('task_action_required', 'task_action_required_cleared', 'task_owner_changed', "
    "'task_closed', 'task_shared', 'project_shared', 'reminder_soon', 'reminder_due', "
    "'task_deadline_tomorrow', 'daily_summary', 'export_ready')"
)
NEW_KINDS = OLD_KINDS[:-1] + ", 'book_shared')"


def upgrade() -> None:
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {NEW_KINDS}")


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'book_shared'")
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {OLD_KINDS}")
