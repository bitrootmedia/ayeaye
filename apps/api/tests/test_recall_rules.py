"""Facts and recall: the parts that are pure functions.

No database and no model. Who may delete a fact, what a fact may hold, how a
source is cut into chunks, and what reciprocal rank fusion promises — each
written so it can be tested like this. The SQL half (a fact's level is its
book's, recall's access on the meaning half, superseding, the sweep finding
what changed) is proved through Postgres and a real model by
`scripts/e2e-recall.sh`; neither covers the other's half, the split
`tests/test_access_matrix.py` documents.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.models.embedding import Embedding, HalfVec
from app.models.knowledge_base import MAX_FACT_LENGTH
from app.services.embeddings import CHUNK_CHARS, chunks
from app.services.facts import can_delete, clean_body
from app.services.recall import RRF_K, fuse

# --- who may delete a fact ------------------------------------------------------


def test_the_author_with_write_may_delete_their_own():
    me = uuid.uuid4()
    assert can_delete(level="write", created_by_user_id=me, user_id=me)


def test_a_writer_may_not_delete_somebody_elses():
    """Supersede is the writer's way out of somebody else's fact; delete is for
    the one that was simply wrong, and that is its author's or the owner's call."""
    assert not can_delete(level="write", created_by_user_id=uuid.uuid4(), user_id=uuid.uuid4())


def test_the_books_owner_may_delete_anything():
    assert can_delete(level="owner", created_by_user_id=uuid.uuid4(), user_id=uuid.uuid4())


def test_an_author_cut_back_to_read_cannot_delete():
    """Writing it needed `write`; deleting it still does. Access taken away is
    taken away from what you once wrote, too."""
    me = uuid.uuid4()
    assert not can_delete(level="read", created_by_user_id=me, user_id=me)


def test_an_orphaned_fact_never_matches_the_caller():
    """`created_by_user_id` is SET NULL — a NULL author must never compare
    equal to anybody, or every writer could delete it."""
    assert not can_delete(level="write", created_by_user_id=None, user_id=uuid.uuid4())


# --- what a fact may hold ----------------------------------------------------------


def test_a_fact_is_trimmed():
    assert clean_body("  the thing  \n") == "the thing"


@pytest.mark.parametrize("raw", ["", "   ", "\n\t", None])
def test_an_empty_fact_is_refused(raw):
    with pytest.raises(HTTPException) as exc:
        clean_body(raw)
    assert exc.value.status_code == 422


def test_a_long_fact_is_refused_not_cut():
    """Half a fact says something else."""
    assert clean_body("x" * MAX_FACT_LENGTH) == "x" * MAX_FACT_LENGTH
    with pytest.raises(HTTPException) as exc:
        clean_body("x" * (MAX_FACT_LENGTH + 1))
    assert exc.value.status_code == 422
    assert "article" in exc.value.detail


# --- chunking ---------------------------------------------------------------------


def test_a_short_source_is_one_chunk_carrying_its_title():
    assert chunks("Passbolt TLS", "Reload nginx after certbot.") == [
        "Passbolt TLS\n\nReload nginx after certbot."
    ]


def test_a_fact_has_no_title_and_gets_none():
    assert chunks("", "Reload nginx after certbot.") == ["Reload nginx after certbot."]


def test_a_title_with_nothing_under_it_is_still_something():
    """A task is often only a title — it is still worth finding."""
    assert chunks("Incident: helm out of disk", "") == ["Incident: helm out of disk"]


def test_nothing_at_all_is_no_chunks():
    """The sweep's SQL excludes empty sources for exactly this reason: one that
    produced no chunks would come back as stale on every run."""
    assert chunks("", "   \n ") == []


def test_every_chunk_fits_and_carries_the_title():
    body = "\n\n".join(f"Paragraph {n}. " + "word " * 120 for n in range(12))
    out = chunks("Restoring from backup", body)
    assert len(out) > 1
    for piece in out:
        assert len(piece) <= CHUNK_CHARS
        assert piece.startswith("Restoring from backup\n\n")


def test_nothing_is_lost_between_chunks():
    """Every word of the source is in some chunk, in order."""
    words = [f"w{n}" for n in range(900)]
    out = chunks("T", " ".join(words))
    rebuilt = " ".join(p.removeprefix("T\n\n").replace("\n", " ") for p in out).split()
    assert rebuilt == words


def test_paragraphs_are_kept_together_where_they_fit():
    """A chunk boundary lands between thoughts, not mid-sentence."""
    first = "The certificate is renewed by certbot. " * 10
    second = "Nginx keeps serving the old one until reloaded. " * 10
    out = chunks("", f"{first}\n\n{second}", size=600)
    assert out[0].strip() == first.strip()
    assert out[1].strip() == second.strip()


def test_a_word_longer_than_a_chunk_is_cut_hard():
    """A URL or a hash has no better boundary inside it — and must not loop."""
    out = chunks("", "x" * 3000, size=1000)
    assert "".join(out) == "x" * 3000
    assert all(len(p) <= 1000 for p in out)


# --- fusion -----------------------------------------------------------------------


def test_agreement_beats_a_single_first_place():
    """Found second by both searches outranks found first by one — the whole
    reason to fuse rather than pick a winner."""
    a, b = uuid.uuid4(), uuid.uuid4()
    scores = fuse({("fact", "text"): [a, b], ("fact", "meaning"): [b]})
    assert scores[("fact", b)] > scores[("fact", a)]


def test_rank_one_is_worth_one_over_k_plus_one():
    a = uuid.uuid4()
    assert fuse({("fact", "text"): [a]}, weights={"fact": 1.0})[("fact", a)] == 1 / (RRF_K + 1)


def test_a_kinds_weight_scales_what_it_contributes():
    """A task is evidence rather than a statement of what is true, so at the
    same rank it places under a fact."""
    f, t = uuid.uuid4(), uuid.uuid4()
    scores = fuse({("fact", "text"): [f], ("task", "text"): [t]})
    assert scores[("fact", f)] > scores[("task", t)]


def test_the_same_id_in_two_kinds_is_two_results():
    """Keyed on (kind, id): a task and a fact can't share a UUIDv7, but the
    fusion must not depend on that."""
    shared = uuid.uuid4()
    scores = fuse({("fact", "text"): [shared], ("task", "text"): [shared]})
    assert set(scores) == {("fact", shared), ("task", shared)}


# --- the switch, and the column ------------------------------------------------------


def test_semantic_search_needs_both_an_endpoint_and_a_model():
    """Email's contract: empty is a supported deployment, not a broken one."""
    assert not Settings(embeddings_url="", embeddings_model="").embeddings_enabled
    assert not Settings(embeddings_url="http://ollama:11434/v1").embeddings_enabled
    assert not Settings(embeddings_model="embeddinggemma:300m").embeddings_enabled
    assert Settings(
        embeddings_url="http://ollama:11434/v1", embeddings_model="embeddinggemma:300m"
    ).embeddings_enabled


def test_a_vector_is_written_in_pgvectors_own_text_form():
    """asyncpg has no codec for `halfvec`, so the bind is text and the cast is
    the server's — the format has to be the one pgvector parses."""
    process = HalfVec().bind_processor(dialect=None)
    assert process([0.5, -1, 2]) == "[0.5,-1.0,2.0]"
    assert process(None) is None


def test_a_chunk_has_exactly_one_anchor():
    """Three nullable foreign keys, one CHECK — `attachments`' idiom, so each
    cascades and nothing has to sweep up orphans."""
    checks = {
        c.name: str(c.sqltext)
        for c in Embedding.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert checks["ck_embeddings_one_anchor"] == "num_nonnulls(fact_id, article_id, task_id) = 1"
    for anchor in ("fact_id", "article_id", "task_id"):
        [fk] = Embedding.__table__.c[anchor].foreign_keys
        assert fk.ondelete == "CASCADE"
