"""chats: direct and group conversations, and the chat list

Revision ID: 0055_chats
Revises: 0054_sheet_text_cells
Create Date: chats

See `services/chats.py`. A conversation gains a `kind`; `direct` and `group`
have no anchor, and `conversation_members` is their access rule.
`message_reads` becomes a person's row in their chat list (pinned, muted,
archived), with `last_read_at` nullable for somebody put in the list before
they've read anything. `last_message_at` is backfilled so existing threads
sort correctly from the first load. One notification kind, backfilled onto
every existing channel: a DM is the thing people most expect to reach them
away from the desk.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055_chats"
down_revision: str | None = "0054_sheet_text_cells"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "('task_action_required', 'task_action_required_cleared', 'task_owner_changed', "
    "'task_closed', 'task_shared', 'project_shared', 'reminder_soon', 'reminder_due', "
    "'task_deadline_tomorrow', 'daily_summary', 'export_ready', 'book_shared', "
    "'comment_mention', 'timer_paused', 'weekly_report')"
)
NEW_KINDS = OLD_KINDS[:-1] + ", 'direct_message')"

KIND_ANCHOR = (
    "(kind = 'task' AND task_id IS NOT NULL AND project_id IS NULL)"
    " OR (kind = 'project' AND project_id IS NOT NULL AND task_id IS NULL)"
    " OR (kind IN ('direct', 'group') AND task_id IS NULL AND project_id IS NULL)"
)


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="task"),
    )
    op.execute("UPDATE conversations SET kind = 'project' WHERE project_id IS NOT NULL")
    op.add_column("conversations", sa.Column("title", sa.String(length=120), nullable=True))
    op.add_column("conversations", sa.Column("direct_key", sa.String(length=80), nullable=True))
    op.add_column(
        "conversations",
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE conversations c SET last_message_at = m.newest "
        "FROM (SELECT conversation_id, max(created_at) AS newest FROM messages "
        "GROUP BY conversation_id) m WHERE m.conversation_id = c.id"
    )
    op.drop_constraint("ck_conversations_one_anchor", "conversations", type_="check")
    op.create_check_constraint("ck_conversations_kind_anchor", "conversations", KIND_ANCHOR)
    op.create_index(
        "uq_conversations_direct",
        "conversations",
        ["organisation_id", "direct_key"],
        unique=True,
        postgresql_where=sa.text("direct_key IS NOT NULL"),
    )
    op.create_index(
        "ix_conversations_last_message",
        "conversations",
        ["organisation_id", "last_message_at"],
    )

    op.create_table(
        "conversation_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuidv7()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("conversation_id", "user_id", name="uq_conversation_members"),
    )
    op.create_index(
        "ix_conversation_members_conversation_id", "conversation_members", ["conversation_id"]
    )
    op.create_index("ix_conversation_members_user_id", "conversation_members", ["user_id"])

    op.add_column(
        "messages",
        sa.Column(
            "reply_to_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.alter_column("message_reads", "last_read_at", nullable=True)
    op.add_column(
        "message_reads", sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "message_reads",
        sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "message_reads", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {NEW_KINDS}")
    op.execute(
        "UPDATE notification_channels "
        "SET enabled_kinds = array_append(enabled_kinds, 'direct_message') "
        "WHERE NOT (enabled_kinds @> ARRAY['direct_message']::text[])"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE notification_channels "
        "SET enabled_kinds = array_remove(enabled_kinds, 'direct_message')"
    )
    op.execute("DELETE FROM notifications WHERE kind = 'direct_message'")
    op.drop_constraint("ck_notifications_kind", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_kind", "notifications", f"kind IN {OLD_KINDS}")

    op.drop_column("message_reads", "archived_at")
    op.drop_column("message_reads", "muted")
    op.drop_column("message_reads", "pinned_at")
    op.execute("DELETE FROM message_reads WHERE last_read_at IS NULL")
    op.alter_column("message_reads", "last_read_at", nullable=False)

    op.drop_column("messages", "reply_to_message_id")
    op.drop_table("conversation_members")

    # Chats have no anchor and cannot survive the old constraint.
    op.execute("DELETE FROM conversations WHERE kind IN ('direct', 'group')")
    op.drop_index("ix_conversations_last_message", table_name="conversations")
    op.drop_index("uq_conversations_direct", table_name="conversations")
    op.drop_constraint("ck_conversations_kind_anchor", "conversations", type_="check")
    op.create_check_constraint(
        "ck_conversations_one_anchor", "conversations", "num_nonnulls(task_id, project_id) = 1"
    )
    op.drop_column("conversations", "last_message_at")
    op.drop_column("conversations", "created_by_user_id")
    op.drop_column("conversations", "direct_key")
    op.drop_column("conversations", "title")
    op.drop_column("conversations", "kind")
