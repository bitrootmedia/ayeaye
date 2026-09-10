"""daily_summary_hour: which local hour the digest goes out, per person

Revision ID: 0044_daily_summary_hour
Revises: 0043_bookmarks
Create Date: Phase 9 follow-up

The hour used to be one module constant (`SUMMARY_HOUR = 7`) applied to
everybody. Reported by somebody whose digest arrived in the middle of the
night, which is what a hardcoded hour does the moment a stored timezone is
wrong — and there was no setting to reach for either way.

Defaults to **6**, not the old 7: this is a "shape the day before it starts"
message, and 6am was what was asked for. Existing rows move with the
default, deliberately — nobody chose 7, it was simply the only value there
was, so there is nothing here to preserve.

The CHECK is the whole validation: the column is written from an API field,
and an hour outside 0–23 would silently mean "never sent" rather than
failing anywhere anyone would notice.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_daily_summary_hour"
down_revision: str | None = "0043_bookmarks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "daily_summary_hour",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("6"),
        ),
    )
    op.create_check_constraint(
        "ck_users_daily_summary_hour",
        "users",
        "daily_summary_hour BETWEEN 0 AND 23",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_daily_summary_hour", "users", type_="check")
    op.drop_column("users", "daily_summary_hour")
