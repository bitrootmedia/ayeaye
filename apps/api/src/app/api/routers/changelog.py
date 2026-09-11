"""The organisation's changelog — what happened, when, and who wrote it down.

Thin, like every router here: the two bars (any member reads and adds,
whoever recorded it or an org admin edits) live in `services/changelog.py`.

**Paged, unlike the bookmark shelf next door.** A shelf is curated and stops
growing; a log only ever gets longer, so this is CLAUDE.md's "a list that can
grow is paged, and says what it is a page of" — with `/tasks`' own no-default
-limit rule, because a silent cap on a *history* is the worst place for one.
"""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models.changelog import MAX_DESCRIPTION_LENGTH
from app.schemas.structure import PersonOut
from app.services import changelog as changelog_service

router = APIRouter(prefix="/organisations/{org_id}", tags=["changelog"])


class ChangelogEntryIn(BaseModel):
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    #: Optional: left out, it's the caller's own today rather than the
    #: server's — see `services/changelog.py`.
    happened_on: date | None = None


class ChangelogEntryUpdate(BaseModel):
    description: str | None = None
    happened_on: date | None = None


class ChangelogEntryOut(BaseModel):
    id: str
    #: The date being recorded. Not `created_at`, which is when somebody
    #: typed it in — see models/changelog.py for why both exist.
    happened_on: date
    description: str
    added_by: PersonOut | None
    created_at: datetime
    updated_at: datetime
    #: Resolved server-side so the UI can omit a control rather than show one
    #: that 403s — the same reasoning `can_close` on a task follows.
    can_edit: bool


def _out(entry, author, *, can_edit: bool) -> ChangelogEntryOut:
    return ChangelogEntryOut(
        id=str(entry.id),
        happened_on=entry.happened_on,
        description=entry.description,
        added_by=(
            None
            if author is None
            else PersonOut(id=str(author.id), email=author.email, display_name=author.display_name)
        ),
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        can_edit=can_edit,
    )


def _editable(ctx, entry, user) -> bool:
    return changelog_service.can_edit(
        role=ctx.role, created_by_user_id=entry.created_by_user_id, user_id=user.id
    )


@router.get("/changelog", response_model=list[ChangelogEntryOut])
async def list_changelog(
    response: Response,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    limit: int | None = None,
    offset: int = 0,
    q: str = "",
):
    """The organisation's log, newest first, optionally narrowed by `q`.

    **No default limit**, the same call `/tasks` makes. Ask for a `limit` and
    the count of everything *matching* comes back in `X-Total-Count`, so a
    paging client always knows what it is a page *of*.

    `q` is the same matcher ⌘K uses (`search_service.matches`), not a second
    one written here — the palette links to this list carrying the query it
    matched on, and two different predicates would mean a hit that lands on a
    log not containing it. Server-side rather than client-side, unlike the
    Projects list's own name filter, for the ordinary reason: this list is a
    page, so filtering in the browser would only filter the page it happens
    to be holding.
    """
    rows, total = await changelog_service.list_page(db, ctx, limit=limit, offset=offset, q=q)
    response.headers["X-Total-Count"] = str(total)
    return [_out(e, author, can_edit=_editable(ctx, e, user)) for e, author in rows]


@router.post("/changelog", response_model=ChangelogEntryOut, status_code=status.HTTP_201_CREATED)
async def add_changelog_entry(
    body: ChangelogEntryIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Any member. A log only an admin may write to is a log that stays
    empty — and an incomplete history is worse than none, because people
    believe it."""
    entry = await changelog_service.create(
        db, ctx, user, description=body.description, happened_on=body.happened_on
    )
    return _out(entry, user, can_edit=True)


@router.patch("/changelog/{entry_id}", response_model=ChangelogEntryOut)
async def update_changelog_entry(
    entry_id: uuid.UUID,
    body: ChangelogEntryUpdate,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """Whoever recorded it, or an org admin. 403 rather than 404 for anybody
    else: every member can see the entry, so pretending it isn't there would
    be the wrong lie."""
    entry, author = await changelog_service.get_or_404(db, ctx, entry_id)
    entry = await changelog_service.update_one(
        db, ctx, entry, user, fields=body.model_dump(exclude_unset=True)
    )
    return _out(entry, author, can_edit=True)


@router.delete("/changelog/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_changelog_entry(
    entry_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    entry, _author = await changelog_service.get_or_404(db, ctx, entry_id)
    await changelog_service.remove(db, ctx, entry, user)
