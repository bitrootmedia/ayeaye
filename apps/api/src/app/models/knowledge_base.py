"""Knowledge base: books, articles, and every edit kept as history.

    organisation ──► books ──┬─► book_members   (user XOR team, like a project)
                              └─► articles ──► article_revisions

**A book is private to its owner until it is shared** — the identical rule
`models/structure.py` states for a project, and `BookMember` is a
byte-for-byte copy of `ProjectMember` for exactly that reason: they are the
same concept, just naming a different resource. See `services/access.py` for
the book-level functions and `services/books.py` for the service, both close
copies of their project counterparts.

**An article holds no content of its own.** `is_private` and ownership live
on `Article`; the title and body live on `ArticleRevision`, one row per
editing session, immutable once superseded. That split is what makes "keep
history of all edits" and "attachments attach to a revision" both true at
once — see `services/articles.py`'s own docstring for the session mechanics.

**`is_private` plays `Task.hidden_at`'s exact role**, not a new idea: it
short-circuits ahead of the whole book-access expression in
`effective_article_level`, defaults to true (a new article is born a private
draft), and only the article's own owner may clear it — the same `can_hide`
reasoning, restated: an admin privatising someone else's article would be
hiding it from themselves.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.structure import GRANT_LEVELS, LEVEL_READ


class Book(Base):
    """A book. Private to its owner until shared — see `models/structure.py`'s
    identical `Project` docstring."""

    __tablename__ = "books"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # RESTRICT, same reasoning as Project.owner_user_id: a book with no owner
    # is one nobody can administer, so removing that person has to reassign
    # first (see services/organisations.py's _reassign_everything_owned_by).
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Archived, never hard-deleted from the list — the identical Project
    # convention. A real DELETE stays available (services/books.py::delete)
    # for the owner who actually wants the history gone.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    grants: Mapped[list["BookMember"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )


class BookMember(Base):
    """One grant of access to one book, to a person **or** a team — the
    identical shape `ProjectMember` uses, reusing its `GRANT_LEVELS`."""

    __tablename__ = "book_members"
    __table_args__ = (
        CheckConstraint("num_nonnulls(user_id, team_id) = 1", name="ck_book_members_one_principal"),
        CheckConstraint(f"level IN {GRANT_LEVELS!r}", name="ck_book_members_level"),
        Index(
            "uq_book_members_user",
            "book_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_book_members_team",
            "book_id",
            "team_id",
            unique=True,
            postgresql_where=text("team_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )

    level: Mapped[str] = mapped_column(String(16), nullable=False, server_default=LEVEL_READ)

    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    book: Mapped[Book] = relationship(back_populates="grants")


class Article(Base):
    """Identity and metadata only — the content lives in `ArticleRevision`.
    See this module's own docstring for why the split exists."""

    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    # CASCADE: there is no loose article, unlike a task — deleting a book
    # deletes what's in it.
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # True on creation — a new article is always born a private draft.
    # Publishing is the owner clearing this, the only thing that makes it
    # visible per the book's own access grants. See services/articles.py.
    is_private: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    revisions: Mapped[list["ArticleRevision"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )


class ArticleRevision(Base):
    """One editing session's worth of content. Ordered by `id` — UUIDv7 sorts
    chronologically, the identical no-`position`-column convention checklists
    and sheets already use, since nothing here needs reordering.

    The **latest** revision (`id DESC LIMIT 1`) is the mutable one — every
    autosave in the same session updates this same row in place. It becomes
    immutable the instant a newer session's revision supersedes it. See
    `services/articles.py::start_editing_session` for exactly when that is.
    """

    __tablename__ = "article_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    # Sanitised HTML — identical contract to Task.description. See
    # services/richtext.py, reused verbatim, not reimplemented.
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Generated by Postgres, tags stripped — the identical
    # `Task.description_text` idiom, so search reads prose, not markup, with
    # no second write path to drift out of step.
    body_text: Mapped[str] = mapped_column(
        Text,
        Computed("regexp_replace(coalesce(body, ''), '<[^>]*>', ' ', 'g')", persisted=True),
        nullable=False,
    )

    # SET NULL, the same "don't tear a hole in shared content" reasoning
    # Message.user_id already uses — a revision is history now, and removing
    # the person who wrote it must not remove the record that it happened.
    edited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Bumped by every autosave within the session. `created_at` is what
    # "history, in order" sorts by; this is only ever read to show "last
    # touched" and to decide whether a session is still open.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    article: Mapped[Article] = relationship(back_populates="revisions")
