"""data export: exports table, export_ready notification kind

Revision ID: 0028_exports
Revises: 0027_mfa
Create Date: Phase 24

`exports` is keyed on `requested_by_user_id`, not shared with the rest of
the organisation — see models/export.py's own docstring for why the
privacy rule (no admin override) matters here specifically: the zip's
contents are the requester's own visibility snapshot, not the
organisation's. `project_id` nullable means the whole organisation;
`downloaded_at` is the "confirmed download" signal the autodelete sweep
acts on, and `status` grows a fourth value, `expired`, for a row whose
object has already been deleted.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_exports"
down_revision = "0027_mfa"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)

OLD_KINDS = (
    "('task_action_required', 'task_owner_changed', 'task_closed', "
    "'task_shared', 'project_shared', 'reminder_soon', 'reminder_due', "
    "'task_deadline_tomorrow', 'daily_summary')"
)
NEW_KINDS = OLD_KINDS[:-1] + ", 'export_ready')"


def upgrade() -> None:
    op.create_table(
        "exports",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "organisation_id",
            UUID,
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "requested_by_user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("storage_key", sa.String(length=300), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed', 'expired')", name="ck_exports_status"
        ),
    )
    op.create_index("ix_exports_org_user", "exports", ["organisation_id", "requested_by_user_id"])

    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {NEW_KINDS}")


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'export_ready'")
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {OLD_KINDS}")

    op.drop_table("exports")
