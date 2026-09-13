---
paths:
  - "apps/api/src/app/services/books.py"
  - "apps/api/src/app/services/articles.py"
  - "apps/api/src/app/models/knowledge_base.py"
  - "apps/api/src/app/api/routers/knowledge_base.py"
  - "apps/web/src/views/KnowledgeBase.tsx"
  - "apps/web/src/views/Book*.tsx"
  - "apps/web/src/views/Article*.tsx"
  - "scripts/e2e-kb.sh"
---

# The knowledge base: books, articles, revisions

## The knowledge base

Read `services/books.py` and `services/articles.py`. Book → article, with
every edit kept as history — a runbook or a policy is durable reference
material, the thing this product had no place for before it existed.

**A book's access model is a project's, unchanged.** `models/knowledge_base.py`'s
`Book`/`BookMember` are near-mechanical copies of `Project`/`ProjectMember` —
owner + grants to a person or a team at `read`/`write`, org admins see
everything, private until shared. `services/access.py`'s `book_level_expression`
and `visible_books_stmt` are the identical copies, and `AccessPanel` (already
generalized to a `basePath` prop for tasks) is reused for books with zero
changes — the third resource to prove that generalization was worth doing.

**`is_private` is both the draft flag and the privacy flag — one boolean, not
two independent dimensions.** An article is born private, and only its owner
can publish it (`can_make_private`, the article-level twin of `can_hide`).
Turning it back on un-publishes it. `effective_article_level` short-circuits
on `is_private` **ahead of** the whole book-access expression, line for line
the same shape `effective_task_level` uses for `is_hidden` — which means
**organisation admins can't see a private article either**, the identical
deliberate hole hidden tasks already carry. `article_level_expression` is the
SQL mirror, proved to agree with the Python function through Postgres by
`scripts/e2e-kb.sh` exactly the way `test_access_matrix.py`'s own docstring
explains for tasks.

**A revision is a whole editing session, not a keystroke — this is the one
place the design had to go further than what was literally asked, to make
"attachments attach to a revision" buildable at all.** `start_editing_session`
resolves the latest revision (`id DESC LIMIT 1`, UUIDv7 sorting chronologically
for free — no `position` column, the same convention checklists and sheets
already use) and either hands it back **mutable** (same person, within
`SESSION_IDLE_WINDOW`) or seeds a fresh row from its title/body and freezes
the old one into history. Every autosave (`autosave_revision`) updates that
one row in place; the endpoint 409s if it's been superseded, the same
"you're editing a stale copy" signal a real conflict would eventually need.
`_latest_revisions` (`services/articles.py`) batches this per page with the
identical `ROW_NUMBER() OVER (PARTITION BY …)` + `aliased(Entity, subquery)`
shape `access.board_stmt` already uses to bound a board column — manually
reconstructing an ORM row from raw subquery columns was tried first and
abandoned before it shipped, because it can't handle a `Computed` column
like `body_text` correctly.

**Rendering a body resolves `data-attachment-id` by attachment id and the
*article's* access, not by exact revision match.** A session's body is
copied forward from the previous one, so a later revision can still
reference an image an earlier revision technically owns —
`attachments_service.image_urls_for_article` scopes the lookup to "any
revision of this article," not just the one being rendered, which is what
makes reopening an old entry in History still show its pictures.
`services/richtext.py` needed zero changes: it already resolves by id and
tolerates one that doesn't come back, the identical graceful-degradation a
task description gets for a deleted attachment.

**Attachments anchor to a specific `ArticleRevision`, a third anchor on the
one `attachments` table** (`ck_attachments_one_anchor` widened to
`num_nonnulls(task_id, conversation_id, article_revision_id) = 1`). The
Files panel is scoped to the revision being *viewed* — a fresh session
starts with none, and an old revision in history shows exactly what was
attached to it at the time — a deliberately narrower promise than inline
images get, and the honest reading of "attached to revision" for a panel
that isn't dealing with copied-forward content. Confirming an upload reuses
the **one shared** `POST /organisations/{id}/attachments/{id}/confirm`
route in `conversations.py` rather than a second confirm endpoint: `_anchor_of`
grew one more branch (resolve the revision, then `articles_service.context_for`
on its article), the same generic-dispatch shape it already had for a task
versus a conversation.

**`components/task-files.tsx` became `components/files-panel.tsx`, and
`FilesPanel` takes a `basePath` prop instead of a `taskId`** — the identical
one-prop generalization `AccessPanel` went through, for the identical
reason: a second real caller. `RichTextEditor` got the same treatment
(`taskId` → `basePath`, plus an optional `noun` for its hint copy) so a
pasted screenshot in the article editor stages to
`${basePath}/files` regardless of which resource that is. `TaskFile` (the
type) is now `FileItem` with `from_comment` made optional, since an article
revision has no comment thread to have arrived from.

**Generalising a component is not a licence to generalise its copy, and
this one cost six browser tests to learn.** The first version of
`FilesPanel` dropped the noun out of the two user-facing strings that had
one — `aria-label="File to add to this task"` became `"File to add"`, and
the drop overlay's "Drop to attach to this task" became "Drop to attach" —
on the reasoning that the panel no longer knows it's a task. Both are
worse copy on their own terms: an accessible name of "File to add" tells a
screen reader nothing about what it attaches to, which is the one thing
that label exists to say. They also broke `task-ux.spec.ts` (×3),
`realtime-task.spec.ts` and `drag-drop.spec.ts` (×2), every one of which
addresses those controls by exactly that wording — and none of it showed
up until the browser suite was next run, several commits later, because
neither `pnpm typecheck` nor any HTTP suite can see a string. `FilesPanel`
now takes the same `noun` prop `RichTextEditor` already had, defaulting to
`"task"`, so the task screen's strings are byte-identical to what they
always were and `ArticleDetail` passes `noun="article"`. **When a shared
component swallows a caller-specific word, give it a prop, not a
shrug** — and run `./scripts/e2e-browser.sh` after any refactor that
touches copy, because it is the only suite that reads it.

**A nav item can break a test three screens away.** Adding "Knowledge base"
to the rail made `tags.spec.ts`'s `getByText("Knowledge base")` — asserting
a tag chip had been created — match two elements and fail on strict mode.
The product was right and the locator was loose; it now asserts on the
chip's own `Remove tag Knowledge base` button, which can only ever be the
one thing meant. Same family as the toast-title-versus-history-line trap
below: any bare `getByText` for a word that could plausibly become a nav
item, a heading or a button label somewhere else is a test waiting to fail
for a reason that has nothing to do with what it's testing.

**No locking: silent last-write-wins**, same as everything else in this
product that isn't explicitly collaborative — two people editing the same
article is not a case this design tries to prevent.

**Search matches only the current revision's text**, the same "search the
live content, not history" rule a task description already follows.
`search.articles_stmt` joins to the latest revision per article through a
correlated scalar subquery (`ORDER BY id DESC LIMIT 1`, the identical
shape `_inherited_project_rank` demonstrates elsewhere) and reuses
`article_level_expression` for the WHERE clause — the vanish-from-contents
behaviour and search agree by construction, not by a second, separately
maintained check. `body_text` is `article_revisions`' own generated column,
mirroring `tasks.description_text` stripped-HTML-for-search contract
exactly, down to the same `regexp_replace` DDL from migration 0015.

**`book_shared` is one more notification kind, wired the way `task_shared`
actually works — not the way `project_shared` turned out to.** Sharing a
project fires no notification at all today; `KIND_PROJECT_SHARED` is a
constant in the closed set with no `notify()` call anywhere behind it. That
looks like a plan that was never finished rather than a design decision, so
`services/books.py::grant` was wired to notify a directly-granted user, the
same shape `tasks_service.grant` already uses (never on a team grant, never
when granting to yourself) — matching what a "book_shared" notification
should plainly do, not perpetuating a gap it happened to inherit by naming
convention. No notification for publishing or privatising an article: the
owner's own action on their own thing, the same "no notification on
generation" reasoning recurring tasks already document.

**A real bug found only by curl-testing the routes, not by reading them:**
the router's own `prefix="/organisations/{org_id}/kb"` combined with six
routes each additionally hardcoding a leading `/kb/articles/...` or
`/kb/revisions/...` — doubling the segment to `.../kb/kb/articles/...`,
404ing every one of them. Ruff, mypy and the unit suite all passed; nothing
short of an actual HTTP request against the live path would have caught it,
which is why Phase 3 of this feature's build order was "curl-test before
moving on" rather than "trust the code review."

**`ArticleOut` shipped once without an `access` field, and the frontend had
no way to decide whether to render the editor or a read-only view without
it** — `BookOut` already carried `access: str`, and the article schema's
own author (also this session) simply forgot the identical field on its
sibling. `_article_out()` already threaded a `level` parameter through
every one of its four call sites for the `can_make_private` computation;
the fix was one more field on the response, not a second lookup.

**The frontend autosave cannot reuse the notepad's own "send only the
changed field" shape**, and copying it verbatim would have shipped a bug:
`services/personal_notes.py`'s `PATCH` is a genuine partial update, but
`autosave_revision` always overwrites both `title` and `body` unconditionally.
Sending only the just-changed field — the notepad's own pattern — would
silently blank out whichever field a stale closure over React state hadn't
just touched. The fix is a `titleRef`/`bodyRef` pair updated synchronously
inside `queueSave`, so a debounced `save()` always sends the *current* value
of both fields regardless of which one triggered it, not a value captured
when the callback was created.
