"""The organisation's changelog — a dated log of things that happened.

"BingAds version lift, the 3rd." Three fields and no more: the date it
happened, what happened, and who wrote it down.

**Two bars, and they are the bookmark shelf's first two exactly — the third
one is deliberately absent.**

1. **Reading and adding is ordinary membership.** No grants and no per-row
   visibility: this is the organisation's own record of itself, so
   `CurrentOrg` is the whole check and `list_stmt` carries no access
   expression at all. The same shape `services/bookmarks.py` documents, and
   for the same reason — a log only an admin may write to is a log that
   stays empty, and an incomplete log is worse than no log because people
   believe it.
2. **Editing and deleting is whoever recorded it, or an org admin.** The
   ordinary shape everywhere else in this codebase: your own thing, plus the
   admin escape hatch that keeps a self-hosted product operable. 403 rather
   than 404 for anybody else — every member can see the entry, so pretending
   it isn't there would be the wrong lie.
3. **There is no pinning, no reordering, and no third bar.** A bookmark
   shelf needs an order because it hasn't got one; a log's order is its
   dates. Letting somebody drag an entry above one that happened after it
   would let the list lie about the sequence, which is the one thing a
   changelog is for.

**Paged, unlike bookmarks — and that is the difference between a shelf and a
log.** A bookmark list is curated and stops growing; a changelog is
append-only by nature and only ever gets longer, which is exactly CLAUDE.md's
"a list that can grow is paged, and says what it is a page of". Ask for a
`limit` and the count of everything comes back in `X-Total-Count`. There is
**no default limit**, the same call `/tasks` makes: a silent cap is worse
than a big response, because the caller believes they have everything.

**`happened_on` defaults to the caller's own today, never the server's.** A
date has no timezone (see `services/reminders.py`, whose `today_for` this
reuses rather than re-deriving), so anyone west of London recording something
in the evening would otherwise have it filed under tomorrow.

**The description is plain text and stays plain text.** Nothing renders it
with `dangerouslySetInnerHTML`, so unlike a task description there is nothing
to sanitise — the same safe-by-construction position Sparks holds. Storing
HTML here would create a trust boundary this feature hasn't got.
"""

import uuid
from datetime import date

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChangelogEntry, User
from app.models.changelog import MAX_DESCRIPTION_LENGTH
from app.services import search as search_service
from app.services.organisations import OrgContext, can_manage_members
from app.services.reminders import today_for

# --- pure rules. no database, no request. -----------------------------------


def can_edit(*, role: str, created_by_user_id: uuid.UUID | None, user_id: uuid.UUID) -> bool:
    """Rule 2. Whoever recorded it, or an org admin.

    `created_by_user_id` is nullable (SET NULL, see the model), so an entry
    whose author has since been removed from the installation is editable by
    admins alone — which is the right answer: there is nobody left it belongs
    to. A NULL author must never compare equal to the caller.
    """
    return can_manage_members(role) or (
        created_by_user_id is not None and created_by_user_id == user_id
    )


def clean_description(raw: str | None) -> str:
    """A storable description, or a 422.

    **Refused rather than truncated** when it's too long, the same call
    `bookmarks.normalise_url` makes for a URL: an entry silently cut in half
    says something other than what was written, and a changelog people can't
    trust literally is not one.
    """
    description = (raw or "").strip()
    if not description:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a changelog entry needs a description",
        )
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"that description is too long (limit {MAX_DESCRIPTION_LENGTH} characters)",
        )
    return description


# --- the list ---------------------------------------------------------------


def list_stmt(*, org_id: uuid.UUID, q: str = "") -> Select:
    """One organisation's log, newest first, optionally narrowed by text.

    **The filter is `search_service.matches`, not a second ILIKE written
    here**, and that is what makes a ⌘K result and the screen it links to
    agree by construction: the palette navigates to this list carrying the
    same query, so if the two matched differently a hit would land on a log
    that doesn't contain it. Typo tolerance comes along for free, and the
    caller has to have run `search_service.apply_threshold` first for the
    `%>` half to use the threshold this product chose rather than Postgres'
    own.

    `happened_on` descending is the order the log is *about*; `id`
    descending is the tie-break, so several entries filed under the same date
    come back most-recently-recorded first rather than swapping around
    between requests — UUIDv7 makes that free.

    The join to `User` is an **outer** join and has to stay one: an entry
    whose author has since been removed from the installation has a NULL
    `created_by_user_id` (SET NULL, see the model), and an inner join would
    silently drop that row — quietly editing the organisation's own history,
    which is the one thing this table exists not to do.
    """
    return (
        select(ChangelogEntry, User)
        .outerjoin(User, User.id == ChangelogEntry.created_by_user_id)
        .where(
            ChangelogEntry.organisation_id == org_id,
            *([search_service.matches(ChangelogEntry.description, q)] if q else []),
        )
        .order_by(ChangelogEntry.happened_on.desc(), ChangelogEntry.id.desc())
    )


async def list_page(
    db: AsyncSession, ctx: OrgContext, *, limit: int | None, offset: int, q: str = ""
) -> tuple[list[tuple[ChangelogEntry, User | None]], int]:
    """A page of the log, and what it is a page *of*.

    `limit=None` returns everything and counts what it returned — no second
    query for a total that is already known.

    Both bounds are clamped rather than validated: these come off a URL
    people edit and share, and Postgres refuses a negative `LIMIT` or
    `OFFSET` outright — which would surface as a 500 on a link somebody
    mistyped. The same reasoning as "an unknown sort key is ignored, not
    rejected".
    """
    q = search_service.normalise(q)
    if q:
        # Before any statement that uses `%>` — see `apply_threshold`.
        await search_service.apply_threshold(db)
    stmt = list_stmt(org_id=ctx.organisation.id, q=q)
    offset = max(0, offset)
    if limit is not None:
        limit = max(0, limit)
    if limit is None:
        rows = (await db.execute(stmt)).all()
        return [(entry, author) for entry, author in rows], len(rows)
    # Counted through the same predicate, or "Showing 5 of 312" would be
    # counting the whole log while showing a filtered page of it.
    total = (
        await db.execute(
            select(func.count())
            .select_from(ChangelogEntry)
            .where(
                ChangelogEntry.organisation_id == ctx.organisation.id,
                *([search_service.matches(ChangelogEntry.description, q)] if q else []),
            )
        )
    ).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).all()
    return [(entry, author) for entry, author in rows], int(total)


async def create(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    *,
    description: str,
    happened_on: date | None,
) -> ChangelogEntry:
    """Record one. Any member — see rule 1."""
    entry = ChangelogEntry(
        organisation_id=ctx.organisation.id,
        created_by_user_id=user.id,
        # Their today, not the server's. See the module docstring.
        happened_on=happened_on or today_for(user),
        description=clean_description(description),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def get_or_404(
    db: AsyncSession, ctx: OrgContext, entry_id: uuid.UUID
) -> tuple[ChangelogEntry, User | None]:
    """In *this* organisation, or it doesn't exist.

    Scoped to `ctx.organisation.id` for the reason
    `personal_notes.get_or_404` gives: without it, an entry could be edited
    or deleted through a different organisation's URL by somebody who happens
    to belong to both.
    """
    row = (
        await db.execute(
            select(ChangelogEntry, User)
            .outerjoin(User, User.id == ChangelogEntry.created_by_user_id)
            .where(
                ChangelogEntry.id == entry_id,
                ChangelogEntry.organisation_id == ctx.organisation.id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="changelog entry not found"
        )
    entry, author = row
    return entry, author


async def update_one(
    db: AsyncSession,
    ctx: OrgContext,
    entry: ChangelogEntry,
    user: User,
    *,
    fields: dict,
) -> ChangelogEntry:
    """Correct the date or the wording. Whoever recorded it, or an org admin.

    A correction is an ordinary edit with no trail of its own, unlike a task's
    (`task_revisions`): a changelog entry is a few words somebody typed, not
    content a colleague may have been contributing to and can lose.
    """
    ctx.require(
        can_edit(role=ctx.role, created_by_user_id=entry.created_by_user_id, user_id=user.id),
        "only whoever recorded this entry, or an organisation admin, can change it",
    )
    if "description" in fields:
        entry.description = clean_description(fields["description"])
    if "happened_on" in fields and fields["happened_on"] is not None:
        entry.happened_on = fields["happened_on"]
    await db.commit()
    # Refreshed, not assumed: `updated_at` carries `onupdate=func.now()`, and
    # reading it back off a committed-but-not-refreshed row is the
    # `MissingGreenlet` trap `recurrence.attach()` documents.
    await db.refresh(entry)
    return entry


async def remove(db: AsyncSession, ctx: OrgContext, entry: ChangelogEntry, user: User) -> None:
    """Same bar as editing: whoever recorded it, or an org admin."""
    ctx.require(
        can_edit(role=ctx.role, created_by_user_id=entry.created_by_user_id, user_id=user.id),
        "only whoever recorded this entry, or an organisation admin, can remove it",
    )
    await db.delete(entry)
    await db.commit()


__all__ = [
    "can_edit",
    "clean_description",
    "create",
    "get_or_404",
    "list_page",
    "list_stmt",
    "remove",
    "update_one",
]
