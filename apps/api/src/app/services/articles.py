"""Articles, and every edit kept as history.

Three rules, and they follow from `models/knowledge_base.py`'s own
docstring:

1. **An article is born private, and only its owner may publish it.**
   `is_private` defaults to true; `set_private` is owner-only, the
   identical `can_hide` reasoning tasks already use — a book admin
   privatising someone else's article would be hiding it from themselves.

2. **A revision is a whole editing session, not a keystroke.** The latest
   revision (`id DESC LIMIT 1`) is mutable — every autosave in the same
   session updates it in place — until a *new* session starts, at which
   point it's frozen and a fresh row is seeded from it. That's what makes
   "attachments attach to a revision" buildable at all: the row exists
   before anyone types or pastes an image.

3. **Rendering never assumes an attachment belongs to the revision showing
   it.** A new session's body is copied forward from the old one, so an
   inline image reference can point at an attachment a different, older
   revision actually owns — `services/richtext.py::render()` already
   resolves by attachment id and tolerates one that no longer exists, so
   this needed no changes there.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Article, ArticleRevision, OrganisationMember, User
from app.models.organisation import STATUS_ACTIVE
from app.services import access, richtext
from app.services.books import BookContext
from app.services.organisations import OrgContext

# How long a revision stays "the same session" if the same person comes back
# to it — long enough that stepping away to find a screenshot doesn't start
# a needless new history entry, short enough that coming back tomorrow
# clearly reads as a new pass at the article.
SESSION_IDLE_WINDOW = timedelta(minutes=30)

MAX_TITLE_LENGTH = 300


@dataclass(frozen=True)
class ArticleContext:
    """An article plus the caller's resolved level on it."""

    article: Article
    level: str

    def require(self, allowed: bool, detail: str) -> None:
        if not allowed:
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=detail)


def can_make_private(*, is_owner: bool) -> bool:
    """The actual owner, and nobody else — not even a book admin. The
    identical `tasks_service.can_hide` reasoning: privatising someone
    else's article would hide it from the person doing the hiding."""
    return is_owner


async def _latest_revisions(
    db: AsyncSession, article_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ArticleRevision]:
    """The current (mutable-or-just-frozen) revision per article, one query
    regardless of how many articles — the same one-lookup discipline every
    list endpoint in this codebase follows once a page is involved, and the
    identical `ROW_NUMBER() OVER (PARTITION BY ...)` + `aliased(Entity, sub)`
    shape `access.board_stmt` already uses to bound each board column."""
    if not article_ids:
        return {}
    sub = (
        select(
            ArticleRevision,
            func.row_number()
            .over(partition_by=ArticleRevision.article_id, order_by=ArticleRevision.id.desc())
            .label("rn"),
        )
        .where(ArticleRevision.article_id.in_(article_ids))
        .subquery()
    )
    revision = aliased(ArticleRevision, sub)
    rows = (await db.execute(select(revision).where(sub.c.rn == 1))).scalars().all()
    return {r.article_id: r for r in rows}


async def latest_revision(db: AsyncSession, article_id: uuid.UUID) -> ArticleRevision | None:
    return (
        await db.execute(
            select(ArticleRevision)
            .where(ArticleRevision.article_id == article_id)
            .order_by(ArticleRevision.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def context_for(
    db: AsyncSession, ctx: OrgContext, article_id: uuid.UUID, user_id: uuid.UUID
) -> ArticleContext:
    """One article, or 404 — the same 404 whether it's missing, belongs to
    another organisation, isn't shared with you, or is someone else's
    private draft."""
    row = (
        await db.execute(
            access.visible_article_stmt(
                user_id=user_id,
                org_id=ctx.organisation.id,
                org_role=ctx.role,
                article_id=article_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="article not found")
    article, rank = row
    return ArticleContext(article=article, level=access.level_name(rank) or "")


async def list_for_book(
    db: AsyncSession, ctx: OrgContext, book_id: uuid.UUID, user_id: uuid.UUID
) -> list[tuple[Article, str, ArticleRevision | None]]:
    """The table of contents: every article in this book the caller can
    see, with its current title. A private article that isn't theirs
    simply never matches — the vanish-from-contents behaviour, achieved by
    the same access expression, not a second filter."""
    rows = (
        await db.execute(
            access.visible_articles_stmt(
                user_id=user_id, org_id=ctx.organisation.id, org_role=ctx.role, book_id=book_id
            )
        )
    ).all()
    articles = [a for a, _ in rows]
    latest = await _latest_revisions(db, [a.id for a in articles])
    return [(a, access.level_name(rank) or "", latest.get(a.id)) for a, rank in rows]


async def create(
    db: AsyncSession, bctx: BookContext, user: User, *, title: str = ""
) -> tuple[Article, ArticleRevision]:
    """A new article: born private, owned by its creator, with one empty
    revision to start editing from. Needs `write` on the book."""
    bctx.require(access.can_write(bctx.level), "you have read-only access to this book")
    article = Article(
        book_id=bctx.book.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        is_private=True,
    )
    db.add(article)
    await db.flush()
    revision = ArticleRevision(
        article_id=article.id,
        title=(title or "").strip()[:MAX_TITLE_LENGTH],
        body="",
        edited_by_user_id=user.id,
    )
    db.add(revision)
    await db.commit()
    await db.refresh(article)
    await db.refresh(revision)
    return article, revision


async def set_private(
    db: AsyncSession, actx: ArticleContext, user: User, *, is_private: bool
) -> Article:
    """Publish or un-publish. Owner-only — see `can_make_private`."""
    is_owner = actx.article.owner_user_id == user.id
    actx.require(can_make_private(is_owner=is_owner), "only the article's owner can change this")
    actx.article.is_private = is_private
    await db.commit()
    await db.refresh(actx.article)
    return actx.article


async def transfer_owner(
    db: AsyncSession, actx: ArticleContext, ctx: OrgContext, *, new_owner_id: uuid.UUID
) -> Article:
    """Hand the article to someone else. Owner or organisation admin only —
    `actx.level` already resolves to `owner` for either, the same
    `can_administer` check `books_service.transfer` uses. The caller may
    lose their own access by doing this (an article to someone else, on a
    book they don't otherwise have write on) — the same "don't re-resolve a
    level a successful commit just took away" caution `tasks_service.update`
    learned the hard way; callers of this function should tolerate a 404 on
    whatever they build from the response afterwards, not treat it as the
    transfer having failed.
    """
    actx.require(access.can_administer(actx.level), "only the article's owner can hand it over")
    member = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.user_id == new_owner_id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="that person is not a member of this organisation",
        )
    actx.article.owner_user_id = new_owner_id
    await db.commit()
    await db.refresh(actx.article)
    return actx.article


async def start_editing_session(
    db: AsyncSession, actx: ArticleContext, user: User
) -> ArticleRevision:
    """Resolve the mutable "current" revision, or start a fresh one.

    The latest revision stays mutable for whoever was last editing it, as
    long as they're the one reopening it within `SESSION_IDLE_WINDOW` —
    otherwise (someone else editing, or enough time passed that this reads
    as a new pass at the article) a new revision is seeded from it, and the
    old one freezes into history. Needs `write` on the article.
    """
    actx.require(access.can_write(actx.level), "you have read-only access to this article")
    current = await latest_revision(db, actx.article.id)
    if current is None:
        current = ArticleRevision(
            article_id=actx.article.id, title="", body="", edited_by_user_id=user.id
        )
        db.add(current)
        await db.commit()
        await db.refresh(current)
        return current

    now = datetime.now(UTC)
    still_open = (
        current.edited_by_user_id == user.id
        and current.updated_at is not None
        and (now - current.updated_at) < SESSION_IDLE_WINDOW
    )
    if still_open:
        return current

    fresh = ArticleRevision(
        article_id=actx.article.id,
        title=current.title,
        body=current.body,
        edited_by_user_id=user.id,
    )
    db.add(fresh)
    await db.commit()
    await db.refresh(fresh)
    return fresh


async def autosave_revision(
    db: AsyncSession, actx: ArticleContext, revision: ArticleRevision, *, title: str, body: str
) -> ArticleRevision:
    """Update the mutable revision in place. 409 if it's been superseded —
    the client is editing a stale copy, same "you're behind" signal a real
    conflict would eventually need."""
    actx.require(access.can_write(actx.level), "you have read-only access to this article")
    current = await latest_revision(db, actx.article.id)
    if current is None or current.id != revision.id:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="this revision is no longer the current one — reload and start a new session",
        )
    revision.title = (title or "").strip()[:MAX_TITLE_LENGTH]
    revision.body = richtext.sanitise(body) or ""
    await db.commit()
    await db.refresh(revision)
    return revision


async def list_revisions(
    db: AsyncSession, actx: ArticleContext
) -> list[tuple[ArticleRevision, User | None]]:
    """History, newest first."""
    rows = (
        await db.execute(
            select(ArticleRevision, User)
            .outerjoin(User, User.id == ArticleRevision.edited_by_user_id)
            .where(ArticleRevision.article_id == actx.article.id)
            .order_by(ArticleRevision.id.desc())
        )
    ).all()
    return [(r, u) for r, u in rows]


async def get_revision(
    db: AsyncSession, actx: ArticleContext, revision_id: uuid.UUID
) -> ArticleRevision:
    row = (
        await db.execute(
            select(ArticleRevision).where(
                ArticleRevision.id == revision_id, ArticleRevision.article_id == actx.article.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="revision not found")
    return row
