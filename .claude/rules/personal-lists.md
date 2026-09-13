---
paths:
  - "apps/api/src/app/services/personal_notes.py"
  - "apps/api/src/app/services/sparks.py"
  - "apps/api/src/app/services/bookmarks.py"
  - "apps/api/src/app/services/changelog.py"
  - "apps/api/src/app/models/personal_note.py"
  - "apps/api/src/app/models/spark.py"
  - "apps/api/src/app/models/bookmark.py"
  - "apps/api/src/app/models/changelog.py"
  - "apps/api/src/app/api/routers/bookmarks.py"
  - "apps/api/src/app/api/routers/changelog.py"
  - "apps/api/src/app/api/routers/sparks.py"
  - "apps/api/src/app/api/routers/personal_notes.py"
  - "apps/web/src/views/Notepad.tsx"
  - "apps/web/src/views/Sparks.tsx"
  - "apps/web/src/components/spark-capture.tsx"
  - "apps/web/src/views/Bookmarks.tsx"
  - "apps/web/src/views/Changelog.tsx"
  - "scripts/e2e-notepad.sh"
  - "scripts/e2e-sparks.sh"
  - "scripts/e2e-bookmarks.sh"
  - "scripts/e2e-changelog.sh"
  - "e2e/tests/bookmarks.spec.ts"
  - "e2e/tests/changelog.spec.ts"
---

# The notepad, sparks, bookmarks and the changelog

## The notepad

Read `services/personal_notes.py`. Free-form notes, scoped to an
organisation, with a title, a body, timestamps and a delete button — a
different shape from `services/notes.py`'s private task note, and
deliberately so. That module's own docstring explains why a task note stays
a single field with no title, no list, no delete: "a list would grow a
timestamp, an author, a delete button... and would arrive at being a second
comment thread." The notepad **is** that list, on purpose — it isn't about
any one piece of work, so it needs the title and the list to be findable
again later. Same organisation-scoped nav tier as Tasks, Planner and
Calendar, not tucked under Account or Reminders.

**Only the author, ever — the identical absence-of-a-branch discipline.**
Every statement in `services/personal_notes.py` filters on `user_id == the
caller`, full stop, not even for an organisation admin. `get_or_404` also
filters on `organisation_id == ctx.organisation.id`: without that half, a
note made in one organisation could be edited or deleted through a
*different* organisation's URL by the same person — invisible to anyone
else, but still the wrong organisation's notepad reaching into another
one's. `scripts/e2e-notepad.sh` has a dedicated case for exactly that.

**Autosaved, no Save button** — the identical trade `PrivateNote` already
made for the task-scoped version: a button turns a scratchpad into a form
you can fail to submit, and the failure mode is losing the thought you were
trying to keep.

**Title and body share one debounce window, not two independent timers.**
The first version queued each field's own `setTimeout`, and typing in one
field cleared and replaced the *other* field's pending timer without saving
it — silently dropping whichever field wasn't touched last. `pending.current`
merges every queued field into one object; a single timer flushes all of it
in one `PATCH`.

**Closing the dialog has to flush the pending debounce, not just cancel
it.** Escape, the corner X and a backdrop click all unmount the editor, and
the original cleanup effect just cleared the timer — silently discarding
the last few keystrokes typed before closing. `flush()` is what both the
unmount cleanup and every field's `onBlur` call now: it cancels the timer
and immediately fires the save with whatever's still pending, so a save in
flight is never abandoned, only ever completed early.

**The card and its Delete button can't both be `<button>` elements.** A
`<button>` nested inside a `<button>` is invalid HTML — found because a
Playwright role query for "Delete {title}" matched both the outer card
(whose computed accessible name concatenates its own text with the nested
button's) and the real button, which is exactly the kind of ambiguity that
also confuses the browser's own click handling. The card carries `role=
"button"` on a plain `<div>` (via `Card`'s own prop passthrough) with
`tabIndex`/`onKeyDown` for keyboard access instead, and Delete's own click
handler stops propagation rather than relying on DOM nesting to isolate it.

**The editor is almost full screen, not the default small centered
`Dialog`.** A notepad is somewhere you actually write, and the default
`sm:max-w-sm` box fought that — `DialogContent` gets a large className
override (`h-[90vh] sm:max-w-4xl flex flex-col`) with the body `Textarea`
as `flex-1` instead of a fixed `rows={10}`, so it claims whatever height
the title and footer don't need. Two things worth knowing if this is
touched again: `DialogContent`'s corner close button is absolutely
positioned (`top-2 right-2`) against the *outer* popup, not the header, so
the header needs its own `pr-12` or a long title's text runs under it; and
`Textarea`'s default `field-sizing-content` (auto-grows to fit its own
text) has to be overridden to `[field-sizing:fixed]` or `flex-1` never
actually gets to claim the space — the two sizing modes fight for the same
axis.

**`flush()`-on-unmount only covers closing the dialog *within the app* —
Escape, the X, a backdrop click. A hard reload or closing the tab tears
down the whole JS context immediately, with no React unmount lifecycle at
all**, so a debounce armed but not yet fired is lost with it, silently.
Found by a test that filled the body and reloaded immediately, mirroring
exactly what a real hard refresh does. There is no way to *guarantee* a
`PATCH` completes from a `beforeunload` handler, so the fallback is the
standard one any autosaved editor uses instead: warn before leaving while
`pending.current` or the debounce timer is non-empty, the same native
"leave with unsaved changes?" prompt any editor shows. It doesn't fix the
race — it gives the person a chance to not trigger it.

## Sparks

Read `services/sparks.py`. Quick capture — an idea, a link, anything not
worth a task yet — reachable from any screen with ⌘J (Ctrl+J), typed into a
dialog, saved, and you're straight back to whatever you were doing. Review
and edit what piles up on `/sparks`.

**Deliberately not the notepad, and not a task note.** The notepad's own
docstring already explains why a task note stays a single field with no
title, no list, no delete — a spark is that same shape *as* a list, one
step further than the notepad in the other direction: no title either, one
field, because a second field to fill in is friction a capture tool exists
specifically to avoid.

**Cross-organisation, unlike the notepad.** The whole point is catching a
thought regardless of which organisation happens to be open when it
strikes — `services/sparks.py` carries no `organisation_id` at all, and
`GET/POST /sparks` sit at the bare root next to the inbox and reminders,
not under `/organisations/{id}`. The ⌘J hotkey and its header button are
bound at the shell level with no `railOrg` guard, unlike search and "New
task" beside them — pressing it on the bare "Your organisations" screen
with zero organisations yet still works.

**Only you, ever — no sharing, no admin override.** The identical
absence-of-a-branch discipline `services/notes.py` and
`services/personal_notes.py` already hold for their own private data:
every statement filters on `user_id == the caller`, full stop, and
`get_or_404` (edit, delete) 404s on somebody else's spark rather than 403 —
its existence is not something you're being told about.

**The filter box on `/sparks` is client-side**, the identical call the
Projects list already makes for its own name filter — this was never a
paged fetch to begin with, so narrowing what's on screen doesn't earn a
round trip. This was also the resolved answer to "should search work with
these": a personal capture list search stays local to its own screen
rather than joining the org-scoped ⌘K palette, which has no cross-
organisation case to handle for anything else it searches.

**Capturable over MCP too, and from the menu bar app.** `create_spark`
(`app/mcp/server.py`) is one argument and no organisation id, the same
shape as this screen's own dialog — see the MCP section. It exists because
the `ayeaye-menubar` app is the same idea as ⌘J in a different place: a box
that appears under a keystroke, and until it had this tool everything typed
into it had to become a task whether or not there was anything to do yet.

**Bare URLs are linked, not sanitised.** A spark's body is plain text, not
the sanitised HTML a task description is — there's no rich editor and
nothing here is ever rendered with `dangerouslySetInnerHTML`. `Linkified`
(`views/Sparks.tsx`) splits on a URL-shaped regex and turns only the
matched segments into real `<a>` elements; every other segment is still a
plain React text node, escaped the same as the whole string would have
been. Safe by construction, not by an allow-list — there is no markup to
sanitise because none is ever parsed as markup.

**Editing a card is a click, not a second screen.** No dialog, no
autosave-with-a-debounce like the notepad's own editor — a spark is short
enough that click-to-edit, then blur or ⌘Enter to commit, Escape to
cancel, is the whole interaction. `SparkCard`'s local `body` state resets
from `spark.body` whenever a fresh row lands (a save from elsewhere, or the
initial load), the same "the prop changed under us, not what we're
mid-typing" reasoning the notepad's own editor documents for its `note.id`
dependency, just keyed on the value here since there's no id-per-dialog
instance to key on instead.

## Bookmarks

Read `services/bookmarks.py`. The organisation's own shelf of links — the
staging URL, the shared drive, the supplier's portal — with a description, an
order, and a pin. `/orgs/{id}/bookmarks`, its own rail item under Knowledge
base, because both are reference material you go to on purpose.

**Shared, which is the one thing here unlike everything in the two sections
above it.** Sparks and the notepad are lists only their author ever reads;
this is a list every member reads, in the same order. That is also what makes
`position` worth storing at all: an order nobody else sees is a preference,
not a shelf.

**Three bars, deliberately different from each other, and that is why
`scripts/e2e-bookmarks.sh` needs four accounts.**

- **Reading and adding is ordinary membership.** No grants, no per-row
  visibility — `CurrentOrg` is the whole check, and `list_stmt` is one
  statement with no access expression in it. This is the only
  organisation-scoped resource in the product with nothing finer than
  membership to resolve, which is why that builder looks too simple next to
  `access.visible_tasks_stmt` and is nonetheless right. A shelf only an
  admin may add to is a shelf that stays empty.
- **Editing and deleting is whoever added it, or an org admin.** The
  ordinary shape everywhere else — your own thing, plus the escape hatch.
  Only testable between two *plain members*: a member must not be able to
  rewrite a colleague's link, and a single-account test reports that as
  working.
- **Pinning is the organisation's `owner`, and not even an admin.** A pinned
  link is what the whole organisation sees first, and that was asked for as
  an owner's call. Note the direction — this is **narrower** than admin, not
  wider, so it cannot be expressed by reusing `can_manage_members`;
  `organisations.can_delete_organisation` is the existing precedent for an
  owner-only capability and `can_pin` is its sibling, kept in
  `services/bookmarks.py` rather than beside it because it is a rule about
  bookmarks, not about membership. It is the second owner-only thing in the
  product, and the only one that isn't destructive.

**Reordering is member-level, unlike editing the same row.** Moving somebody
else's bookmark up the list is what tidying a shared list means, and it
changes nothing about the bookmark itself. Pinning is untouched by it: a
pinned row sorts ahead of every unpinned one whatever its position, so no
member can drag a link past a pinned one — asserted in the e2e suite rather
than left to reasoning, because it is the one place the two rules meet.

**Pinning and editing each get their own route, for opposite reasons.**
`POST .../pinned` exists because it is a *higher* bar than the `PATCH` (the
same reason `POST /tasks/{id}/closed` is its own route when only the owner
may close) — a `pinned` field on `BookmarkUpdate` would mean one endpoint
answering 403 for one field and 200 for another in the same request.
`POST .../position` exists because it is a *lower* one: folding it into the
`PATCH` would either lock members out of tidying the list or let them
rewrite a colleague's URL.

**`created_by_user_id` is `SET NULL`, which is why
`organisations._reassign_everything_owned_by` needed no bookmark branch.**
`projects.owner_user_id` and `tasks.owner_user_id` are RESTRICT because a
thing with no owner is a thing nobody can administer, so that function has
to find a departing colleague's work a new home. A bookmark has no owner —
only somebody who happened to type it in — and stays administrable by the
organisation's admins regardless, so removing them succeeds and the link
stays on the shelf, still saying who added it. `scripts/e2e-bookmarks.sh`
asserts exactly that rather than leaving it to reasoning.

The NULL itself only arrives when the *account* goes, not when somebody
leaves an organisation — and the consequence is worth knowing: an orphaned
bookmark is editable by admins alone, so `can_edit` must never let a NULL
author compare equal to the caller. `tests/test_bookmark_rules.py` pins that
specifically.

**The `User` join in `list_stmt` is an OUTER join and has to stay one**, for
the same reason: an inner join silently drops every orphaned row out of the
organisation's list.

**A URL is normalised before it is stored, and that is a security boundary
rather than tidiness.** Every row renders as a real `<a href>`, so a stored
`javascript:` URL is stored XSS waiting for the next colleague to click it.
`normalise_url` is an allow-list of exactly `http` and `https` — the same
allow-list-not-block-list reasoning `services/richtext.py` applies to
markup — and it supplies `https://` when somebody types a bare hostname,
because without a scheme that href is *relative* and navigates inside the
app instead of out to the site. Two things about it are non-obvious:

- **A naive `^\w+:` scheme pattern is wrong on real input.** RFC 3986 allows
  dots and digits in a scheme, so `example.com:8080/admin` parses as the
  scheme "example.com" and `localhost:3000` as "localhost" — both then get
  refused as "not http", and both are ordinary things to paste in.
  `_scheme_of` requires *no dot in the candidate* **and** *no port number
  after the colon* before it believes it has found a scheme. Found by a unit
  test, not by a person.
- **A URL that is too long is refused, not truncated.** Truncating one
  produces a link that goes somewhere else, which is worse than saying no.

**`description` is the row's label, and there is deliberately no second
`title` field.** The list renders the description as the link text and falls
back to the URL when it is blank, so there is nothing to keep in step with
anything. Blank and absent are one state (`server_default=""`), the same call
`services/notification_channels.py` makes for a blank email override.

Two things on the frontend are worth knowing before touching it:

- **Pinned rows are their own list, not a flag on one long one, and that is
  a correctness point rather than a layout preference.** The server sorts
  every pinned row ahead of every unpinned one whatever its position, so a
  single sortable list would let somebody drop an unpinned row above a
  pinned one and watch it snap straight back on the next load. Two
  `SortableContext`s, and dragging never crosses them — the way a row
  changes group is the pin button. The Pinned heading only exists when
  something is in it, which is also how a non-owner (who gets no pin button
  at all, the usual "don't show a control that 403s" rule) can still see
  *which* links are pinned.
- **The delete button says "Delete X", not "Remove X", and that is a test
  fix living in the product's copy.** Playwright's `getByRole` name matching
  is case-insensitive **substring** by default, and "Remove X" literally
  contains "move X" — so it resolved to the same locator as the drag
  handle's own "Move X" and every reorder test failed on strict mode. Same
  family as the "Priority: Normal" trap below, and cheaper to fix in one
  label than in every test that reaches for a grip handle. "Delete" is the
  word the notepad and Sparks already use for this anyway.

Reordering is drag-and-drop through `@dnd-kit`, the Planner's own dependency
and its own grip-handle split (only the grip carries the listeners, so
following a link and moving a row never fight over the same click).
`bookmarks.spec.ts` drives it through the **keyboard** sensor for the reason
`planner.spec.ts` documents — dnd-kit's pointer sensor is genuinely flaky to
script, and its collision state lands on the next animation frame rather
than synchronously with the keydown, so each key needs a short pause after
it.

**Not searchable from ⌘K, and no MCP tool — neither was asked for.** Adding
either is one more `*_stmt` in `services/search.py` or one more tool in
`app/mcp/server.py` respectively; both would be additive, and neither is
pretended at anywhere in the code.

## The changelog

Read `services/changelog.py`. The organisation's dated record of what
happened — "BingAds version lift", "switched the feed to the new endpoint".
Three fields and no more: the date it happened, a description, and who wrote
it down. `/orgs/{id}/changelog`, its own rail item under Bookmarks, because
both are reference material you go to on purpose.

**Two dates, and conflating them would be the whole bug.** `happened_on` is
what is being recorded; `created_at` is when somebody typed it in. Tuesday's
version lift routinely gets written down on Thursday, and a log that can only
say Thursday is a log of when people remembered rather than of what happened.
The list groups by `happened_on` and states each date once; a redated entry
therefore belongs under a different heading, which is why the frontend
reloads after an edit that moved the date rather than patching the row where
it sits.

**It is the bookmark shelf's first two bars, and deliberately not its
third.** Reading and adding is ordinary membership — `CurrentOrg` is the
whole check and `list_stmt` carries no access expression at all, because a
log only an admin may write to is a log that stays empty, and an incomplete
history is worse than none since people believe it. Editing and deleting is
whoever recorded it, or an org admin (403, never 404 — every member can see
the entry). There is **no pinning and no reordering**: a shelf of links has
no inherent order so one is worth storing, but a log's order is its dates,
and dragging an entry above one that happened after it would let the list lie
about the sequence — which is the one thing a changelog is for. So there is
no `position` column here, unlike `bookmarks`.

**Paged, also unlike bookmarks, and that is the difference between a shelf
and a log.** A shelf is curated and stops growing; a changelog is append-only
by nature. `limit`/`offset` with `X-Total-Count`, and **no default limit** —
the same call `/tasks` makes, and a silent cap on a *history* is the worst
place for one.

**`happened_on` defaults to the caller's own today, never the server's** —
`reminders.today_for` reused rather than re-derived, because a date has no
timezone and anyone west of London recording something in the evening would
otherwise file it under tomorrow. `lib/format.ts`'s `isoDate` is the
browser's half of the same rule, promoted out of `views/Calendar.tsx` when
this screen became its second real caller: `toISOString()` converts to UTC
first and slides the day near midnight.

**The description is plain text and stays plain text.** Nothing renders it
with `dangerouslySetInnerHTML`, so unlike a task description there is nothing
to sanitise — the same safe-by-construction position Sparks holds. Storing
HTML here would create a trust boundary this feature hasn't got. It is
**refused rather than truncated** when too long, the same call
`bookmarks.normalise_url` makes for a long URL: an entry cut in half says
something other than what was written.

**`created_by_user_id` is `SET NULL`**, so like bookmarks this needed no
branch in `organisations._reassign_everything_owned_by` — an entry has no
owner, only somebody who happened to record it. The `User` join in
`list_stmt` is therefore an **outer** join and has to stay one: an inner join
would silently drop every orphaned row, quietly editing the organisation's
own history, which is the one thing this table exists not to do.

Two things on the frontend are worth knowing before touching it:

- **The add dialog is keyed by an open counter, not reseeded by an effect.**
  `openSeq` bumps on every open so a fresh instance mounts, which is what
  makes the date today *every* time you open it without anything ever
  writing over a field somebody is already typing into — the same "a
  different thing is a different component" idiom `Keyed` in `main.tsx`
  uses for detail routes.
- **The empty state must not quote the dialog's own placeholder.** It did at
  first — both said "BingAds version lift" — and every assertion on that
  phrase matched two elements. The placeholder is the more useful home for
  the example, since it is in front of you while you type. Same family as
  the "Knowledge base" nav-item collision already recorded below.

**Searchable from ⌘K, and the one `*_stmt` in `services/search.py` with no
access expression in it.** That is right rather than an omission: a changelog
entry has no per-resource visibility to resolve, so membership — already
established by `ctx` — is the whole check, and inventing a `level >
NO_ACCESS` here would be a second answer to a question the feature doesn't
ask. `changelog_stmt` maps an entry onto the `Hit` shape the palette already
renders: **the title is the description's first line** (`split_part`, because
an entry has no title of its own — the description *is* the content) and
**the date is the context**, where a task's project name goes. No subtitle:
for a one-line entry it would repeat the title word for word. The score is
computed over the whole description, so a match three lines down still
surfaces the entry. Migration 0047 adds the `gin_trgm_ops` index that keeps
it an index lookup rather than a scan over what is likely to be the longest
table a self-hoster has after a few years.

**A hit lands on the log carrying the query that matched it**
(`/orgs/{id}/changelog?q=…`), because a changelog entry has no screen of its
own — it is a row in a list. That only works because the list filters with
the **same** `search_service.matches`, not a second ILIKE written in
`services/changelog.py`: two different predicates would mean a link that
arrives at a log not containing the row it promised. The filter is
server-side, unlike the Projects list's own name filter, for the ordinary
reason — this list is a page, so filtering in the browser would only narrow
the page it happens to be holding. `X-Total-Count` goes through the same
predicate, or "Showing 5 of 312" would count the whole log while showing a
filtered page of it. `_matches` became public `matches` for this: the same
promotion `snippet` and `recurrence.advance` already went through when a
second real caller turned up.

**Wiring the palette for it surfaced a bug that had been there since the
knowledge base shipped.** `search-palette.tsx`'s `go()` routes `project` to
the projects screen and **everything else to a task URL** — so when
`articles_stmt` was added to `search()`, every article hit navigated to
`/orgs/{id}/tasks/<an article id>` and landed on "task not found".
`SearchHit["kind"]` was still `"task" | "project" | "note"` too, so
TypeScript never noticed. Both fixed, and `search.spec.ts`'s "an article hit
opens the article, not a task URL" pins it. The lesson for the next kind:
**`go()` has to name every kind `search()` can return**, because its fallback
is a task URL rather than an error.

**Two MCP tools, `changelog` (read) and `record_change` (write).** The read
one takes an optional `query` — the same matcher again — and says what its
page is a page *of* when there is more, the text equivalent of
`X-Total-Count`. `record_change`'s own docstring leans on `happened_on`
hard, because an assistant told "we lifted the BingAds version on Tuesday"
on a Thursday will otherwise file it under Thursday, which is precisely the
mistake the column exists to prevent. Both refuse through `Denied` rather
than letting a service's `HTTPException` become a crash with its text
withheld — the length and emptiness checks are pre-validated here for
`create_spark`'s own documented reason. There is deliberately **no edit or
delete tool**: correcting a log is a person's judgement about their own
record, and the two tools that exist cover what was actually asked for.
