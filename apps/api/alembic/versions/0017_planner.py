"""a personal day planner: five buckets, and a pool of what isn't in one

Revision ID: 0017_planner
Revises: 0016_access_tokens
Create Date: Phase 12

One row per person per task — a task is unplanned (no row) or in exactly one
bucket, never both, never two. The unique constraint on (task_id, user_id) is
what the upsert in services/planner.py relies on, the same way
uq_task_notes_task_user is relied on by services/notes.py.

No organisation_id column: it isn't denormalized here any more than it is on
task_notes, and org-scoping happens by joining to tasks.organisation_id. This
is a small per-person list, never a paginated bulk endpoint, so that join
costs nothing worth indexing around.

`position` is a plain integer, same convention as tasks.position: the client
resends absolute values on every drop and there is no server-side
resequencing. See services/planner.py.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_planner"
down_revision = "0016_access_tokens"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)

BUCKETS = ("today", "tomorrow", "this_week", "next_week", "someday")


def upgrade() -> None:
    op.create_table(
        "planner_entries",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bucket", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(f"bucket IN {BUCKETS!r}", name="ck_planner_entries_bucket"),
        sa.UniqueConstraint("task_id", "user_id", name="uq_planner_entries_task_user"),
    )
    op.create_index("ix_planner_entries_task_id", "planner_entries", ["task_id"])
    op.create_index("ix_planner_entries_user_id", "planner_entries", ["user_id"])
    # The bucket read: one person's, one bucket, in manual order.
    op.create_index(
        "ix_planner_entries_user_bucket", "planner_entries", ["user_id", "bucket", "position"]
    )


def downgrade() -> None:
    op.drop_table("planner_entries")
