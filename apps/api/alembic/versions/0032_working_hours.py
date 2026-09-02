"""working hours: a weekly pattern of when someone plans to be around

Revision ID: 0032_working_hours
Revises: 0031_notification_channels
Create Date: Phase 9 follow-up

A cell's existence IS the check, the same idiom task_sheet_cells and
task_tags already use. See services/working_hours.py.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032_working_hours"
down_revision = "0031_notification_channels"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "working_hours",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("hour", sa.SmallInteger(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "weekday", "hour", name="uq_working_hours_user_weekday_hour"
        ),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_working_hours_weekday"),
        sa.CheckConstraint("hour BETWEEN 0 AND 23", name="ck_working_hours_hour"),
    )
    op.create_index("ix_working_hours_user_id", "working_hours", ["user_id"])


def downgrade() -> None:
    op.drop_table("working_hours")
