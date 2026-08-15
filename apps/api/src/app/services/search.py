"""Search — fuzzy, fast, and inside the access model by construction.

## Why this is Postgres and not Typesense/Meilisearch/Elastic

The deciding factor is **permissions, not scale**.

What a person may see here is *computed*: `GREATEST` over ownership, direct
grants, team grants, project inheritance and organisation role, across five
tables (see `services/access.py`). Handing that to an external engine leaves
two options, and both are bad:

1. **Denormalise an ACL onto every document.** Then adding one person to one
   team re-indexes every task in every project that team can reach. Until it
   finishes, the index is wrong — and an index that is wrong about permissions
   is a data leak, not a stale cache. Revoking access is the dangerous
   direction: the row keeps matching until the reindex lands.
2. **Over-fetch and filter afterwards.** Ask the engine for 200, drop the ones
   they can't see, hope enough survive. That throws away the speed you bought
   the engine for, and it breaks counts and pagination.

In Postgres the visibility expression composes into the *same statement* as the
text match. Correct by construction, always fresh, nothing to sync, nothing to
operate. For a self-hosted product that also means one less container in a
stack whose whole pitch is `docker compose up`.

**When to revisit.** Genuinely, not never:

* cross-organisation search (there is no per-org filter to prune with);
* ranking over large message bodies past roughly a million documents;
* wanting typo-tolerant highlighting, synonyms or learn-to-rank.

At that point the shape to reach for is a search service fed by a change
stream, with the ACL check *still* done in Postgres on the returned ids — the
engine ranks, the database authorises.

## How the matching works

Two mechanisms, because they fail in different ways:

* **`pg_trgm`** for fuzziness — handles typos and mid-word substrings, and its
  GIN index is what makes `ILIKE '%…%'` fast rather than a sequential scan.
* **Prefix matching** for as-you-type, so "antif" finds "antifoul" from the
  fifth keystroke rather than only once the word is complete.

Scores from both are combined with `GREATEST` so a strong signal from either
wins, and the threshold is deliberately generous: a search box that shows
nothing feels broken, while one extra near-miss costs a glance.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import (
    ColumnElement,
    Float,
    Select,
    case,
    exists,
    func,
    literal,
    or_,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Tag, Task, TaskNote, TaskTag
from app.services import access
from app.services.organisations import OrgContext

# Below this, a trigram match is noise rather than a near-miss.
FUZZY_THRESHOLD = 0.3

# Shorter than this and trigram similarity is meaningless (a two-character
# query is similar to everything), so those fall back to prefix matching alone.
MIN_FUZZY_LENGTH = 3

# Per-kind cap. The palette shows a handful of each; asking for more makes the
# query slower for results nobody scrolls to.
DEFAULT_LIMIT = 6


@dataclass(frozen=True)
class Hit:
    kind: str  # "task" | "project" | "note"
    id: str
    title: str
    subtitle: str | None
    context: str | None
    score: float
    # Whether the thing is closed/archived. Shown, not hidden: people search
    # for finished work precisely because they can't remember where it went.
    inactive: bool


def _score(column, q: str) -> ColumnElement[float]:
    """How well one text column matches the query.

    `GREATEST` over three signals rather than a weighted sum: they're on
    different scales and a weighted sum would need tuning nobody can explain
    later. A strong signal from any one of them is enough.
    """
    signals = [
        # Starts with what you typed — the as-you-type case, ranked top.
        case((column.ilike(f"{q}%"), literal(1.0)), else_=literal(0.0)),
        # Contains it. Fast because of the GIN trigram index, which is the
        # whole reason a leading-wildcard LIKE is affordable here.
        case((column.ilike(f"%{q}%"), literal(0.8)), else_=literal(0.0)),
    ]
    if len(q) >= MIN_FUZZY_LENGTH:
        # Typo tolerance. `word_similarity` compares the query against the
        # best-matching *word* in the column rather than the whole string, so
        # a long title isn't penalised for being long.
        signals.append(func.word_similarity(q, func.coalesce(column, "")))
    return func.greatest(*signals).cast(Float)


def _matches(column, q: str) -> ColumnElement[bool]:
    """The predicate. **Both halves must be index-servable.**

    `ILIKE '%…%'` is, through `gin_trgm_ops`. The fuzzy half only is when it
    is written as the **operator** `q <% col` — `word_similarity(q, col) > 0.3`
    is the same test to a reader and a sequential scan to the planner, because
    a function call in a comparison has no index to match against.

    Two details, both of which silently un-index it if you get them wrong:

    * **The column goes on the left** (`col %> q`, not `q <% col`). They are
      commutators and mean the same thing; only one has the indexed side where
      the planner looks for it.
    * **No `coalesce()`.** Wrapping the column makes it an expression the plain
      index can't match, and a NULL column yields NULL — which is filtered out
      anyway, exactly like `word_similarity(q, '')` scoring zero did.

    Measured on 10,000 tasks: the whole search went from ~450ms to ~130ms.
    Postgres still often picks a scan over the trigram index here, because
    trigram selectivity estimates are poor and one organisation holds every
    row; forcing the index takes the same query to 14ms. Not worth a planner
    hint yet — worth knowing when this is next too slow.

    `%>` compares against `pg_trgm.word_similarity_threshold`, a GUC, rather
    than an inline number. `apply_threshold()` sets it per transaction so the
    two agree; without that call the default 0.6 applies and typo tolerance
    quietly halves.
    """
    tests = [column.ilike(f"%{q}%")]
    if len(q) >= MIN_FUZZY_LENGTH:
        tests.append(column.op("%>")(q))
    return or_(*tests)


async def apply_threshold(db: AsyncSession) -> None:
    """Point `<%` at our threshold rather than Postgres' default.

    `set_config(..., is_local => true)` rather than `SET LOCAL`: it lasts
    exactly this transaction either way, but `SET` is parsed before parameters
    are bound and rejects a placeholder outright. The function form takes one.

    Transaction-local matters — a pooled connection is handed straight to the
    next request, and a threshold left behind would quietly change how
    somebody else's search behaves.
    """
    await db.execute(
        text("SELECT set_config('pg_trgm.word_similarity_threshold', :t, true)"),
        {"t": str(FUZZY_THRESHOLD)},
    )


def normalise(q: str) -> str:
    """Trim and collapse whitespace. An empty query is not a search for
    everything — the caller must skip it."""
    return " ".join((q or "").split())


def tasks_stmt(*, user_id: uuid.UUID, ctx: OrgContext, q: str, limit: int) -> Select:
    """Matching tasks the caller can see. One statement, as ever.

    The text predicate and the visibility expression are ANDed in the same
    WHERE, so there is no window in which a row that fails the access check
    could be returned and filtered later.
    """
    level = access.task_level_expression(user_id, ctx.role)
    # A tag is a deliberate label, so a match on one is a strong signal —
    # ranked just under the title and above a mention in the body. This is
    # also the *only* way to reach an off-board task by typing: it is off the
    # board by design, so search has to know the word people filed it under.
    tag_hit = exists(
        select(1)
        .select_from(TaskTag)
        .join(Tag, Tag.id == TaskTag.tag_id)
        .where(TaskTag.task_id == Task.id, _matches(Tag.name, q))
        .correlate(Task)
    )
    score = func.greatest(
        _score(Task.title, q),
        # Descriptions are secondary: a hit in the body is real but weaker
        # than a hit in the name, and this keeps the ordering intuitive.
        _score(Task.description_text, q) * literal(0.6),
        case((tag_hit, literal(0.9)), else_=literal(0.0)).cast(Float),
    )
    return (
        select(
            literal("task").label("kind"),
            Task.id.label("id"),
            Task.title.label("title"),
            # The stripped text, so a snippet is prose rather than markup.
            Task.description_text.label("subtitle"),
            Project.name.label("context"),
            score.label("score"),
            (Task.closed_at.isnot(None)).label("inactive"),
        )
        .select_from(Task)
        # Outer: a loose task has no project, and an inner join would silently
        # drop exactly the tasks that are hardest to find by browsing.
        .outerjoin(Project, Project.id == Task.project_id)
        .where(
            Task.organisation_id == ctx.organisation.id,
            level > access.NO_ACCESS,
            or_(_matches(Task.title, q), _matches(Task.description_text, q), tag_hit),
        )
        # Open work first at equal relevance — that is what people are usually
        # looking for — then score, then newest.
        .order_by(Task.closed_at.isnot(None), score.desc(), Task.id.desc())
        .limit(limit)
    )


def projects_stmt(*, user_id: uuid.UUID, ctx: OrgContext, q: str, limit: int) -> Select:
    level = access.project_level_expression(user_id, ctx.role)
    score = func.greatest(
        _score(Project.name, q),
        _score(Project.description, q) * literal(0.6),
    )
    return (
        select(
            literal("project").label("kind"),
            Project.id.label("id"),
            Project.name.label("title"),
            Project.description.label("subtitle"),
            literal(None).label("context"),
            score.label("score"),
            (Project.archived_at.isnot(None)).label("inactive"),
        )
        .select_from(Project)
        .where(
            Project.organisation_id == ctx.organisation.id,
            level > access.NO_ACCESS,
            or_(_matches(Project.name, q), _matches(Project.description, q)),
        )
        .order_by(Project.archived_at.isnot(None), score.desc(), Project.id.desc())
        .limit(limit)
    )


def notes_stmt(*, user_id: uuid.UUID, ctx: OrgContext, q: str, limit: int) -> Select:
    """The caller's own private notes.

    **Scoped to `user_id` in the same WHERE as everything else**, so there is
    no arrangement of parameters that returns somebody else's. That is the
    whole promise of the feature, and it is one clause.

    The note is the hit, but the *task* is where the link goes — you search
    your notes to get back to the work, not to read the note in a palette.
    """
    level = access.task_level_expression(user_id, ctx.role)
    score = _score(TaskNote.body, q)
    return (
        select(
            literal("note").label("kind"),
            Task.id.label("id"),
            Task.title.label("title"),
            TaskNote.body.label("subtitle"),
            literal("Your private note").label("context"),
            score.label("score"),
            (Task.closed_at.isnot(None)).label("inactive"),
        )
        .select_from(TaskNote)
        .join(Task, Task.id == TaskNote.task_id)
        .where(
            TaskNote.user_id == user_id,
            Task.organisation_id == ctx.organisation.id,
            level > access.NO_ACCESS,
            _matches(TaskNote.body, q),
        )
        .order_by(score.desc(), TaskNote.id.desc())
        .limit(limit)
    )


async def search(
    db: AsyncSession,
    ctx: OrgContext,
    user_id: uuid.UUID,
    *,
    q: str,
    limit: int = DEFAULT_LIMIT,
) -> list[Hit]:
    """Everything matching, across kinds, ordered by relevance.

    Each kind is capped separately and merged in Python rather than being one
    big UNION with a global LIMIT. That guarantees a matching project is never
    pushed off the list by twenty tasks that happen to score fractionally
    higher — the palette is for jumping to things, and a kind vanishing
    entirely is worse than an imperfect order.

    PHASE 6 adds messages and comments here: one more `*_stmt` returning the
    same shape, appended to the list below. Their visibility comes from the
    task or project they hang off, so it is the same `level > NO_ACCESS` test
    against the same expressions — nothing new to reason about.
    """
    q = normalise(q)
    if not q:
        return []

    # Before any statement that uses `<%`.
    await apply_threshold(db)

    hits: list[Hit] = []
    for stmt in (
        tasks_stmt(user_id=user_id, ctx=ctx, q=q, limit=limit),
        projects_stmt(user_id=user_id, ctx=ctx, q=q, limit=limit),
        notes_stmt(user_id=user_id, ctx=ctx, q=q, limit=limit),
    ):
        for row in (await db.execute(stmt)).all():
            hits.append(
                Hit(
                    kind=row.kind,
                    id=str(row.id),
                    title=row.title,
                    subtitle=_snippet(row.subtitle, q),
                    context=row.context,
                    score=float(row.score or 0),
                    inactive=bool(row.inactive),
                )
            )

    # Active before archived, then by score. Stable within a kind because the
    # per-kind statements already ordered themselves.
    hits.sort(key=lambda h: (h.inactive, -h.score))
    return hits


def _snippet(text: str | None, q: str, width: int = 90) -> str | None:
    """A short window around the match, so a hit in a long description shows
    *why* it matched rather than the first line of unrelated text."""
    if not text:
        return None
    body = " ".join(text.split())
    if len(body) <= width:
        return body
    at = body.lower().find(q.lower())
    if at < 0:
        return body[:width].rstrip() + "…"
    start = max(0, at - width // 3)
    end = min(len(body), start + width)
    return ("…" if start else "") + body[start:end].strip() + ("…" if end < len(body) else "")


__all__ = ["Hit", "search", "normalise", "tasks_stmt", "projects_stmt", "notes_stmt"]
