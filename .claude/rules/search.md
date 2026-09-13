---
paths:
  - "apps/api/src/app/services/search.py"
  - "apps/web/src/components/search-palette.tsx"
  - "scripts/e2e-search.sh"
  - "e2e/tests/search.spec.ts"
---

# Search — why Postgres, and when to stop

## Search — why Postgres, and when to stop

Read the `services/search.py` docstring before proposing a search engine.

**Fuzzy matching must be written as an operator.** `word_similarity(q, col) >
0.3` and `col %> q` are the same test to a reader and completely different to
the planner: only the operator can be served by the GIN trigram index. Two
details un-index it again if you get them wrong — the **column goes on the
left**, and there must be **no `coalesce()`** around it. Measured on 10,000
tasks: search went from ~450ms to ~80ms. `%>` reads its threshold from
`pg_trgm.word_similarity_threshold`, which `apply_threshold()` sets per
transaction; without that call the default 0.6 applies and typo tolerance
quietly halves.

**The deciding factor is permissions, not scale.** What a person may see is
computed across five tables. Handing that to Typesense/Meilisearch/Elastic
means either denormalising an ACL onto every document — where one team-
membership change re-indexes thousands of docs and any lag is a *leak*, not a
stale cache — or over-fetching and filtering afterwards, which throws away the
speed you bought it for and breaks counts and pagination.

In Postgres the visibility expression ANDs into the same statement as the text
match. There is no moment at which a row the caller can't see exists in the
result set. Revoking access removes it from search on the next keystroke, with
nothing to reindex.

`pg_trgm` (migration 0005) supplies both halves: GIN indexes that make
`ILIKE '%…%'` an index lookup rather than a scan, and `word_similarity()` for
typo tolerance. Measured at **~20 ms** on a small database and **~80 ms across 10,000 tasks**,
end to end including HTTP.

**Revisit when** — genuinely, not never: cross-organisation search (no per-org
filter to prune with), ranking over message bodies past ~1M documents, or
wanting synonyms/highlighting/learn-to-rank. The shape to reach for then is an
engine fed by a change stream with the ACL check *still* in Postgres on the
returned ids: the engine ranks, the database authorises.

Adding a searchable kind is one more `*_stmt` in that module returning the same
shape. Messages and comments (Phase 6) inherit visibility from the task or
project they hang off, so it's the same `level > NO_ACCESS` test.

**`changelog_stmt` is the exception that proves the rule: no access
expression at all.** A changelog entry has no per-resource visibility — the
organisation's log is read by every member of it — so membership, already
established by `ctx`, is the whole check. Every other `*_stmt` ANDs a level
because its resource genuinely has levels.

**And a kind is two places, not one.** `search-palette.tsx`'s `go()` falls
back to a task URL for any kind it doesn't name, so a new `*_stmt` without a
matching branch there sends its hits to `/tasks/<some other id>` and a "task
not found" screen. That is exactly what article hits did between the
knowledge base shipping and the changelog being added — see the changelog
section. `SearchHit["kind"]` has to grow too, or TypeScript won't catch it
either.

**The new-task dialog's duplicate check is `tasks_stmt` called directly, not
`search()`.** `GET /tasks/similar` reuses the exact same access-scoped
fuzzy-title statement the search palette uses, skipping the two other kinds
`search()` also checks — a duplicate task isn't a duplicate project or a
duplicate note, so there's no reason to fetch either. `snippet()` (formerly
private, promoted the same way `recurrence.advance` was — a second real
caller is what that promotion is for) formats the match the identical way a
palette result reads. **A failed check must never block creating the task**
— it's a courtesy, not a gate the feature depends on — so the frontend
treats a network error identically to "nothing similar found" and lets the
task through. The confirmation itself is click-Create-twice, not a second
dialog: the first press that finds something shows what it found and stops:
the *second* press — button now reading "Create anyway" — is the
confirmation, the same "say it again to mean it" shape as the delete
dialogs elsewhere, minus the retyping, because a title is not a name someone
picked on purpose the way a project's is.

**A long, unbroken duplicate-task title could push the whole dialog wider
than its own `max-w-sm` — two separate `min-width: auto` floors stacked on
top of each other, not one bug.** `NewTaskDialog`'s "Similar tasks already
exist" box renders each match as `<a className="flex ...">` wrapping a
`<span className="truncate">`; a flex *item* defaults to `min-width: auto`,
which floors it at its own content's natural width regardless of
`truncate` — the ellipsis CSS never gets the chance to apply, because the
box refuses to shrink small enough to need it. That alone was fixed with
`min-w-0` on both the `<a>` and the inner `<span>`. But `DialogContent`
itself is `display: grid` (Base UI's own markup), and its direct child —
the plain `<div className="space-y-4">` wrapping the entire dialog body —
is *itself* a grid item with the identical default floor. Fixing only the
inner flex left the outer grid item overflowing the dialog's box by
hundreds of pixels regardless, invisible without checking a computed style
because `max-width` still clamped the dialog's own rendered box — the
overflow was the *content* silently spilling past it, not the dialog
itself growing. `min-w-0` was needed at both levels; a single flex or grid
item without it anywhere on the path from a long string up to a
width-constrained ancestor is enough to defeat every `truncate` below it.

On the client, `components/search-palette.tsx`. Three things there are load-
bearing and easy to delete by accident:

- **Requests are aborted *and* sequence-checked.** Eight keystrokes are eight
  requests that can return in any order; without the monotonic guard a slow
  answer for "ant" overwrites the fast one for "antifoul". Invisible on
  localhost, constant on a real connection. There is a browser test that
  injects latency to prove it.
- **Old results stay while new ones load.** Clearing on every keystroke makes
  the panel strobe.
- **"Nothing matches" only after a settled search**, never mid-flight.
