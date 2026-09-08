"""Bookmarks — the organisation's shared list of links.

Thin, like every router here: the three bars (member reads and adds, author
or admin edits, **owner alone pins**) live in `services/bookmarks.py`.

Two things about the route shapes are deliberate:

- **Pinning has its own route** rather than being a field on the `PATCH`,
  because it has a different rule from every other edit — the same reason
  `POST /tasks/{id}/closed` is its own route when only the owner may close.
  A `pinned` field on `BookmarkUpdate` would mean one endpoint answering
  403 for one field and 200 for another in the same request.
- **So does reordering**, for the mirror-image reason: it is a *lower* bar
  than editing the row, so folding it into the `PATCH` would either lock
  members out of tidying the list or let them rewrite a colleague's URL.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models.bookmark import MAX_DESCRIPTION_LENGTH, MAX_URL_LENGTH
from app.schemas.structure import PersonOut
from app.services import bookmarks as bookmarks_service

router = APIRouter(prefix="/organisations/{org_id}", tags=["bookmarks"])


class BookmarkIn(BaseModel):
    url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)


class BookmarkUpdate(BaseModel):
    url: str | None = None
    description: str | None = None


class BookmarkPinIn(BaseModel):
    pinned: bool


class BookmarkMoveIn(BaseModel):
    """`None` appends to the end — see `services/bookmarks.py::move`. The list
    screen always sends a real value (it knows the row's new neighbours and
    computes the midpoint itself); this is for anything that doesn't."""

    position: int | None = None


class BookmarkOut(BaseModel):
    id: str
    url: str
    description: str
    pinned: bool
    position: int
    added_by: PersonOut | None
    created_at: datetime
    updated_at: datetime
    #: Resolved server-side so the UI can omit a control rather than show one
    #: that 403s — the same reasoning `can_close` on a task follows. Pinning
    #: needs no equivalent field: it depends only on the caller's role, which
    #: the frontend already holds for every organisation it lists.
    can_edit: bool


def _out(bookmark, author, *, can_edit: bool) -> BookmarkOut:
    return BookmarkOut(
        id=str(bookmark.id),
        url=bookmark.url,
        description=bookmark.description,
        pinned=bookmark.pinned,
        position=bookmark.position,
        added_by=(
            None
            if author is None
            else PersonOut(id=str(author.id), email=author.email, display_name=author.display_name)
        ),
        created_at=bookmark.created_at,
        updated_at=bookmark.updated_at,
        can_edit=can_edit,
    )


def _editable(ctx, bookmark, user) -> bool:
    return bookmarks_service.can_edit(
        role=ctx.role, created_by_user_id=bookmark.created_by_user_id, user_id=user.id
    )


@router.get("/bookmarks", response_model=list[BookmarkOut])
async def list_bookmarks(ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """The organisation's list, pinned first then by position.

    Not paged, and no cap. A bookmark list is a curated shelf rather than a
    table that grows on its own, and a silently truncated one would hide the
    link somebody came here for — the same call `list_events` and the task
    board's own "no default limit" rule make.
    """
    rows = (await db.execute(bookmarks_service.list_stmt(org_id=ctx.organisation.id))).all()
    return [_out(b, author, can_edit=_editable(ctx, b, user)) for b, author in rows]


@router.post("/bookmarks", response_model=BookmarkOut, status_code=status.HTTP_201_CREATED)
async def add_bookmark(body: BookmarkIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Any member. A shared shelf nobody but an admin may add to is a shelf
    that stays empty."""
    bookmark = await bookmarks_service.create(
        db, ctx, user, url=body.url, description=body.description
    )
    return _out(bookmark, user, can_edit=True)


@router.patch("/bookmarks/{bookmark_id}", response_model=BookmarkOut)
async def update_bookmark(
    bookmark_id: uuid.UUID,
    body: BookmarkUpdate,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    bookmark, author = await bookmarks_service.get_or_404(db, ctx, bookmark_id)
    bookmark = await bookmarks_service.update_one(
        db, ctx, bookmark, user, fields=body.model_dump(exclude_unset=True)
    )
    return _out(bookmark, author, can_edit=True)


@router.post("/bookmarks/{bookmark_id}/pinned", response_model=BookmarkOut)
async def set_bookmark_pinned(
    bookmark_id: uuid.UUID,
    body: BookmarkPinIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """**Organisation owners only** — not admins. A pinned link is what every
    member of the organisation sees first.

    403 rather than 404 for anybody else: they can see the bookmark, so
    pretending it isn't there would be the wrong lie.
    """
    bookmark, author = await bookmarks_service.get_or_404(db, ctx, bookmark_id)
    bookmark = await bookmarks_service.set_pinned(db, ctx, bookmark, pinned=body.pinned)
    return _out(bookmark, author, can_edit=_editable(ctx, bookmark, user))


@router.post("/bookmarks/{bookmark_id}/position", response_model=BookmarkOut)
async def move_bookmark(
    bookmark_id: uuid.UUID,
    body: BookmarkMoveIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """Any member, unlike editing the row — tidying a shared list is not the
    same act as rewriting somebody else's link."""
    bookmark, author = await bookmarks_service.get_or_404(db, ctx, bookmark_id)
    bookmark = await bookmarks_service.move(db, ctx, bookmark, position=body.position)
    return _out(bookmark, author, can_edit=_editable(ctx, bookmark, user))


@router.delete("/bookmarks/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(
    bookmark_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    bookmark, _author = await bookmarks_service.get_or_404(db, ctx, bookmark_id)
    await bookmarks_service.remove(db, ctx, bookmark, user)
