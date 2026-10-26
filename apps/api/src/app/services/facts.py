"""Facts: the short things worth knowing next time, filed in a book.

A gotcha and what it cost, a decision and its reason, what an incident turned
out to be. The thing a team otherwise keeps in somebody's head, a Slack
thread, or an agent's private memory — written here instead so the next
person, and the next person's assistant, finds it.

Three rules:

1. **A fact is read by whoever can read its book, and changed by whoever can
   write to it.** No owner, no private state, no route of its own — see
   `access.visible_facts_stmt`. Deleting is narrower: whoever wrote it, or
   whoever administers the book, because deleting is for the fact that was
   wrong and superseding is for the one that stopped being true.

2. **Readable the moment it is written.** There is no draft step, unlike an
   article — see `models/knowledge_base.py::Fact`.

3. **Superseding is the normal way out.** A superseded fact leaves recall and
   the book's list but stays reachable by id and in "show superseded", with a
   pointer to whatever replaced it. Knowledge rots, and the honest record of
   that is "this was true until then", not a hole.
"""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Fact, Tag, User
from app.models.knowledge_base import MAX_FACT_LENGTH
from app.services import access
from app.services import tags as tags_service
from app.services.books import BookContext
from app.services.organisations import OrgContext

# --- pure rules. no database, no request. -----------------------------------


def can_delete(
    *, level: str | None, created_by_user_id: uuid.UUID | None, user_id: uuid.UUID
) -> bool:
    """Rule 1's narrower half: whoever wrote it, or whoever administers the
    book. Writing it needed `write`, so the author still needs that today — a
    person whose access was cut back to `read` can't reach in and delete what
    they once wrote."""
    if access.can_administer(level):
        return True
    return (
        access.can_write(level)
        and created_by_user_id is not None
        and created_by_user_id == user_id
    )


def clean_body(raw: str | None) -> str:
    """A storable body, or a 422. Refused rather than truncated when too long,
    the changelog's own reasoning — half a fact says something else."""
    body = (raw or "").strip()
    if not body:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a fact needs a body"
        )
    if len(body) > MAX_FACT_LENGTH:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"that fact is too long (limit {MAX_FACT_LENGTH} characters) — "
                "something with steps belongs in an article"
            ),
        )
    return body


# --- reading -----------------------------------------------------------------


@dataclass(frozen=True)
class FactContext:
    """A fact plus the caller's level on its book."""

    fact: Fact
    level: str

    def require(self, allowed: bool, detail: str) -> None:
        if not allowed:
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=detail)


async def context_for(
    db: AsyncSession, ctx: OrgContext, fact_id: uuid.UUID, user_id: uuid.UUID
) -> FactContext:
    """One fact, or 404 — the same 404 whether it's missing, in another
    organisation, or in a book you can't see."""
    row = (
        await db.execute(
            access.visible_fact_stmt(
                user_id=user_id, org_id=ctx.organisation.id, org_role=ctx.role, fact_id=fact_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="fact not found")
    fact, rank = row
    return FactContext(fact=fact, level=access.level_name(rank) or "")


async def list_for_book(
    db: AsyncSession,
    ctx: OrgContext,
    book_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    include_superseded: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[tuple[Fact, str]], int]:
    """A page of one book's facts, newest first, and how many there are.

    Paged and counted for the changelog's reason: facts only accumulate, and
    "a list that can grow is paged, and says what it is a page of". No default
    limit, and bounds clamped rather than validated, as there.
    """
    stmt = access.visible_facts_stmt(
        user_id=user_id,
        org_id=ctx.organisation.id,
        org_role=ctx.role,
        book_id=book_id,
        include_superseded=include_superseded,
    )
    offset = max(0, offset)
    if limit is None:
        rows = (await db.execute(stmt.offset(offset))).all()
        facts = [(f, access.level_name(rank) or "") for f, rank in rows]
        return facts, offset + len(facts)
    total = (
        await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (await db.execute(stmt.limit(max(0, limit)).offset(offset))).all()
    return [(f, access.level_name(rank) or "") for f, rank in rows], int(total)


# --- writing -----------------------------------------------------------------


async def _tags(db: AsyncSession, ctx: OrgContext, user: User, names: list[str]) -> list[Tag]:
    """Resolve names to tags, creating any that don't exist yet — the
    vocabulary is open to every member, see `services/tags.py` rule 1.
    Duplicates and blanks dropped, so `["kb", "KB", ""]` is one tag."""
    seen: set[str] = set()
    tags: list[Tag] = []
    for name in names:
        key = " ".join((name or "").split()).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        tags.append(await tags_service.get_or_create(db, ctx, user, name=name))
    return tags


async def create(
    db: AsyncSession,
    ctx: OrgContext,
    bctx: BookContext,
    user: User,
    *,
    body: str,
    tags: list[str] | None = None,
    via: str | None = None,
) -> Fact:
    """Write one down. Needs `write` on the book.

    Tags are resolved *before* the fact is added: `get_or_create` commits on
    its own (it has to, to win a race for a new tag name), and a commit
    between adding the fact and tagging it would leave a window where the
    fact exists untagged. Resolving first means the fact and its taggings go
    in one transaction.
    """
    bctx.require(access.can_write(bctx.level), "you have read-only access to this book")
    clean = clean_body(body)
    resolved = await _tags(db, ctx, user, tags or [])
    fact = Fact(book_id=bctx.book.id, body=clean, created_by_user_id=user.id, via=via)
    db.add(fact)
    await db.flush()
    for tag in resolved:
        await tags_service.apply_to_fact(db, fact, tag, commit=False)
    await db.commit()
    await db.refresh(fact)
    return fact


async def update(db: AsyncSession, fctx: FactContext, *, body: str) -> Fact:
    """Correct the wording. `write` on the book — a fact is the book's, not
    its author's, the same way a wiki page is."""
    fctx.require(access.can_write(fctx.level), "you have read-only access to this book")
    fctx.fact.body = clean_body(body)
    await db.commit()
    # `updated_at` is `onupdate=func.now()`; read back, never assumed — the
    # MissingGreenlet trap `recurrence.attach()` documents.
    await db.refresh(fctx.fact)
    return fctx.fact


async def supersede(
    db: AsyncSession,
    ctx: OrgContext,
    fctx: FactContext,
    user: User,
    *,
    by_fact_id: uuid.UUID | None = None,
) -> Fact:
    """Take a fact out of recall because it stopped being true, optionally
    pointing at what replaced it.

    The replacement must be one the caller can see — through the same
    `context_for`, so naming a fact in a book you can't read is the same 404
    as naming one that doesn't exist, and a pointer never leads somebody to a
    fact they could not otherwise have known about. It may be in a different
    book: a decision recorded in "Decisions" can be superseded by one filed
    somewhere else, and both books' readers keep the half they could see.
    """
    fctx.require(access.can_write(fctx.level), "you have read-only access to this book")
    if by_fact_id is not None:
        if by_fact_id == fctx.fact.id:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="a fact can't be superseded by itself",
            )
        await context_for(db, ctx, by_fact_id, user.id)
    fctx.fact.superseded_at = func.now()
    fctx.fact.superseded_by_fact_id = by_fact_id
    await db.commit()
    await db.refresh(fctx.fact)
    return fctx.fact


async def restore(db: AsyncSession, fctx: FactContext) -> Fact:
    """Undo a supersede: it is true again, or it never stopped being."""
    fctx.require(access.can_write(fctx.level), "you have read-only access to this book")
    fctx.fact.superseded_at = None
    fctx.fact.superseded_by_fact_id = None
    await db.commit()
    await db.refresh(fctx.fact)
    return fctx.fact


async def remove(db: AsyncSession, fctx: FactContext, user: User) -> None:
    """Delete outright — for the fact that was simply wrong. See `can_delete`."""
    fctx.require(
        can_delete(
            level=fctx.level, created_by_user_id=fctx.fact.created_by_user_id, user_id=user.id
        ),
        "only whoever wrote this fact, or the book's owner, can delete it — "
        "supersede it instead if it has stopped being true",
    )
    await db.delete(fctx.fact)
    await db.commit()


async def tag(db: AsyncSession, ctx: OrgContext, fctx: FactContext, user: User, name: str) -> Tag:
    fctx.require(access.can_write(fctx.level), "you have read-only access to this book")
    found = await tags_service.get_or_create(db, ctx, user, name=name)
    await tags_service.apply_to_fact(db, fctx.fact, found)
    return found


async def untag(db: AsyncSession, fctx: FactContext, tag_id: uuid.UUID) -> None:
    fctx.require(access.can_write(fctx.level), "you have read-only access to this book")
    await tags_service.unapply_from_fact(db, fctx.fact, tag_id)


__all__ = [
    "FactContext",
    "can_delete",
    "clean_body",
    "context_for",
    "create",
    "list_for_book",
    "remove",
    "restore",
    "supersede",
    "tag",
    "untag",
    "update",
]
