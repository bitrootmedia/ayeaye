"""conversations, messages and per-person read cursors

Revision ID: 0007_conversations
Revises: 0006_time
Create Date: Phase 6

A conversation is anchored to exactly one thing — a task **or** a project —
and there is at most one per thing. Both facts are constraints rather than
conventions:

* `ck_conversations_one_anchor` — `num_nonnulls(task_id, project_id) = 1`;
* two partial unique indexes, one per anchor column, so the NULL side of every
  row doesn't collide with every other row's NULL.

`message_reads` is one cursor per person per conversation, not a read receipt
per message. The badge only ever asks "how many since my cursor".
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_conversations"
down_revision = "0006_time"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organisation_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=True),
        sa.Column("project_id", UUID, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(task_id, project_id) = 1", name="ck_conversations_one_anchor"
        ),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversations_organisation_id"), "conversations", ["organisation_id"]
    )
    op.create_index(
        "uq_conversations_task",
        "conversations",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("task_id IS NOT NULL"),
    )
    op.create_index(
        "uq_conversations_project",
        "conversations",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )

    op.create_table(
        "messages",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        # Soft delete: a hole in a thread people have already replied to is
        # worse than a tombstone.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        # SET NULL: deleting a person must not tear holes in a discussion other
        # people were part of.
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation", "messages", ["conversation_id", "id"])

    op.create_table(
        "message_reads",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "user_id", name="uq_message_reads"),
    )
    op.create_index(
        op.f("ix_message_reads_conversation_id"), "message_reads", ["conversation_id"]
    )
    op.create_index(op.f("ix_message_reads_user_id"), "message_reads", ["user_id"])


def downgrade() -> None:
    op.drop_table("message_reads")
    op.drop_table("messages")
    op.drop_table("conversations")
