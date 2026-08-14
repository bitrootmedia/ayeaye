"""tags, and the one that takes work off the board

Revision ID: 0011_tags
Revises: 0010_hidden_tasks
Create Date: Phase 9

A shared per-organisation vocabulary. The index worth reading is
`uq_tags_org_name`: it is on **`lower(name)`**, because without that you get
`kb`, `KB` and `Kb` within a week and no filter finds all three.

`off_board` is what makes a tag more than a label — tasks carrying one leave
the board and the list, which is how "this is a knowledge base item rather
than a task" is expressed without a second entity type.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_tags"
down_revision = "0010_hidden_tasks"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "organisation_id",
            UUID,
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("off_board", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_by_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("id", "organisation_id", name="uq_tags_id_org"),
    )
    op.create_index("ix_tags_organisation_id", "tags", ["organisation_id"])
    # Case-insensitive uniqueness. Display keeps whatever case was typed.
    op.execute("CREATE UNIQUE INDEX uq_tags_org_name ON tags (organisation_id, lower(name))")

    op.create_table(
        "task_tags",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", UUID, sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "tag_id", name="uq_task_tags_task_tag"),
    )
    op.create_index("ix_task_tags_task_id", "task_tags", ["task_id"])
    op.create_index("ix_task_tags_tag", "task_tags", ["tag_id"])

    # Search matches tag names, so they get the same trigram index as every
    # other searchable column (migration 0005).
    op.execute("CREATE INDEX ix_tags_name_trgm ON tags USING gin (name gin_trgm_ops)")


def downgrade() -> None:
    op.drop_table("task_tags")
    op.execute("DROP INDEX IF EXISTS ix_tags_name_trgm")
    op.execute("DROP INDEX IF EXISTS uq_tags_org_name")
    op.drop_table("tags")
