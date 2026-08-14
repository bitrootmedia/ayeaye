"""message_attachments — files on comments

Revision ID: 0008_attachments
Revises: 0007_conversations
Create Date: Phase 6b

`message_id` is **nullable** on purpose: the row exists before the comment
does. You attach, then send. Binding is scoped to the conversation, the
uploader and `message_id IS NULL`, so an id can't be reused or borrowed from
another thread.

`storage_key` is unique and is *not* derived from the filename — two people
uploading "photo.jpg" must not collide, and a filename is attacker input.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_attachments"
down_revision = "0007_conversations"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("id", UUID, server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("message_id", UUID, nullable=True),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("storage_key", sa.String(length=400), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready')", name="ck_message_attachments_status"
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_message_attachments_key"),
    )
    op.create_index("ix_message_attachments_message", "message_attachments", ["message_id"])
    # The sweep, and "what have I staged in this thread".
    op.create_index(
        "ix_message_attachments_pending", "message_attachments", ["conversation_id", "status"]
    )


def downgrade() -> None:
    op.drop_table("message_attachments")
