"""Wire shapes for the knowledge base: books, articles, revisions.

Grant/person/team shapes (`GrantIn`, `GrantOut`, `PersonOut`, `TransferIn`,
…) are reused directly from `app.schemas.structure` — a book's sharing
model is a project's, unchanged, so there's nothing book-specific about
those shapes to redeclare.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.structure import GrantOut, PersonOut


class BookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class BookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    archived: bool | None = None


class BookOut(BaseModel):
    id: str
    name: str
    description: str | None
    owner: PersonOut | None
    archived: bool
    created_at: datetime
    # The caller's resolved level: read | write | owner.
    access: str
    # How many articles the caller can see in it — 0 for a brand-new book,
    # and the honest answer for everyone else: their own private drafts
    # plus whatever's published, never a count that leaks what's private to
    # someone else.
    article_count: int = 0


class BookAccessOut(BaseModel):
    owner: PersonOut | None
    grants: list[GrantOut]
    organisation_admins: list[PersonOut]
    can_manage: bool


class ArticleCreate(BaseModel):
    title: str = Field(default="", max_length=300)


class ArticleOut(BaseModel):
    id: str
    book_id: str
    title: str
    owner: PersonOut | None
    is_private: bool
    # Whether the caller may toggle `is_private` — the owner, and nobody
    # else, the identical `can_hide` rule a task uses.
    can_make_private: bool
    created_at: datetime
    updated_at: datetime
    # The caller's resolved level: read | write | owner. Same field BookOut
    # already carries — without it the frontend has no way to decide whether
    # to render the editor or a read-only view.
    access: str


class ArticleSetPrivate(BaseModel):
    is_private: bool


class ArticleTransferIn(BaseModel):
    owner_user_id: str


class RevisionOut(BaseModel):
    id: str
    article_id: str
    title: str
    body: str
    edited_by: PersonOut | None
    created_at: datetime
    updated_at: datetime
    # Whether this is the mutable "current" revision — the one an autosave
    # can still land on. Every older row is history, read-only.
    is_current: bool


class RevisionSave(BaseModel):
    title: str = Field(default="", max_length=300)
    body: str = ""
    # "html" (the default) is what the browser editor always sends. A caller
    # that would rather write "**bold**" than build tags — a curl script, an
    # MCP client — sets this to "markdown" and the router runs `body` through
    # richtext.from_markdown() first. Never stored: it only decides how this
    # one request's `body` is read.
    body_format: Literal["html", "markdown"] = "html"


class ArticleFileOut(BaseModel):
    """One file on a revision. No `from_comment` flag — unlike a task, an
    article has no comment thread to post a file into."""

    id: str
    filename: str
    content_type: str
    size_bytes: int
    url: str
    thumbnail_url: str | None
    uploaded_by: PersonOut | None
    created_at: datetime
