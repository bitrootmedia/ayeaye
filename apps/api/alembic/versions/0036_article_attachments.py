"""article attachments — a third anchor on the one attachments table

Revision ID: 0036_article_attachments
Revises: 0035_knowledge_base
Create Date: Phase 26

An attachment can now also anchor to an `article_revision` — inline images
and standalone files on a knowledge-base article, the same table tasks and
comments already share (see CLAUDE.md's "one table, two anchors", now three).
The CHECK widens from "exactly one of two" to "exactly one of three"; nothing
about `task_id`/`conversation_id`'s own behaviour changes.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036_article_attachments"
down_revision = "0035_knowledge_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attachments",
        sa.Column(
            "article_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("article_revisions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_attachments_article_revision", "attachments", ["article_revision_id", "status"]
    )

    op.drop_constraint("ck_attachments_one_anchor", "attachments", type_="check")
    op.create_check_constraint(
        "ck_attachments_one_anchor",
        "attachments",
        "num_nonnulls(task_id, conversation_id, article_revision_id) = 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_attachments_one_anchor", "attachments", type_="check")
    op.execute("DELETE FROM attachments WHERE article_revision_id IS NOT NULL")
    op.create_check_constraint(
        "ck_attachments_one_anchor", "attachments", "num_nonnulls(task_id, conversation_id) = 1"
    )
    op.drop_index("ix_attachments_article_revision", table_name="attachments")
    op.drop_column("attachments", "article_revision_id")
