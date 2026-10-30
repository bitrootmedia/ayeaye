"""Conversations: the comment thread on a task or a project, and chats.

    tasks    ──1:1──► conversations ──► messages
    projects ──1:1──┘   ▲            └─► message_reads  (one row per person)
    (no anchor) ────────┘  direct / group ──► conversation_members

**There is no separate comment system, and there must not be.** Trello-style
comments under a task *are* this thread, which is what makes attachments,
voice notes, realtime delivery and the unread badge one implementation instead
of two. See the note in CLAUDE.md.

A conversation is anchored to exactly one thing — a task **or** a project —
enforced by `CHECK (num_nonnulls(task_id, project_id) = 1)`. It has no access
rules of its own: **who can see a thread is who can see its anchor**. That is
one rule rather than two, and it means revoking access to a task revokes the
conversation with it, with nothing else to remember.

**Chats are the same table, with no anchor.** A `direct` conversation (two
people, or one: your own saved messages) or a `group` has nothing to inherit
access from, so `conversation_members` is its access rule — and the only one.
**An organisation admin is not a member of anybody's DM**: the admin route
that opens every task deliberately does not open these, the same promise a
private note makes. See `services/chats.py`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

KIND_TASK = "task"
KIND_PROJECT = "project"
KIND_DIRECT = "direct"
KIND_GROUP = "group"
CONVERSATION_KINDS = (KIND_TASK, KIND_PROJECT, KIND_DIRECT, KIND_GROUP)
# The kinds whose access is membership rather than an anchor.
CHAT_KINDS = (KIND_DIRECT, KIND_GROUP)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # The anchor follows the kind: a task thread has a task and nothing
        # else, a chat has neither. One CHECK so the two can never disagree.
        CheckConstraint(
            "(kind = 'task' AND task_id IS NOT NULL AND project_id IS NULL)"
            " OR (kind = 'project' AND project_id IS NOT NULL AND task_id IS NULL)"
            " OR (kind IN ('direct', 'group') AND task_id IS NULL AND project_id IS NULL)",
            name="ck_conversations_kind_anchor",
        ),
        # One thread per thing. Partial, because the other column is NULL on
        # every row and NULLs never collide.
        Index(
            "uq_conversations_task",
            "task_id",
            unique=True,
            postgresql_where=text("task_id IS NOT NULL"),
        ),
        Index(
            "uq_conversations_project",
            "project_id",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
        # One DM per pair of people per organisation. The key is the two user
        # ids sorted and joined, so "A to B" and "B to A" are the same row.
        Index(
            "uq_conversations_direct",
            "organisation_id",
            "direct_key",
            unique=True,
            postgresql_where=text("direct_key IS NOT NULL"),
        ),
        # The chat list orders by this.
        Index("ix_conversations_last_message", "organisation_id", "last_message_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False, server_default=KIND_TASK)
    # A group's name. A DM is named after the other person, at read time, so
    # a rename shows up without rewriting anything.
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    direct_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalised from `messages` so the chat list sorts without scanning
    # them. Stamped by `services/conversations.post`, the one writer.
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    """One comment.

    Deleting is soft: `deleted_at` is set and the body cleared. A hard delete
    would leave a hole in a conversation people have already read and replied
    to, and "this message was removed" is more honest than silence.
    """

    __tablename__ = "messages"
    __table_args__ = (
        # The thread query: one conversation, oldest first. UUIDv7 sorts by
        # time, so `id` is the chronological index for free.
        Index("ix_messages_conversation", "conversation_id", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL rather than CASCADE: deleting a person must not tear holes in a
    # discussion other people were part of. The message stays, unattributed.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    body: Mapped[str] = mapped_column(Text, nullable=False)

    # What acted on the author's behalf, if anything — the name of the
    # personal access token or the OAuth client that posted this
    # ("Claude"). NULL means a person typed it in the web app, which is the
    # overwhelming majority of rows and why this is nullable rather than
    # defaulted to something.
    #
    # **Attribution, not authorship.** `user_id` is still whose comment this
    # is: an assistant posts as the person whose credential it holds, and
    # that is the whole model here (see `app/mcp/server.py`'s one rule). This
    # column only says how the words arrived, which is what stops a thread
    # from reading as though somebody typed something they never wrote —
    # the gap the `[Claude]` prefix convention existed to paper over.
    via: Mapped[str | None] = mapped_column(String(80), nullable=True)

    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Telegram-style quoted reply. SET NULL: removing the original leaves the
    # reply standing, just no longer quoting anything.
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ConversationMember(Base):
    """Who is in a direct or group chat — **the whole of its access rule**.

    Only chats have rows here. A task thread's audience is whoever can see the
    task, and a member row there would be a second answer that could disagree.
    """

    __tablename__ = "conversation_members"
    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_conversation_members"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MessageRead(Base):
    """One person's place in one conversation: how far they've read, and how
    the thread sits in their chat list.

    **A row here is what puts a task or project thread in somebody's chat
    list** — written when they read it, post in it, or are given a stake in
    it (owner, action-required, named). It is display, never access: the list
    still filters every row through the anchor's visibility, so a thread you
    lost access to drops out however many rows point at it.

    A cursor per person, not a row per person per message. The badge only ever
    asks "how many since my cursor", and a join table of read receipts would be
    thousands of rows to answer a question nobody asked.

    The reference project had one cursor *per side* of a two-party chat, which
    meant two people sharing an account's view marked each other's messages
    read. Here a thread can have any number of participants, so the cursor is
    genuinely per person.
    """

    __tablename__ = "message_reads"
    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_message_reads"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The `created_at` of the newest message this person has seen. Set from the
    # message's own timestamp, never from now() — clock skew between the API
    # and the database could otherwise mark a message read before it arrived.
    # NULL is "nothing read yet": a stake-holder put in the list by somebody
    # else's message, before they've opened it.
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Muted: still listed and still counted on the chat itself, but no
    # notifications and no contribution to the total badge.
    muted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Out of the list until something newer than this arrives.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# What may be attached. A closed set, checked before a ticket is issued and
# again against what actually landed — a client that lies about the type in
# step 1 is caught in step 3.
ALLOWED_TYPES = (
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "text/plain",
    "text/csv",
    "video/mp4",
    "video/webm",
    "audio/webm",
    "audio/mp4",
    "audio/mpeg",
)

STATUS_PENDING = "pending"
STATUS_READY = "ready"


class Attachment(Base):
    """A file, uploaded straight from the browser to storage.

    **Anchored to a task, a conversation, OR an article revision**, enforced
    by `CHECK (num_nonnulls(task_id, conversation_id, article_revision_id) =
    1)`:

    * `task_id` — attached to the task directly (the Files panel's "Add").
    * `conversation_id` — posted in a comment. `message_id` is NULL while it is
      staged and set when the comment is sent.
    * `article_revision_id` — an inline image or standalone file on a
      knowledge-base article, scoped to the specific revision it was added
      during. See `services/articles.py` for why a revision, not the article.

    One table for both because **the Files panel shows both**. A file somebody
    dropped into a reply is exactly as much "a file on this task" as one added
    from the panel, and splitting them is how you end up hunting through a
    thread for the survey PDF. The panel marks which came from a comment.

    Three steps, and the row exists from the first one:

    1. `POST .../attachments` — access is checked, the declared type validated,
       a `pending` row written, and a presigned PUT returned.
    2. the browser PUTs the bytes to storage. **They never pass through the
       API**, which is the whole point: a phone video doesn't occupy a worker
       for two minutes.
    3. `POST .../attachments/{id}/confirm` — the API HEADs the object to learn
       what *really* landed, enforces the size limit against the real size, and
       flips the row to `ready`.

    `message_id` is nullable because the row exists **before** the comment: you
    attach, then send. Unsent `pending` rows are swept on the next upload in
    the same conversation — a client that never confirms leaves litter, not a
    visible attachment.
    """

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{STATUS_PENDING}', '{STATUS_READY}')",
            name="ck_attachments_status",
        ),
        CheckConstraint(
            "num_nonnulls(task_id, conversation_id, article_revision_id) = 1",
            name="ck_attachments_one_anchor",
        ),
        # A message only makes sense on a conversation-anchored row.
        CheckConstraint(
            "message_id IS NULL OR conversation_id IS NOT NULL",
            name="ck_attachments_message_needs_conversation",
        ),
        Index("ix_attachments_message", "message_id"),
        Index("ix_attachments_task", "task_id", "status"),
        # The sweep query, and "what's staged for me here".
        Index("ix_attachments_pending", "conversation_id", "status"),
        Index("ix_attachments_article_revision", "article_revision_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    # Exactly one of these three is set. See the CHECK above.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    article_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("article_revisions.id", ondelete="CASCADE"),
        nullable=True,
    )
    # NULL until the comment it belongs to is actually sent.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # The object key in the bucket. Not derived from the filename: two people
    # uploading "photo.jpg" must not collide, and a filename is attacker input.
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False, unique=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))

    # Set by a worker job after confirm, for images only. NULL means "no
    # thumbnail" — either it isn't an image, or the job hasn't run (or
    # couldn't), and the UI falls back to the full-size object. A gallery of
    # 12MP phone photos rendered at 80px is the reason this exists.
    thumbnail_key: Mapped[str | None] = mapped_column(String(400), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=STATUS_PENDING
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
