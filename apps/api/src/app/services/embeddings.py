"""Embeddings: turning facts, articles and tasks into vectors, and keeping
them current.

## Optional, like email

Nothing hard-depends on this. Semantic search needs two things — an
embedding endpoint (EMBEDDINGS_URL + EMBEDDINGS_MODEL) and the `embeddings`
table, which only exists where pgvector is installed (see migration 0052) —
and `available()` is the one place that asks for both. Without either, recall
is the trigram search the product always had, and nothing says it is broken,
because it isn't.

## Any OpenAI-compatible endpoint

`POST {EMBEDDINGS_URL}/embeddings` with `{model, input: [...]}` is spoken by
the bundled Ollama, OpenAI, Voyage, and most self-hostable servers, so one
client covers all of them. The prefixes are the one model-specific thing:
some models were trained with an instruction on each side, and are measurably
worse at retrieval without it.

## The sweep finds what changed, in SQL

There are deliberately **no hooks in the services that write facts, articles
or tasks.** A hook per write path is a hook somebody forgets — the next
feature that edits a description outside `tasks_service.update` would leave
its text unindexed forever, silently. Instead every chunk carries the md5 of
the whole source text it was cut from, and one statement per kind finds
every source whose current text hashes differently (or has no chunks for the
configured model at all). Edits, backfills, model changes and a worker that
was down for a week are all the same case.

Articles and tasks are only picked up once they have **settled** — untouched
for `SETTLE` — so an autosave every few seconds doesn't embed every draft of
a paragraph on its way to being written. A fact is finished when it is
written, so it isn't held back.

Run every minute (`tasks/embeddings.py`), kicked immediately after a fact is
written so an assistant that writes one can recall it in the same breath, and
safe to run concurrently: a session advisory lock means a second run simply
returns.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy import delete, exists, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Article, ArticleRevision, Book, Embedding, Fact, Task

logger = logging.getLogger("app.services.embeddings")

# How long an article or a task must sit untouched before it is embedded.
SETTLE = timedelta(seconds=60)

# Characters per chunk, title included. Around 300 tokens: small enough that a
# chunk is about one thing — which is what makes its similarity score mean
# something — and comfortably inside every embedding model's context.
CHUNK_CHARS = 1200

# Inputs per request to the endpoint. Small on purpose: a local model works
# through one request before it starts the next — Ollama's parallel slots do
# not apply to embedding models, measured — so a person's question queued
# behind a backfill waits for the whole batch in front of it. A batch buys
# nothing back either: sixteen inputs took sixteen times one. Four keeps that
# wait to about a second on an idle CPU; at eight, on a loaded laptop, a
# question waited 24 seconds, timed out, and quietly fell back to text.
REQUEST_BATCH = 4

# Sources taken per statement, and how long one sweep may run. A backfill of
# ten thousand tasks on a CPU is hours of work; the budget hands the rest to
# the next minute's run rather than holding the lock past it — and leaves
# half of every minute to everything else on the box.
SOURCE_BATCH = 32
SWEEP_BUDGET_SECONDS = 30

# `pg_try_advisory_lock` key. Any constant; this one is "recall" in ASCII.
_SWEEP_LOCK = 0x726563616C6C

QUERY_TIMEOUT = httpx.Timeout(10.0)
INDEX_TIMEOUT = httpx.Timeout(120.0)

_table_exists: bool | None = None


# --- pure: chunking ------------------------------------------------------------

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def chunks(title: str, body: str, *, size: int = CHUNK_CHARS) -> list[str]:
    """Cut a source into pieces of at most `size` characters, each carrying
    the title.

    **The title goes on every chunk**, not just the first: a passage from the
    middle of "Passbolt: renewing the TLS certificate" is about Passbolt, and
    without the title the vector for "run certbot renew, then reload nginx"
    has no idea which server it is about.

    Packed greedily by paragraph, then by sentence, then by word — the
    largest unit that fits — so a chunk boundary lands between thoughts
    rather than mid-sentence wherever the text allows it. No overlap between
    chunks: the title already supplies the context overlap usually exists to
    carry, and these sources are short.
    """
    title = " ".join((title or "").split())
    head = f"{title}\n\n" if title else ""
    room = max(size - len(head), size // 3)

    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n|\n", body or ""):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        if len(paragraph) <= room:
            pieces.append(paragraph)
            continue
        for sentence in _SENTENCE_END.split(paragraph):
            if len(sentence) <= room:
                pieces.append(sentence)
                continue
            words, line = sentence.split(" "), ""
            for word in words:
                # A single "word" longer than the room — a URL, a hash — is
                # cut hard; there is no better boundary inside it.
                while len(word) > room:
                    if line:
                        pieces.append(line)
                        line = ""
                    pieces.append(word[:room])
                    word = word[room:]
                candidate = f"{line} {word}".strip()
                if len(candidate) > room:
                    pieces.append(line)
                    line = word
                else:
                    line = candidate
            if line:
                pieces.append(line)

    packed: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n{piece}" if current else piece
        if len(candidate) > room:
            packed.append(current)
            current = piece
        else:
            current = candidate
    if current:
        packed.append(current)

    if not packed:
        return [title] if title else []
    return [head + p for p in packed]


# --- the endpoint --------------------------------------------------------------


async def available(db: AsyncSession) -> bool:
    """Configured, and the table exists. The table check is cached for the
    life of the process: it only changes when somebody installs pgvector and
    re-runs the migration, and both of those are followed by a restart."""
    global _table_exists
    if not settings.embeddings_enabled:
        return False
    if _table_exists is None:
        found = (await db.execute(text("SELECT to_regclass('public.embeddings')"))).scalar()
        _table_exists = found is not None
    return _table_exists


async def _embed(inputs: list[str], *, timeout: httpx.Timeout) -> list[list[float]]:
    url = settings.embeddings_url.rstrip("/") + "/embeddings"
    headers = {}
    if settings.embeddings_api_key:
        headers["Authorization"] = f"Bearer {settings.embeddings_api_key}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            url, json={"model": settings.embeddings_model, "input": inputs}, headers=headers
        )
        response.raise_for_status()
        data = response.json()["data"]
    # The spec says `index` orders them; don't trust the array order.
    return [row["embedding"] for row in sorted(data, key=lambda r: r["index"])]


async def embed_query(q: str) -> list[float] | None:
    """The question, as a vector — or None, and recall carries on as text
    search. A slow or absent model must cost a person their semantic results,
    never their search."""
    try:
        [vector] = await _embed([settings.embeddings_query_prefix + q], timeout=QUERY_TIMEOUT)
        return vector
    except Exception:
        logger.warning("embedding the query failed; recall falls back to text", exc_info=True)
        return None


async def embed_documents(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for start in range(0, len(texts), REQUEST_BATCH):
        batch = texts[start : start + REQUEST_BATCH]
        batch = [settings.embeddings_document_prefix + t for t in batch]
        out.extend(await _embed(batch, timeout=INDEX_TIMEOUT))
    return out


# --- what needs embedding ------------------------------------------------------


@dataclass(frozen=True)
class Source:
    kind: str  # "fact" | "article" | "task"
    id: uuid.UUID
    organisation_id: uuid.UUID
    title: str
    body: str
    hash: str


def _source_text_sql(title, body):
    """md5(title || E'\\n' || body). Computed in SQL on both sides of the
    comparison — when a chunk is written and when the sweep looks for stale
    ones — so there is no second spelling of it in Python to drift."""
    return func.md5(func.coalesce(title, "") + literal("\n") + func.coalesce(body, ""))


def _is_current(anchor, source_id, hashed):
    """A chunk exists for this source, for the configured model, cut from its
    current text. Not-this is what the sweep embeds."""
    return exists(
        select(1).where(
            anchor == source_id,
            Embedding.model == settings.embeddings_model,
            Embedding.source_hash == hashed,
        )
    )


def _stale_facts(limit: int, organisation_id: uuid.UUID | None):
    hashed = _source_text_sql(literal(""), Fact.body)
    return (
        select(
            literal("fact").label("kind"),
            Fact.id,
            Book.organisation_id,
            literal("").label("title"),
            Fact.body.label("body"),
            hashed.label("hash"),
        )
        .join(Book, Book.id == Fact.book_id)
        .where(
            ~_is_current(Embedding.fact_id, Fact.id, hashed),
            *([Book.organisation_id == organisation_id] if organisation_id else []),
        )
        .order_by(Fact.id.desc())
        .limit(limit)
    )


def _stale_articles(limit: int, organisation_id: uuid.UUID | None):
    # The latest revision, the same correlated subquery `search.articles_stmt`
    # uses — recall reads the live text, never history.
    latest_id = (
        select(ArticleRevision.id)
        .where(ArticleRevision.article_id == Article.id)
        .order_by(ArticleRevision.id.desc())
        .limit(1)
        .correlate(Article)
        .scalar_subquery()
    )
    hashed = _source_text_sql(ArticleRevision.title, ArticleRevision.body_text)
    return (
        select(
            literal("article").label("kind"),
            Article.id,
            Book.organisation_id,
            ArticleRevision.title.label("title"),
            ArticleRevision.body_text.label("body"),
            hashed.label("hash"),
        )
        .select_from(Article)
        .join(ArticleRevision, ArticleRevision.id == latest_id)
        .join(Book, Book.id == Article.book_id)
        .where(
            ArticleRevision.updated_at < func.now() - SETTLE,
            # An article with nothing in it yet has nothing to embed, and
            # left in it would come back as stale on every run.
            func.length(func.btrim(ArticleRevision.title + ArticleRevision.body_text)) > 0,
            ~_is_current(Embedding.article_id, Article.id, hashed),
            *([Book.organisation_id == organisation_id] if organisation_id else []),
        )
        .order_by(Article.id.desc())
        .limit(limit)
    )


def _stale_tasks(limit: int, organisation_id: uuid.UUID | None):
    hashed = _source_text_sql(Task.title, Task.description_text)
    return (
        select(
            literal("task").label("kind"),
            Task.id,
            Task.organisation_id,
            Task.title.label("title"),
            func.coalesce(Task.description_text, "").label("body"),
            hashed.label("hash"),
        )
        .where(
            Task.updated_at < func.now() - SETTLE,
            ~_is_current(Embedding.task_id, Task.id, hashed),
            *([Task.organisation_id == organisation_id] if organisation_id else []),
        )
        # Newest first, so a backfill makes the work people are looking at
        # searchable before the archive is.
        .order_by(Task.id.desc())
        .limit(limit)
    )


async def stale_sources(
    db: AsyncSession, *, limit: int = SOURCE_BATCH, organisation_id: uuid.UUID | None = None
) -> list[Source]:
    """Facts first, then articles, then tasks — the order recall weights them
    in, so a backfill makes the deliberate knowledge findable first.

    `organisation_id` narrows it to one organisation, for indexing one
    without waiting behind every other one's backfill — which is what
    `scripts/e2e-recall.sh` does, on a dev database holding tens of thousands
    of tasks from every other suite."""
    found: list[Source] = []
    for stmt in (_stale_facts, _stale_articles, _stale_tasks):
        room = limit - len(found)
        if room <= 0:
            break
        for row in (await db.execute(stmt(room, organisation_id))).all():
            found.append(
                Source(
                    kind=row.kind,
                    id=row.id,
                    organisation_id=row.organisation_id,
                    title=row.title or "",
                    body=row.body or "",
                    hash=row.hash,
                )
            )
    return found


_ANCHOR = {"fact": "fact_id", "article": "article_id", "task": "task_id"}
_MODEL = {"fact": Fact, "article": Article, "task": Task}


async def index(db: AsyncSession, sources: list[Source]) -> int:
    """Embed these sources and replace their chunks. One transaction, so a
    source is never seen half-replaced: recall reads either the old chunks or
    the new ones."""
    # End the read that found these before the slow part: an embedding call
    # can take seconds, and a transaction left open across it holds back
    # vacuum for nothing.
    await db.commit()
    pieces: list[tuple[Source, int, str]] = []
    for source in sources:
        for n, piece in enumerate(chunks(source.title, source.body)):
            pieces.append((source, n, piece))
    vectors = await embed_documents([p for _, _, p in pieces]) if pieces else []

    gone: set[uuid.UUID] = set()
    for source in sources:
        # Two indexers on one source — the sweep, and somebody indexing one
        # organisation by hand — would each delete the other's rows and then
        # both insert, leaving every chunk twice. A transaction lock per
        # source makes the second wait for the first and then replace it.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": str(source.id)}
        )
        # The source may have been deleted while it was being embedded — the
        # read was committed above, on purpose. `FOR KEY SHARE` both answers
        # that and stops it being deleted until this commits; without it, one
        # deleted fact was a foreign-key error that failed the whole batch,
        # every minute, for as long as the batch kept being picked.
        model = _MODEL[source.kind]
        held = select(model.id).where(model.id == source.id).with_for_update(key_share=True)
        alive = (await db.execute(held)).first()
        if alive is None:
            gone.add(source.id)
            continue
        anchor = getattr(Embedding, _ANCHOR[source.kind])
        await db.execute(delete(Embedding).where(anchor == source.id))
    for (source, n, piece), vector in zip(pieces, vectors, strict=True):
        if source.id in gone:
            continue
        db.add(
            Embedding(
                organisation_id=source.organisation_id,
                **{_ANCHOR[source.kind]: source.id},
                chunk_index=n,
                content=piece,
                source_hash=source.hash,
                model=settings.embeddings_model,
                embedding=vector,
            )
        )
    await db.commit()
    return len(pieces)


async def sweep(db: AsyncSession) -> int:
    """Bring every source's chunks up to date, within a time budget. Returns
    how many sources it embedded.

    A **session** advisory lock rather than a transaction one, because this
    commits per batch and an xact lock would be released by the first
    commit. Released in `finally`: a session lock outlives the session's
    transactions, so one left behind on a pooled connection would quietly
    turn every later sweep into a no-op.
    """
    if not await available(db):
        return 0
    got = (
        await db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _SWEEP_LOCK})
    ).scalar()
    if not got:
        return 0
    done = 0
    try:
        # Rows from a previous model are never compared with anything again
        # (the query filters on `model`), so they are dead weight. Their
        # sources show up as stale below and are re-embedded.
        await db.execute(delete(Embedding).where(Embedding.model != settings.embeddings_model))
        await db.commit()

        deadline = time.monotonic() + SWEEP_BUDGET_SECONDS
        while time.monotonic() < deadline:
            sources = await stale_sources(db)
            if not sources:
                break
            await index(db, sources)
            done += len(sources)
    finally:
        await db.rollback()
        await db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _SWEEP_LOCK})
        await db.commit()
    return done


__all__ = [
    "CHUNK_CHARS",
    "SETTLE",
    "Source",
    "available",
    "chunks",
    "embed_documents",
    "embed_query",
    "index",
    "stale_sources",
    "sweep",
]
