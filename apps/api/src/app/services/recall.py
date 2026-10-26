"""Recall: "what do we know about this?", across facts, articles and tasks.

The question an assistant asks at the start of a piece of work, and the one a
person asks when something feels familiar. Two searches answer it, fused:

* **by text** — `search.matches`, the trigram matcher ⌘K uses. Best at names,
  ids, error strings, the exact word somebody filed it under;
* **by meaning** — cosine distance against `embeddings`, which finds
  "renewing TLS on passbolt2" from "how do we rotate the passbolt certs".

Neither alone is enough. Meaning misses exact identifiers; text misses every
paraphrase. They are combined by **reciprocal rank fusion** — each list
contributes `1 / (RRF_K + rank)` per item — rather than by adding scores,
because a trigram similarity and a cosine distance are on scales nobody could
explain a weighted sum of later. Something both searches found rises; a
strong hit in either still places.

## Access is in the statement, both halves

Every statement here ANDs the same visibility expression its kind uses
everywhere else — `book_level_expression` for a fact, `article_level_
expression`, `task_level_expression` — into the same WHERE as the match or
the distance. That is the whole reason vectors live in Postgres (see
`models/embedding.py`): there is no moment at which a chunk the caller can't
read exists in a result set, so there is nothing an assistant could summarise
that its person couldn't have opened.

## Exact search, no vector index — on purpose

The distance is computed for every chunk of the organisation that survives
the access filter. With an approximate index (HNSW), a selective filter is
applied *after* the index has picked its candidates, and a person who can see
a small corner of a large organisation gets fewer results than they should —
or none — with nothing to say so. An exact scan cannot do that. At the size a
team's knowledge base reaches — tens of thousands of chunks — it costs tens of
milliseconds.

**Revisit when** a single organisation passes a few hundred thousand chunks.
The shape then: an HNSW expression index per model's dimension
(`(embedding::halfvec(768)) halfvec_cosine_ops WHERE model = …`) and
`SET LOCAL hnsw.iterative_scan = relaxed_order`, which keeps scanning until
enough rows pass the filter.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Float, Select, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.models import Article, ArticleRevision, Book, Embedding, Fact, Project, Task, User
from app.models.embedding import HalfVec
from app.services import access
from app.services import embeddings as embeddings_service
from app.services import search as search_service
from app.services import tags as tags_service
from app.services.organisations import OrgContext

KINDS = ("fact", "article", "task")

# The standard constant from the RRF paper. Large enough that the difference
# between rank 1 and rank 2 doesn't swamp agreement between the two lists.
RRF_K = 60

# How many candidates each list contributes before fusion. More than the
# answer needs, so an item ranked modestly by both can still win.
CANDIDATES = 20

# Below this cosine similarity a "match by meaning" is noise: every text is
# somewhat similar to every other, and without a floor a question about
# something nobody wrote down returns the five least-unrelated things instead
# of saying so. Per model, so it is configuration
# (`settings.embeddings_min_similarity`); see the recall rule for how to
# measure it.

# A task is evidence, not a statement of what is true — a fact or an article
# somebody wrote *for* the next reader outranks one at the same fused rank.
KIND_WEIGHT = {"fact": 1.0, "article": 1.0, "task": 0.8}

DEFAULT_LIMIT = 10


@dataclass
class Recalled:
    kind: str
    id: uuid.UUID
    title: str
    snippet: str | None
    #: The book a fact or article is in; the project a task is in, if any.
    context: str | None
    #: Where a link goes: the book for a fact (facts have no screen of their
    #: own), the article, the task.
    parent_id: uuid.UUID | None
    when: datetime
    #: Superseded fact, closed task, archived book. Shown, not hidden — the
    #: incident closed last spring is exactly what recall is for.
    inactive: bool
    by: str | None = None
    via: str | None = None
    tags: list[str] = field(default_factory=list)
    score: float = 0.0
    #: "text", "meaning" or "both" — which search found it, so a caller can
    #: tell a paraphrase from a literal hit.
    matched: str = ""


@dataclass
class RecallResult:
    items: list[Recalled]
    #: Whether the meaning half ran. False when embeddings are switched off
    #: or the endpoint didn't answer — a caller that reports "nothing found"
    #: should know it was only looking by text.
    semantic: bool
    #: A tag that was asked for and doesn't exist. Nothing can carry it, so
    #: the answer is empty — and saying which word was wrong is the useful
    #: part of that answer.
    unknown_tags: list[str] = field(default_factory=list)


# --- one base statement per kind ----------------------------------------------
#
# Each returns the same labelled columns — id, title, body, context, parent_id,
# when, inactive, by_user_id, via — already restricted to what the caller can
# see, plus the text columns a literal match is tried against. The text and
# meaning searches then each add their own half to it, so the access rule is
# written once per kind, not once per search.


def _fact_base(user_id: uuid.UUID, ctx: OrgContext, tag_ids, include_inactive: bool):
    level = access.book_level_expression(user_id, ctx.role)
    stmt = (
        select(
            Fact.id.label("id"),
            literal("").label("title"),
            Fact.body.label("body"),
            Book.name.label("context"),
            Book.id.label("parent_id"),
            Fact.created_at.label("when"),
            (Fact.superseded_at.isnot(None) | Book.archived_at.isnot(None)).label("inactive"),
            Fact.created_by_user_id.label("by_user_id"),
            Fact.via.label("via"),
        )
        .select_from(Fact)
        .join(Book, Book.id == Fact.book_id)
        .where(
            Book.organisation_id == ctx.organisation.id,
            level > access.NO_ACCESS,
            *tags_service.fact_tagged_with_all(tag_ids),
        )
    )
    if not include_inactive:
        stmt = stmt.where(Fact.superseded_at.is_(None))
    return stmt, [Fact.body], Fact.id


def _article_base(user_id: uuid.UUID, ctx: OrgContext, tag_ids, include_inactive: bool):
    level = access.article_level_expression(user_id, ctx.role)
    latest_id = (
        select(ArticleRevision.id)
        .where(ArticleRevision.article_id == Article.id)
        .order_by(ArticleRevision.id.desc())
        .limit(1)
        .correlate(Article)
        .scalar_subquery()
    )
    revision = aliased(ArticleRevision)
    stmt = (
        select(
            Article.id.label("id"),
            revision.title.label("title"),
            revision.body_text.label("body"),
            Book.name.label("context"),
            Article.id.label("parent_id"),
            revision.updated_at.label("when"),
            Book.archived_at.isnot(None).label("inactive"),
            Article.owner_user_id.label("by_user_id"),
            literal(None).label("via"),
        )
        .select_from(Article)
        .join(revision, revision.id == latest_id)
        .join(Book, Book.id == Article.book_id)
        .where(
            Book.organisation_id == ctx.organisation.id,
            level > access.NO_ACCESS,
            *tags_service.article_tagged_with_all(tag_ids),
        )
    )
    if not include_inactive:
        stmt = stmt.where(Book.archived_at.is_(None))
    return stmt, [revision.title, revision.body_text], Article.id


def _task_base(user_id: uuid.UUID, ctx: OrgContext, tag_ids, include_inactive: bool):
    """Closed tasks included even when `include_inactive` is off. A closed
    task is not a retracted one — "what did we do last time" is answered by
    exactly the tasks that are finished, which is the difference between a
    task here and a superseded fact."""
    level = access.task_level_expression(user_id, ctx.role)
    stmt = (
        select(
            Task.id.label("id"),
            Task.title.label("title"),
            Task.description_text.label("body"),
            Project.name.label("context"),
            Task.id.label("parent_id"),
            Task.updated_at.label("when"),
            Task.closed_at.isnot(None).label("inactive"),
            Task.owner_user_id.label("by_user_id"),
            literal(None).label("via"),
        )
        .select_from(Task)
        # Outer: a loose task has no project — search.tasks_stmt's reason.
        .outerjoin(Project, Project.id == Task.project_id)
        .where(
            Task.organisation_id == ctx.organisation.id,
            level > access.NO_ACCESS,
            *tags_service.task_tagged_with_all(tag_ids),
        )
    )
    return stmt, [Task.title, Task.description_text], Task.id


_BASES = {"fact": _fact_base, "article": _article_base, "task": _task_base}
_ANCHORS = {"fact": Embedding.fact_id, "article": Embedding.article_id, "task": Embedding.task_id}


def text_stmt(base: Select, columns, q: str, *, limit: int = CANDIDATES) -> Select:
    """The literal half: any column matches, scored like ⌘K scores it — the
    first column (a title) at full weight, the rest at the 0.6 a body gets in
    `search.tasks_stmt`."""
    score = func.greatest(
        *[
            search_service.column_score(col, q) * literal(1.0 if i == 0 else 0.6)
            for i, col in enumerate(columns)
        ]
    ).cast(Float)
    return (
        base.add_columns(score.label("score"), literal(None).label("chunk"))
        .where(or_(*[search_service.matches(col, q) for col in columns]))
        .order_by(score.desc())
        .limit(limit)
    )


def meaning_stmt(
    base: Select,
    source_id,
    kind: str,
    vector: list[float],
    *,
    org_id: uuid.UUID,
    limit: int = CANDIDATES,
) -> Select:
    """The semantic half: each source's *closest* chunk, closest sources first.

    `ROW_NUMBER() OVER (PARTITION BY source ORDER BY distance)` keeps one row
    per source — a long article must not take all twenty places with twenty
    chunks of itself — the same window `access.board_stmt` uses to bound a
    board column. The model filter is what keeps vectors of different lengths
    from ever meeting, which pgvector would refuse outright.
    """
    distance = Embedding.embedding.op("<=>", return_type=Float)(
        literal(vector, type_=HalfVec())
    )
    ranked = (
        base.add_columns(
            (literal(1.0) - distance).label("score"),
            Embedding.content.label("chunk"),
            func.row_number()
            .over(partition_by=source_id, order_by=distance)
            .label("rn"),
        )
        .join(Embedding, _ANCHORS[kind] == source_id)
        # `organisation_id` again, on the chunk this time: it is what lets the
        # (organisation_id, model) index prune before a single distance is
        # computed. The access expression in `base` is still what decides.
        .where(Embedding.organisation_id == org_id, Embedding.model == settings.embeddings_model)
        .subquery()
    )
    return (
        select(ranked)
        .where(ranked.c.rn == 1, ranked.c.score >= settings.embeddings_min_similarity)
        .order_by(ranked.c.score.desc())
        .limit(limit)
    )


# --- fusion ---------------------------------------------------------------------


def fuse(
    lists: dict[tuple[str, str], list[uuid.UUID]], *, weights: dict[str, float] | None = None
) -> dict[tuple[str, uuid.UUID], float]:
    """Reciprocal rank fusion. `lists` maps (kind, "text"|"meaning") to ids in
    rank order; the result maps (kind, id) to its fused score.

    Pure, so `test_recall_rules.py` can pin what it promises without a
    database: agreement between the two searches beats a single first place,
    and a kind's weight scales everything that kind contributes.
    """
    weights = weights or KIND_WEIGHT
    scores: dict[tuple[str, uuid.UUID], float] = {}
    for (kind, _mode), ids in lists.items():
        for rank, item_id in enumerate(ids, start=1):
            key = (kind, item_id)
            scores[key] = scores.get(key, 0.0) + weights.get(kind, 1.0) / (RRF_K + rank)
    return scores


def _strip_title(chunk: str | None, title: str) -> str | None:
    """A chunk carries its source's title (see `embeddings.chunks`); the
    snippet beside that title shouldn't say it twice."""
    if not chunk:
        return None
    if title and chunk.startswith(title):
        chunk = chunk[len(title) :]
    return " ".join(chunk.split()) or None


async def recall(
    db: AsyncSession,
    ctx: OrgContext,
    user_id: uuid.UUID,
    *,
    q: str,
    kinds: tuple[str, ...] = KINDS,
    tags: list[str] | None = None,
    include_inactive: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> RecallResult:
    """Everything the caller can see that answers `q`, best first."""
    q = search_service.normalise(q)
    if not q:
        return RecallResult(items=[], semantic=False)

    tag_ids: list[uuid.UUID] = []
    unknown: list[str] = []
    for name in tags or []:
        found = await tags_service.find_by_name(db, ctx, name)
        if found is None:
            unknown.append(name)
        else:
            tag_ids.append(found.id)

    vector = None
    if await embeddings_service.available(db):
        vector = await embeddings_service.embed_query(q)
    if unknown:
        return RecallResult(items=[], semantic=vector is not None, unknown_tags=unknown)

    await search_service.apply_threshold(db)

    lists: dict[tuple[str, str], list[uuid.UUID]] = {}
    rows: dict[tuple[str, uuid.UUID], object] = {}
    found_by: dict[tuple[str, uuid.UUID], set[str]] = {}
    chunk_of: dict[tuple[str, uuid.UUID], str] = {}

    for kind in kinds:
        base, columns, source_id = _BASES[kind](user_id, ctx, tag_ids, include_inactive)
        searches = [("text", text_stmt(base, columns, q))]
        if vector is not None:
            searches.append(
                ("meaning", meaning_stmt(base, source_id, kind, vector, org_id=ctx.organisation.id))
            )
        for mode, stmt in searches:
            ids = []
            for row in (await db.execute(stmt)).all():
                key = (kind, row.id)
                ids.append(row.id)
                rows.setdefault(key, row)
                found_by.setdefault(key, set()).add(mode)
                if mode == "meaning" and row.chunk:
                    chunk_of[key] = row.chunk
            lists[(kind, mode)] = ids

    scores = fuse(lists)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]

    authors = {rows[key].by_user_id for key, _ in ranked if rows[key].by_user_id}
    people = {}
    if authors:
        people = {
            u.id: (u.display_name or u.email)
            for u in (await db.execute(select(User).where(User.id.in_(authors)))).scalars()
        }
    by_kind: dict[str, list[uuid.UUID]] = {}
    for (kind, item_id), _ in ranked:
        by_kind.setdefault(kind, []).append(item_id)
    tag_names: dict[tuple[str, uuid.UUID], list[str]] = {}
    for kind, loader in (
        ("fact", tags_service.for_facts),
        ("article", tags_service.for_articles),
        ("task", tags_service.for_tasks),
    ):
        for item_id, item_tags in (await loader(db, by_kind.get(kind, []))).items():
            tag_names[(kind, item_id)] = [t.name for t in item_tags]

    items: list[Recalled] = []
    for key, score in ranked:
        kind, item_id = key
        row = rows[key]
        modes = found_by[key]
        # The passage that matched by meaning if there is one — it is the
        # part that answers the question — else a window around the literal
        # match, the way the palette shows one.
        snippet = _strip_title(chunk_of.get(key), row.title) or search_service.snippet(
            row.body, q, width=240
        )
        items.append(
            Recalled(
                kind=kind,
                id=item_id,
                title=row.title or (row.body or "").split("\n", 1)[0][:120],
                snippet=snippet,
                context=row.context,
                parent_id=row.parent_id,
                when=row.when,
                inactive=bool(row.inactive),
                by=people.get(row.by_user_id),
                via=row.via,
                tags=tag_names.get(key, []),
                score=score,
                matched="both" if len(modes) == 2 else next(iter(modes)),
            )
        )
    return RecallResult(items=items, semantic=vector is not None)


__all__ = [
    "CANDIDATES",
    "KINDS",
    "RRF_K",
    "RecallResult",
    "Recalled",
    "fuse",
    "meaning_stmt",
    "recall",
    "text_stmt",
]
