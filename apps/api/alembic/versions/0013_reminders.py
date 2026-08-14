"""reminders, and the timezone that makes "the day before" mean something

Revision ID: 0013_reminders
Revises: 0012_private_notes
Create Date: Phase 9

`notified_ahead_at` and `notified_due_at` are the interesting columns. They
are not audit fields — they are the **claim** that makes the hourly sweep
idempotent. A conditional `UPDATE … WHERE notified_x_at IS NULL` both selects
and marks in one statement, so a scheduler restart, a retry, or two schedulers
racing produce one notification rather than several. Without them, every one
of those is a duplicate email to everybody at once.

`users.timezone` arrives here rather than with the account screen because this
is what needs it: a reminder is a *date*, and which instant that date begins
at is a property of the person.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_reminders"
down_revision = "0012_private_notes"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)

OLD_KINDS = (
    "('task_action_required', 'task_owner_changed', 'task_closed', "
    "'task_shared', 'project_shared')"
)
NEW_KINDS = OLD_KINDS[:-1] + ", 'reminder_soon', 'reminder_due')"


def upgrade() -> None:
    op.add_column("users", sa.Column("timezone", sa.String(length=64), nullable=True))

    op.create_table(
        "reminders",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("remind_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("notified_ahead_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_reminders_task_id", "reminders", ["task_id"])
    op.create_index("ix_reminders_user_id", "reminders", ["user_id"])
    op.create_index("ix_reminders_user", "reminders", ["user_id", "remind_on"])
    # The sweep's index. Partial, because a dismissed reminder is dead weight
    # in the one query that runs every hour forever.
    op.create_index(
        "ix_reminders_pending",
        "reminders",
        ["remind_on"],
        postgresql_where=sa.text("done_at IS NULL"),
    )

    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {NEW_KINDS}")


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind IN ('reminder_soon', 'reminder_due')")
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {OLD_KINDS}")
    op.drop_table("reminders")
    op.drop_column("users", "timezone")
