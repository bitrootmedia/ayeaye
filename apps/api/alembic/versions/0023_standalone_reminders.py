"""standalone reminders: a reminder with no task behind it

Revision ID: 0023_standalone_reminders
Revises: 0022_disable_members
Create Date: Phase 19

`reminders.task_id` becomes nullable and gains a sibling `title` (the
standalone reminder's own "what") and `organisation_id` (its own
organisation, since there's no task to read one from). Two CHECK
constraints keep the two shapes from drifting into a third:
`ck_reminders_one_anchor` (`num_nonnulls(task_id, title) = 1`) and
`ck_reminders_org_iff_standalone` (`(task_id IS NULL) = (organisation_id
IS NOT NULL)`). See models/reminder.py for the full reasoning.

Every existing row is task-anchored, so the nullable columns default to
NULL for all of them and the constraints hold immediately — no backfill
needed.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_standalone_reminders"
down_revision = "0022_disable_members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("reminders", "task_id", nullable=True)
    op.add_column(
        "reminders",
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("reminders", sa.Column("title", sa.String(length=200), nullable=True))

    op.create_foreign_key(
        "fk_reminders_organisation_id",
        "reminders",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_reminders_one_anchor", "reminders", "num_nonnulls(task_id, title) = 1"
    )
    op.create_check_constraint(
        "ck_reminders_org_iff_standalone",
        "reminders",
        "(task_id IS NULL) = (organisation_id IS NOT NULL)",
    )


def downgrade() -> None:
    # A standalone reminder has no task to fall back to — deleting them is
    # the only honest downgrade, the same reasoning a CHECK-constraint
    # downgrade elsewhere in this codebase uses when the newer shape has no
    # equivalent in the older one.
    op.execute("DELETE FROM reminders WHERE task_id IS NULL")

    op.drop_constraint("ck_reminders_org_iff_standalone", "reminders", type_="check")
    op.drop_constraint("ck_reminders_one_anchor", "reminders", type_="check")
    op.drop_constraint("fk_reminders_organisation_id", "reminders", type_="foreignkey")

    op.drop_column("reminders", "title")
    op.drop_column("reminders", "organisation_id")
    op.alter_column("reminders", "task_id", nullable=False)
