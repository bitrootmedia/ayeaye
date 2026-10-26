"""Facts, tags on knowledge, and recall.

The knowledge base's second half: books already held articles — documents
somebody shapes — and now hold facts, the few sentences somebody (or their
assistant) writes down mid-task so the next person finds them. `recall` is
the question asked across all of it plus the tasks.

Thin, like every router: the rules live in `services/facts.py`,
`services/tags.py` and `services/recall.py`. Under the same
`/organisations/{org_id}/kb` prefix as books and articles; its own module
only so `knowledge_base.py` doesn't keep growing.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models import Fact, Tag, User
from app.models.knowledge_base import MAX_FACT_LENGTH
from app.schemas.structure import PersonOut
from app.schemas.tasks import TagIn, TagOut
from app.services import access as access_service
from app.services import articles as articles_service
from app.services import books as books_service
from app.services import facts as facts_service
from app.services import recall as recall_service
from app.services import tags as tags_service
from app.tasks.embeddings import sweep_embeddings

router = APIRouter(prefix="/organisations/{org_id}/kb", tags=["recall"])


class FactIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_FACT_LENGTH)
    tags: list[str] = Field(default_factory=list, max_length=20)


class FactUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_FACT_LENGTH)


class SupersedeIn(BaseModel):
    #: What replaced it, if anything did. Must be a fact the caller can see.
    by_fact_id: str | None = None


class FactOut(BaseModel):
    id: str
    book_id: str
    body: str
    tags: list[TagOut]
    written_by: PersonOut | None
    #: The token or OAuth client it arrived through — "via Claude" — or null
    #: when a person typed it.
    via: str | None
    superseded_at: datetime | None
    superseded_by_fact_id: str | None
    created_at: datetime
    updated_at: datetime
    #: Resolved server-side so the UI omits a control rather than showing one
    #: that 403s.
    can_edit: bool
    can_delete: bool


def _person(user: User | None) -> PersonOut | None:
    if user is None:
        return None
    return PersonOut(id=str(user.id), email=user.email, display_name=user.display_name)


def _tag_out(tag: Tag) -> TagOut:
    return TagOut(id=str(tag.id), name=tag.name, off_board=tag.off_board)


async def _facts_out(
    db: DbSession, rows: list[tuple[Fact, str]], user: User
) -> list[FactOut]:
    """A page of facts, with their tags and authors in one query each."""
    facts = [f for f, _ in rows]
    tags = await tags_service.for_facts(db, [f.id for f in facts])
    author_ids = {f.created_by_user_id for f in facts if f.created_by_user_id}
    authors = {}
    if author_ids:
        authors = {
            u.id: u
            for u in (await db.execute(select(User).where(User.id.in_(author_ids)))).scalars()
        }
    return [
        FactOut(
            id=str(f.id),
            book_id=str(f.book_id),
            body=f.body,
            tags=[_tag_out(t) for t in tags.get(f.id, [])],
            written_by=_person(authors.get(f.created_by_user_id)),
            via=f.via,
            superseded_at=f.superseded_at,
            superseded_by_fact_id=str(f.superseded_by_fact_id) if f.superseded_by_fact_id else None,
            created_at=f.created_at,
            updated_at=f.updated_at,
            can_edit=access_service.can_write(level),
            can_delete=facts_service.can_delete(
                level=level, created_by_user_id=f.created_by_user_id, user_id=user.id
            ),
        )
        for f, level in rows
    ]


async def _one(db: DbSession, fctx: facts_service.FactContext, user: User) -> FactOut:
    [out] = await _facts_out(db, [(fctx.fact, fctx.level)], user)
    return out


async def _kick() -> None:
    """Embed it now rather than within the minute. Best effort: if the queue
    is unreachable the scheduled sweep still gets there."""
    try:
        await sweep_embeddings.kiq()
    except Exception:  # noqa: BLE001 — a fact is written either way
        pass


# --- facts --------------------------------------------------------------------


@router.get("/books/{book_id}/facts", response_model=list[FactOut])
async def list_facts(
    book_id: uuid.UUID,
    response: Response,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    include_superseded: bool = False,
    limit: int | None = None,
    offset: int = 0,
):
    """Newest first. No default limit; ask for one and `X-Total-Count` says
    what the page is a page of — the changelog's shape, for the same reason."""
    await books_service.context_for(db, ctx, book_id, user.id)
    rows, total = await facts_service.list_for_book(
        db,
        ctx,
        book_id,
        user.id,
        include_superseded=include_superseded,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return await _facts_out(db, rows, user)


@router.post(
    "/books/{book_id}/facts", response_model=FactOut, status_code=status.HTTP_201_CREATED
)
async def create_fact(
    book_id: uuid.UUID, body: FactIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """`write` on the book. Readable by the book's readers at once — no draft."""
    bctx = await books_service.context_for(db, ctx, book_id, user.id)
    fact = await facts_service.create(db, ctx, bctx, user, body=body.body, tags=body.tags)
    await _kick()
    return await _one(db, facts_service.FactContext(fact=fact, level=bctx.level), user)


@router.get("/facts/{fact_id}", response_model=FactOut)
async def get_fact(fact_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    fctx = await facts_service.context_for(db, ctx, fact_id, user.id)
    return await _one(db, fctx, user)


@router.patch("/facts/{fact_id}", response_model=FactOut)
async def update_fact(
    fact_id: uuid.UUID, body: FactUpdate, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    fctx = await facts_service.context_for(db, ctx, fact_id, user.id)
    await facts_service.update(db, fctx, body=body.body)
    return await _one(db, fctx, user)


@router.post("/facts/{fact_id}/supersede", response_model=FactOut)
async def supersede_fact(
    fact_id: uuid.UUID, body: SupersedeIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """It stopped being true. Leaves recall; stays in history."""
    fctx = await facts_service.context_for(db, ctx, fact_id, user.id)
    by = None
    if body.by_fact_id:
        try:
            by = uuid.UUID(body.by_fact_id)
        except ValueError:
            # A malformed id is the same "no such fact" a real one you can't
            # see is — see `facts.supersede`.
            by = uuid.UUID(int=0)
    await facts_service.supersede(db, ctx, fctx, user, by_fact_id=by)
    return await _one(db, fctx, user)


@router.post("/facts/{fact_id}/restore", response_model=FactOut)
async def restore_fact(fact_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    fctx = await facts_service.context_for(db, ctx, fact_id, user.id)
    await facts_service.restore(db, fctx)
    return await _one(db, fctx, user)


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(fact_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    fctx = await facts_service.context_for(db, ctx, fact_id, user.id)
    await facts_service.remove(db, fctx, user)


@router.post("/facts/{fact_id}/tags", response_model=FactOut)
async def tag_fact(
    fact_id: uuid.UUID, body: TagIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    fctx = await facts_service.context_for(db, ctx, fact_id, user.id)
    await facts_service.tag(db, ctx, fctx, user, body.name)
    return await _one(db, fctx, user)


@router.delete("/facts/{fact_id}/tags/{tag_id}", response_model=FactOut)
async def untag_fact(
    fact_id: uuid.UUID, tag_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    fctx = await facts_service.context_for(db, ctx, fact_id, user.id)
    await facts_service.untag(db, fctx, tag_id)
    return await _one(db, fctx, user)


# --- tags on articles -----------------------------------------------------------


@router.get("/articles/{article_id}/tags", response_model=list[TagOut])
async def article_tags(article_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    actx = await articles_service.context_for(db, ctx, article_id, user.id)
    tags = await tags_service.for_articles(db, [actx.article.id])
    return [_tag_out(t) for t in tags.get(actx.article.id, [])]


@router.post("/articles/{article_id}/tags", response_model=list[TagOut])
async def tag_article(
    article_id: uuid.UUID, body: TagIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """`write` on the article, like editing it."""
    actx = await articles_service.context_for(db, ctx, article_id, user.id)
    actx.require(access_service.can_write(actx.level), "you have read-only access to this article")
    tag = await tags_service.get_or_create(db, ctx, user, name=body.name)
    await tags_service.apply_to_article(db, actx.article, tag)
    tags = await tags_service.for_articles(db, [actx.article.id])
    return [_tag_out(t) for t in tags.get(actx.article.id, [])]


@router.delete("/articles/{article_id}/tags/{tag_id}", response_model=list[TagOut])
async def untag_article(
    article_id: uuid.UUID, tag_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    actx = await articles_service.context_for(db, ctx, article_id, user.id)
    actx.require(access_service.can_write(actx.level), "you have read-only access to this article")
    await tags_service.unapply_from_article(db, actx.article, tag_id)
    tags = await tags_service.for_articles(db, [actx.article.id])
    return [_tag_out(t) for t in tags.get(actx.article.id, [])]


# --- recall ---------------------------------------------------------------------


class RecalledOut(BaseModel):
    kind: Literal["fact", "article", "task"]
    id: str
    title: str
    snippet: str | None
    context: str | None
    #: The book a fact lives in (facts have no screen of their own), else the
    #: item itself — enough for the client to build the link.
    parent_id: str | None
    when: datetime
    inactive: bool
    by: str | None
    via: str | None
    tags: list[str]
    score: float
    matched: Literal["text", "meaning", "both"]


class RecallOut(BaseModel):
    items: list[RecalledOut]
    #: False when only text was searched — embeddings off, or the model
    #: didn't answer in time. A client saying "nothing found" should say so.
    semantic: bool
    unknown_tags: list[str]


@router.get("/recall", response_model=RecallOut)
async def recall(
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    q: str = "",
    tags: Annotated[list[str] | None, Query()] = None,
    kinds: Annotated[list[Literal["fact", "article", "task"]] | None, Query()] = None,
    include_inactive: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = recall_service.DEFAULT_LIMIT,
):
    """What the caller can see that answers `q`, by text and by meaning,
    best first. Tags narrow (all of them must match); kinds default to all
    three."""
    result = await recall_service.recall(
        db,
        ctx,
        user.id,
        q=q,
        kinds=tuple(kinds or ()) or recall_service.KINDS,
        tags=tags or [],
        include_inactive=include_inactive,
        limit=limit,
    )
    return RecallOut(
        items=[
            RecalledOut(
                kind=i.kind,
                id=str(i.id),
                title=i.title,
                snippet=i.snippet,
                context=i.context,
                parent_id=str(i.parent_id) if i.parent_id else None,
                when=i.when,
                inactive=i.inactive,
                by=i.by,
                via=i.via,
                tags=i.tags,
                score=round(i.score, 5),
                matched=i.matched,
            )
            for i in result.items
        ],
        semantic=result.semantic,
        unknown_tags=result.unknown_tags,
    )
