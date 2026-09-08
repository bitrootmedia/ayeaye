"""The organisation's bookmark list.

Three bars, deliberately different from each other, and the third is the one
worth remembering:

1. **Reading and adding is ordinary membership.** No grants, no per-row
   visibility — a bookmark is the organisation's shared shelf, so `CurrentOrg`
   is the whole check and the list is one statement with no access expression
   in it at all. This is the only organisation-scoped resource in the product
   with nothing finer than membership to resolve, which is why `list_stmt`
   looks too simple next to `access.visible_tasks_stmt` and is nonetheless
   right.
2. **Editing and deleting is whoever added it, or an org admin.** The
   ordinary shape everywhere else in this codebase: your own thing, plus the
   admin escape hatch that keeps a self-hosted product operable. Somebody
   else's bookmark is not yours to rewrite; it is an admin's to remove.
3. **Pinning is the organisation's `owner`, and nobody else — not an admin.**
   A pinned link is what the whole organisation sees first, and that was
   asked for as an owner's call. Note the direction: this is *narrower* than
   admin, not wider, so it cannot be expressed by reusing
   `can_manage_members` — `organisations.can_delete_organisation` is the
   existing precedent for an owner-only capability and `can_pin` is its
   sibling, kept here rather than there because it is a rule about bookmarks
   rather than about membership.

**Reordering is member-level, unlike editing.** Moving somebody else's
bookmark up the list is what tidying a shared list means, and it changes
nothing about the bookmark itself. Pinning is untouched by it: a pinned row
sorts ahead of every unpinned one whatever its position, so no member can
drag a link past a pinned one.

**Nothing here renumbers a list.** `position` is a plain integer and the
client computes the midpoint of a row's new neighbours — the identical
no-resequencing convention `Task.position` and `planner_entries.position`
already use, with the same "append to the end" fallback
`planner.place` documents for a caller that can't see the neighbours.

**A URL is normalised before it is stored, and that is a security boundary,
not tidiness.** The list renders each row as a real `<a href>`, so a stored
`javascript:` URL is stored XSS — waiting for the next colleague to click
it. `normalise_url` refuses every scheme but http and https, and supplies
`https://` when somebody types a bare hostname (without it, `example.com`
in an href is a *relative* link and navigates inside the app).
"""

import re
import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bookmark, User
from app.models.bookmark import MAX_DESCRIPTION_LENGTH, MAX_URL_LENGTH
from app.models.organisation import ROLE_OWNER
from app.services.organisations import OrgContext, can_manage_members

# --- pure rules. no database, no request. -----------------------------------

# **Not just `^\w+:`, and the two extra conditions are both real inputs.**
# RFC 3986 allows `.` and digits in a scheme, so a naive scheme pattern reads
# `example.com:8080/admin` as the scheme "example.com" and `localhost:3000` as
# "localhost" — both then get refused as "not http", when both are ordinary
# things to paste into a bookmark field. A real scheme has no dot in it and is
# not followed by a port number, so `_scheme_of` requires both before it
# believes it has found one.
_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):(\d*)")
_ALLOWED_SCHEMES = ("http", "https")


def _scheme_of(url: str) -> str | None:
    """The URL's scheme, lowercased, or None if it hasn't got one."""
    match = _SCHEME.match(url)
    if match is None:
        return None
    scheme, digits_after_colon = match.group(1), match.group(2)
    # `host:port`, not `scheme:`. Either signal on its own is enough to be
    # wrong: "example.com" has the dot, "localhost:3000" has the port.
    if digits_after_colon or "." in scheme:
        return None
    return scheme.lower()


def can_pin(role: str) -> bool:
    """Rule 3. Owners only — an admin cannot pin.

    The one place this module is stricter than "an org admin can do
    anything", because pinning decides what every member of the organisation
    sees first.
    """
    return role == ROLE_OWNER


def can_edit(*, role: str, created_by_user_id: uuid.UUID | None, user_id: uuid.UUID) -> bool:
    """Rule 2. Whoever added it, or an org admin.

    `created_by_user_id` is nullable (SET NULL, see the model), so a bookmark
    whose author has since been removed is editable by admins alone — which
    is the right answer: there is nobody left it belongs to.
    """
    return can_manage_members(role) or (
        created_by_user_id is not None and created_by_user_id == user_id
    )


def normalise_url(raw: str) -> str:
    """A storable http(s) URL, or a 422.

    Not validation for its own sake: whatever comes back from here is put
    straight into an `href`, so a `javascript:` or `data:` scheme surviving
    this function is stored XSS. Refuse the scheme rather than try to
    sanitise it — the same allow-list-not-block-list reasoning
    `services/richtext.py` applies to markup.
    """
    url = (raw or "").strip()
    if not url:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a bookmark needs a URL"
        )
    scheme = _scheme_of(url)
    if scheme is None:
        # A bare hostname. Without a scheme this is a *relative* href and
        # navigates inside the app instead of out to the site.
        url = f"https://{url}"
    elif scheme not in _ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a bookmark must be an http or https URL",
        )
    if len(url) > MAX_URL_LENGTH:
        # Truncating a URL produces a link that goes somewhere else, which is
        # worse than refusing it.
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="that URL is too long"
        )
    return url


# --- the list ---------------------------------------------------------------


def list_stmt(*, org_id: uuid.UUID) -> Select:
    """One organisation's bookmarks: pinned first, then by position.

    `id` last as the tie-break, so two rows sharing a position (a double
    submit, or two clients computing the same midpoint) still come back in a
    stable order rather than swapping around between requests — UUIDv7 makes
    that oldest-first for free.

    The join to `User` is an **outer** join and has to stay one: a bookmark
    whose author has since been removed from the installation has a NULL
    `created_by_user_id` (SET NULL, see the model), and an inner join would
    silently drop that row out of the organisation's list.
    """
    return (
        select(Bookmark, User)
        .outerjoin(User, User.id == Bookmark.created_by_user_id)
        .where(Bookmark.organisation_id == org_id)
        .order_by(Bookmark.pinned.desc(), Bookmark.position, Bookmark.id)
    )


async def create(
    db: AsyncSession, ctx: OrgContext, user: User, *, url: str, description: str
) -> Bookmark:
    """Add one to the end of the unpinned list.

    Appended server-side rather than positioned by the client, for
    `planner.place`'s own reason: a form that has just been typed into knows
    nothing about the list's existing neighbours, and fetching them all to
    place one row would be a strange trade.
    """
    position = (
        await db.execute(
            select(func.coalesce(func.max(Bookmark.position), 0) + 1000).where(
                Bookmark.organisation_id == ctx.organisation.id
            )
        )
    ).scalar_one()
    bookmark = Bookmark(
        organisation_id=ctx.organisation.id,
        created_by_user_id=user.id,
        url=normalise_url(url),
        description=(description or "").strip()[:MAX_DESCRIPTION_LENGTH],
        position=position,
    )
    db.add(bookmark)
    await db.commit()
    await db.refresh(bookmark)
    return bookmark


async def get_or_404(
    db: AsyncSession, ctx: OrgContext, bookmark_id: uuid.UUID
) -> tuple[Bookmark, User | None]:
    """In *this* organisation, or it doesn't exist.

    Scoped to `ctx.organisation.id` for the reason
    `personal_notes.get_or_404` gives: without it, a bookmark could be edited
    or deleted through a different organisation's URL by somebody who happens
    to belong to both.
    """
    row = (
        await db.execute(
            select(Bookmark, User)
            .outerjoin(User, User.id == Bookmark.created_by_user_id)
            .where(Bookmark.id == bookmark_id, Bookmark.organisation_id == ctx.organisation.id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="bookmark not found")
    bookmark, author = row
    return bookmark, author


async def update_one(
    db: AsyncSession, ctx: OrgContext, bookmark: Bookmark, user: User, *, fields: dict
) -> Bookmark:
    """Change the URL or the description. Whoever added it, or an org admin.

    403, not 404: the caller can see this bookmark — every member can — so
    pretending it isn't there would be the wrong lie, the same distinction
    `tasks_service.set_open` draws for closing somebody else's task.
    """
    ctx.require(
        can_edit(role=ctx.role, created_by_user_id=bookmark.created_by_user_id, user_id=user.id),
        "only whoever added this bookmark, or an organisation admin, can change it",
    )
    if "url" in fields:
        bookmark.url = normalise_url(fields["url"])
    if "description" in fields:
        bookmark.description = (fields["description"] or "").strip()[:MAX_DESCRIPTION_LENGTH]
    await db.commit()
    # Refreshed, not assumed: `updated_at` carries `onupdate=func.now()`,
    # and reading it back off a committed-but-not-refreshed row is the
    # `MissingGreenlet` trap `recurrence.attach()` documents.
    await db.refresh(bookmark)
    return bookmark


async def set_pinned(
    db: AsyncSession, ctx: OrgContext, bookmark: Bookmark, *, pinned: bool
) -> Bookmark:
    """Rule 3, and its own route for exactly that reason — a different bar
    from every other edit, the same way `POST /tasks/{id}/closed` is its own
    route because only the owner closes."""
    ctx.require(can_pin(ctx.role), "only an organisation owner can pin a bookmark")
    bookmark.pinned = pinned
    await db.commit()
    # Refreshed, not assumed: `updated_at` carries `onupdate=func.now()`,
    # and reading it back off a committed-but-not-refreshed row is the
    # `MissingGreenlet` trap `recurrence.attach()` documents.
    await db.refresh(bookmark)
    return bookmark


async def move(
    db: AsyncSession, ctx: OrgContext, bookmark: Bookmark, *, position: int | None
) -> Bookmark:
    """Reorder. Any member — see the module docstring for why this is a lower
    bar than editing the same row.

    `position=None` appends, for a caller that can't see the neighbours.
    """
    if position is None:
        position = (
            await db.execute(
                select(func.coalesce(func.max(Bookmark.position), 0) + 1000).where(
                    Bookmark.organisation_id == ctx.organisation.id
                )
            )
        ).scalar_one()
    bookmark.position = position
    await db.commit()
    # Refreshed, not assumed: `updated_at` carries `onupdate=func.now()`,
    # and reading it back off a committed-but-not-refreshed row is the
    # `MissingGreenlet` trap `recurrence.attach()` documents.
    await db.refresh(bookmark)
    return bookmark


async def remove(db: AsyncSession, ctx: OrgContext, bookmark: Bookmark, user: User) -> None:
    """Same bar as editing: whoever added it, or an org admin."""
    ctx.require(
        can_edit(role=ctx.role, created_by_user_id=bookmark.created_by_user_id, user_id=user.id),
        "only whoever added this bookmark, or an organisation admin, can remove it",
    )
    await db.delete(bookmark)
    await db.commit()


__all__ = [
    "can_edit",
    "can_pin",
    "create",
    "get_or_404",
    "list_stmt",
    "move",
    "normalise_url",
    "remove",
    "set_pinned",
    "update_one",
]
