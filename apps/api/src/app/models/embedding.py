"""Embeddings: what recall's semantic half compares a question against.

    facts ─────┐
    articles ──┼──► embeddings   (one row per chunk, per model)
    tasks ─────┘

**pgvector, in the Postgres that already holds everything else — not a vector
database.** The reason is the one `services/search.py` gives for not using a
search engine, and it is stronger here: what a person may see is computed
across five tables, and a separate store would need that copied onto every
chunk. A team-membership change would then re-index thousands of rows, and
until it finished the index would answer questions with text the asker can't
read — which, once an assistant summarises the answer, is a leak in prose.
Here the access expression ANDs into the same statement as the distance, so a
revoked grant takes a chunk out of recall on the very next question.

**One anchor per row, like `attachments`.** Three nullable foreign keys and a
`num_nonnulls(...) = 1` check, rather than a `(kind, id)` pair: each one
cascades, so deleting a fact, an article or a task deletes its chunks with no
sweep to forget. `organisation_id` is denormalised on top so the one query
this table has can be pruned to one organisation before anything else.

**`model` is on every row, and the query filters on it.** Vectors from two
models are not comparable — usually not even the same length, which pgvector
refuses outright — so changing EMBEDDINGS_MODEL leaves the old rows inert
until the sweep replaces them (see `services/embeddings.py`).

**`halfvec` with no declared dimension.** Half precision halves the storage
for a loss in recall nobody can measure at this size, and leaving the
dimension off is what lets the column hold whichever model is configured. The
cost is that an HNSW index needs one, which is fine: there isn't one, on
purpose — see `services/recall.py`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    cast,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db.base import Base


class HalfVec(UserDefinedType):
    """pgvector's `halfvec`, without the pgvector Python package.

    Written as text and cast on the server (`CAST(CAST($1 AS text) AS
    halfvec)`), because asyncpg has no codec for an extension type and the
    text form — `[0.1,0.2,…]` — is pgvector's own input syntax. Nothing ever
    reads a vector back out, so there is no result processor to write.
    """

    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "halfvec"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            return "[" + ",".join(repr(float(x)) for x in value) + "]"

        return process

    def bind_expression(self, bindvalue):
        return cast(cast(bindvalue, Text), self)


class Embedding(Base):
    """One chunk of one source, embedded by one model."""

    __tablename__ = "embeddings"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(fact_id, article_id, task_id) = 1", name="ck_embeddings_one_anchor"
        ),
        # The query: one organisation's chunks for the configured model.
        Index("ix_embeddings_org_model", "organisation_id", "model"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    fact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # The text that was embedded, title prefix included. Recall shows it as
    # the snippet — the passage that matched, not the first line of the source.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # md5 of the *whole* source text at the time it was embedded, on every
    # chunk. The sweep compares it with the source's current text, in SQL, to
    # find what changed — see services/embeddings.py.
    source_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(HalfVec(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
