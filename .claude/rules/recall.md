---
paths:
  - "apps/api/src/app/services/recall.py"
  - "apps/api/src/app/services/embeddings.py"
  - "apps/api/src/app/services/facts.py"
  - "apps/api/src/app/models/embedding.py"
  - "apps/api/src/app/api/routers/recall.py"
  - "apps/api/src/app/tasks/embeddings.py"
  - "apps/api/alembic/versions/0052_recall.py"
  - "apps/web/src/components/facts-panel.tsx"
  - "apps/web/src/components/recall-box.tsx"
  - "apps/web/src/views/FactLink.tsx"
  - "infra/postgres/Dockerfile"
  - "scripts/e2e-recall.sh"
  - "e2e/tests/recall.spec.ts"
---

# Facts and recall: the knowledge base as shared memory

## What it is, and why

Decided 2026-10-26: ayeaye becomes the team's knowledge base **and** its
agents' shared memory, in one place with one access model — the job a
separate memory service (Hindsight) was being trialled for. Hindsight is
kept, if at all, for an agent's loose scratch memory; anything a colleague
should find lives here.

Two new things, both in books:

- **Facts** (`services/facts.py`) — a few sentences worth knowing next time:
  a gotcha, a decision and its reason, what an incident turned out to be.
  What an agent writes with `remember` and what a person adds on the book
  screen. Articles are documents somebody shapes; facts are finished when
  typed.
- **Recall** (`services/recall.py`) — "what do we already know about this?"
  across facts, articles and tasks (closed included), by text **and by
  meaning**, fused. The REST route is `GET /kb/recall`, the MCP tool is
  `recall`, the screen is the box on top of the knowledge base.

Plus **one tag vocabulary across tasks, articles and facts** (`article_tags`,
`fact_tags` beside `task_tags`), so the runbook and the task are found under
the same word, and `TagStrip` took a `basePath` + `noun` the way
`AccessPanel` and `FilesPanel` did.

## The rules for a fact

1. **Its level is its book's.** No owner, no private state, no route of its
   own — `access.visible_facts_stmt` is `book_level_expression` and nothing
   else, and there is deliberately no `fact_level_expression`, which would
   read like a second rule.
2. **No draft step**, unlike an article. The point of writing one — often an
   assistant, mid-task — is that the next session finds it.
3. **Editing and superseding is `write` on the book; deleting is the author
   (still holding `write`) or the book's owner.** Supersede is for "stopped
   being true" and keeps the history; delete is for "was wrong".
   `can_delete` is pure and pinned in `tests/test_recall_rules.py`.
4. **Superseding can point at a replacement only you can see**, resolved
   through the same `context_for` — so naming a fact in a book you can't read
   is the same 404 as one that doesn't exist.
5. **Tags are resolved before the fact is added.** `tags.get_or_create`
   commits (it must, to win a race for a new name); resolving after the add
   would leave a window where the fact exists untagged.
6. **`via` is `messages.via`**: the token or OAuth client name, so "via
   Claude" shows beside whose access it was written with.

A fact has **no screen of its own**: links go to its book with `?fact=` and
the row is picked out and scrolled to. `/orgs/:org/kb/facts/:id`
(`views/FactLink.tsx`) is the permalink ⌘K uses — it resolves the book and
replaces itself.

## Why vectors are in Postgres

The argument `search.md` makes against a search engine, only stronger: a
separate vector store needs the ACL copied onto every chunk, a team change
re-indexes thousands of rows, and until it finishes recall hands an assistant
text its person can't open — a leak in prose. Here every `meaning_stmt` ANDs
the kind's own access expression into the same statement as the distance.
`scripts/e2e-recall.sh` proves the direction that matters: revoking a grant
removes the fact from recall **on the next question, with no re-index**.

- **pgvector, built into the bundled image** (`infra/postgres/Dockerfile`),
  not the `pgvector/pgvector` image — that one is Debian, and an existing
  alpine data directory was initialised against musl's collation. The
  `clang`/`llvm` version must match what the base image was built with
  (`pg_config --configure` says); `OPTFLAGS=""` drops `-march=native`.
- **Migration 0052 creates `embeddings` only where pgvector exists.** The one
  conditional migration: a managed Postgres without it must still migrate,
  because the feature is optional. `embeddings.available()` checks the table
  at runtime (cached per process) and recall falls back to text.
- **`halfvec`, no declared dimension, `model` on every row.** Any model fits
  the column; the query filters on `model`, so vectors of two lengths never
  meet (pgvector refuses that outright). Changing `EMBEDDINGS_MODEL` deletes
  the old rows on the next sweep and re-embeds everything.
- **One anchor per row** (`fact_id`/`article_id`/`task_id` +
  `num_nonnulls(...) = 1`), `attachments`' idiom: deleting a source cascades
  its chunks, nothing to sweep up.
- **No vector index, on purpose: exact scan.** HNSW applies a selective
  filter *after* picking candidates, so a person who sees a small corner of a
  big organisation silently gets too few results. Exact is tens of ms at a
  team's scale. Revisit past a few hundred thousand chunks per organisation —
  the shape is in `recall.py`'s docstring.
- **`HalfVec` is a three-line `UserDefinedType`**, not the pgvector package:
  bound as text and cast server-side, because asyncpg has no codec for the
  type, and nothing ever reads a vector back.

## The sweep

`tasks/embeddings.py`, **every minute**, plus a kick straight after a fact is
written (router and `remember`). There are **no hooks in the write paths**:
every chunk carries `md5(title || '\n' || body)` of its source, computed in
SQL on both sides, and one statement per kind finds every source whose text
hashes differently or has no chunks for the current model. Edits, backfill,
a model change and a week of the worker being down are one case.

- **Articles and tasks wait `SETTLE` (60s) untouched**, so autosave doesn't
  embed every draft of a paragraph. Facts don't wait.
- **Facts first, then articles, then tasks, newest first** — a backfill makes
  the deliberate knowledge findable before the archive.
- **A session advisory lock** makes concurrent sweeps no-ops; a **per-source
  transaction lock** in `index()` stops two indexers doubling chunks; and
  **`FOR KEY SHARE` on the source** before replacing its chunks. That last one
  was a real bug: the read is committed before the slow embedding call, a
  fact deleted meanwhile made the insert a foreign-key error, and the whole
  batch failed every minute for as long as it kept being picked.
- **`organisation_id` on `stale_sources`** lets one organisation be indexed
  without waiting behind everyone else's backfill — which is how the e2e
  suite settles, on a dev database holding ~18,000 tasks from every other
  suite.

## The model, and what CPU inference taught us

Optional exactly like email: `EMBEDDINGS_URL` + `EMBEDDINGS_MODEL`, any
OpenAI-compatible `/v1/embeddings`. Production opts into the bundled Ollama
with the `local-embeddings` profile (a ~4 GB image — it carries GPU libraries
— so never on by default); `compose.override.yml` turns it on in every
checkout with `profiles: !reset []`, the way Mailpit is always on in dev.

The default is **`embeddinggemma:300m`** (768 dimensions, multilingual), with
its own asymmetric prompts as `EMBEDDINGS_QUERY_PREFIX` /
`EMBEDDINGS_DOCUMENT_PREFIX`. Three things cost real time:

- **Thread oversubscription is the whole performance story.** llama.cpp uses
  every core and its threads wait on each other at every step, so one busy
  core stalls all of them: a short query took **2.9s at ten threads and 0.3s
  at eight** on a loaded ten-core machine. The compose entrypoint re-creates
  the model under its own name with `PARAMETER num_thread` (cores − 2, or 1)
  after every pull — same weights, so nothing re-embeds. `OLLAMA_THREADS`
  overrides it.
- **Ollama serialises embedding requests; `OLLAMA_NUM_PARALLEL` does not help
  them** (measured: a query sent during an 8-input batch waited for the whole
  batch, 24s on a loaded laptop). A batch buys no throughput either — 16
  inputs took 16× one. So `REQUEST_BATCH = 4` bounds how long a person's
  question waits behind the sweep, and `SWEEP_BUDGET_SECONDS = 30` leaves half
  of every minute to everything else. A query that still times out
  (`QUERY_TIMEOUT`, 10s) **falls back to text and says so** (`semantic:
  false`) — a slow model costs semantic results, never search.
- **`EMBEDDINGS_MIN_SIMILARITY` (default 0.35) is tuned to this model.** Relevant paraphrases
  scored 0.41–0.51, the best unrelated text 0.31, and a question about bread
  0.12. Without a floor, a question nobody has written anything about returns
  the five least-unrelated things instead of nothing. A different model needs
  its own number, which is why it's configuration rather than a constant;
  re-measure with a probe like the one in the e2e suite. Measured 2026-10-26
  on 12 ops notes, 24 questions and 8 off-topic ones: OpenAI
  `text-embedding-3-small` puts the weakest right answer (no shared words) at
  0.41 and the best off-topic match at 0.25, so 0.35 holds for it too;
  embeddinggemma on the same set, 0.39 and 0.22.
- **Migration 0052 creates the extension inside a savepoint.** On a managed
  Postgres (DigitalOcean) pgvector is *available* but only the admin role may
  `CREATE EXTENSION`; the app's own role fails, and outside a savepoint that
  failure aborted the whole migration. Now it degrades to text-only like a
  missing extension. Created beforehand as admin, `IF NOT EXISTS` skips the
  privilege check and the table is made normally.

**The trigram half matches more than you'd think.** `search.matches` is
`word_similarity`, so a long paraphrase sharing two words ("expired",
"certificate") is a text hit too. That is fine for recall — both halves
agreeing is the strongest signal RRF has — but a test that wants to prove the
*meaning* half must use a question sharing no words, and assert `matched ==
"meaning"`, not merely that the fact came back.

## Fusion

Reciprocal rank fusion (`fuse`, pure and pinned): `weight / (60 + rank)` per
list, summed. Not a weighted sum of scores — a trigram similarity and a cosine
distance are on scales nobody could explain a sum of later. Tasks weigh 0.8:
they are evidence, where a fact or an article was written *for* the next
reader. Each kind contributes `CANDIDATES` (20) from each half; tags narrow
(all must match) and apply to every kind; an unknown tag name returns nothing
and names the word, because nothing can carry it.

## The frontend

- **Recall is on Enter, not as-you-type**, unlike ⌘K: every question is
  embedded first, and a request per keystroke would queue behind each other
  and the sweep. ⌘K stays the as-you-type jump by name; facts are in it too
  (`search.facts_stmt`, superseded excluded).
- **The question is in the URL** (`?recall=`), so an answer can be sent.
- **A meaning-only hit says "similar meaning"** — a result sharing no word
  with the question otherwise reads like a mistake.
- **Facts are plain text, never `dangerouslySetInnerHTML`**: what an agent
  writes over MCP is never parsed as markup.

**Browser-test trap, new here:** after "Add fact", `getByText(body)` passes
*before the POST lands*, because the text is still in the textarea — and the
next `fill` is then wiped by the first add's reset. Assert the box emptied
(`toHaveValue("")`), then the row. The changelog's dialog note, in a box
with no dialog to wait for.

## Testing

`scripts/e2e-recall.sh` needs the dev embeddings (always on in a checkout)
and takes about two minutes, mostly embedding. Its `settle` backdates
`updated_at` past `SETTLE` and indexes the test organisation directly; its
`recall` helper retries while `semantic` is false, because a question that
times out behind the dev backfill is the product behaving correctly, not
what any assertion is about. `tests/test_recall_rules.py` covers the pure
half (delete rule, body limits, chunking, fusion, the switch, the column).

**A dev database backfills for hours.** ~18,000 tasks from every e2e suite,
at CPU speed under load. `diagnose.sh`'s Recall section reports how many are
left; recall answers by text for whatever isn't embedded yet.
