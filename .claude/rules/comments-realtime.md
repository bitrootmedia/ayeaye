---
paths:
  - "apps/api/src/app/services/conversations.py"
  - "apps/api/src/app/services/mentions.py"
  - "apps/api/src/app/realtime/**"
  - "apps/api/src/app/models/conversation.py"
  - "apps/api/src/app/api/routers/conversations.py"
  - "apps/web/src/components/comment-thread.tsx"
  - "apps/web/src/components/mention-textarea.tsx"
  - "apps/web/src/hooks/use-realtime.ts"
  - "scripts/e2e-comments.sh"
  - "e2e/tests/comments.spec.ts"
  - "e2e/tests/realtime-task.spec.ts"
---

# Comments, mentions and the realtime socket

## Comments and realtime

Read the `services/conversations.py` docstring. **Comments are the conversation
system, not a second one** — that is the product decision, and it is what makes
attachments, voice notes and the unread badge one implementation when they
arrive. Do not add a `task_comments` table.

A thread has **no access rules of its own**: who can see it is who can see its
anchor. One rule rather than two, and revoking access to a task revokes its
discussion with it. `read` is enough to post — a comment is a contribution, not
a change to the work, and the commonest reason to share something read-only is
to get somebody's input. Editing stays with the author or an org admin; **the
task owner is not special here**, which is only testable between two plain
members.

**A comment can switch who's action-required, but that is `write`, not
`read` — a second bar on the same endpoint, not a relaxation of the first.**
`MessageIn.action_required_user_id` on a task-anchored comment defaults to
`None`, and `None` means *no change*, never "clear it" — a composer that
silently un-assigned a task because nobody touched the picker would be a
trap wearing the shape of a feature. `comment_on_task` runs
`tasks_service.update()` (the identical call the task screen's own picker
makes, so the transition-only notify rule and the `task_events` row are the
same code, not a second implementation of them) **before** it posts the
comment, deliberately: if a read-only commenter somehow reaches this — the
UI's own gate is `people.length > 1` on write access, but the server does not
trust that — the whole request 403s and nothing posts, rather than leaving a
comment that claims a reassignment its own request body couldn't make good
on.

**A comment can say what posted it, without changing whose it is.**
`messages.via` holds the name of the credential that wrote it — attribution,
not authorship, since an assistant posts *as* the person whose token it
holds. NULL for everything typed in the web app, which is nearly everything.
See the MCP section for where the name comes from and why the column is
here rather than on `task_events`.

**The socket has two audiences, and conflating them was a bug.**

- **Who to notify** — a small, stake-holding set: the owner, whoever must act,
  anyone who has already spoken. Deliberately not "everyone who can see it":
  org admins can see everything, and mailing them every comment in the company
  is how notifications get turned off.
- **Who to update live** — anyone with the thread *on screen*. A read-only
  colleague reading along has no stake worth notifying but their view must
  still move. Clients send `{"watch": {"kind": "task", "id": "…"}}` and the
  server checks access **at watch time**, once per thread opened rather than
  once per message per socket.

That check being early is safe because **events carry no content** — only
"conversation X moved". The client refetches, so there is one authorisation
path for message bodies; if access was revoked in between, the refetch 404s,
which is the right answer.

**The socket is authenticated by the session cookie**, which single origin
gives us for free. The reference project had to pass an access token in a query
string — where it lands in server logs and browser history — precisely because
its apps were on other origins. Note `#HttpOnly_` when reading a curl cookie
jar in a test: skipping every line starting with `#` drops exactly the session
cookie.

**A native client gets in with a personal access token instead**, in an
`Authorization` header on the handshake, resolved through the same
`tokens_service.authenticate` path `/mcp` uses. It can do that precisely
because it is not a browser: the WebSocket API in a browser cannot set
request headers, which is the entire reason query-string tokens exist as a
pattern — so nothing here needs one, and the token never touches a URL.
**Any valid token is enough; there is no write check.** Watching is reading,
a read-only token is exactly the right credential for a status light, and
the events carry no content either way. This is what the macOS menu bar app
(its own repo, `ayeaye-menubar`) uses to watch `org:<id>` and follow
critical tasks live rather than polling.

**Creating a task announces too, and used not to.** `tasks_service.create`
was the one mutation that wrote a task and published nothing — so a board
open on somebody else's screen showed every edit live and stayed silent
about a task *appearing*, which is the change most worth seeing. It calls
`realtime.publish_task_changed` directly rather than `announce()`: announce
also stamps `updated_at` and commits, and a row created two lines earlier
already has both timestamps right. There is nothing to restate, only
somebody to tell.

**The board is live too, but coalesced.** It watches `org:<id>` rather than
every card on it — hundreds of registrations per tab otherwise — and collects
events for 1.5s before refetching, skipping the refresh entirely while the tab
is hidden. The task screen refetches immediately, because it is one task and
one small response; a board is the opposite.

**`updated_at` is "last activity", not "last row update".** A comment, a file,
a tag, an hour logged — none of those touch the `tasks` row, so the column
would otherwise answer a question nobody asks. `announce()` stamps it and
publishes in one call, deliberately: same trigger, same call sites, and
splitting them means somebody adds a seventh kind of change and remembers one.

**A private note never calls it**, and that is the point — a note nobody else
can read must not announce itself through a timestamp everybody can see, which
would leak through the back door exactly what the feature promises to keep.
Reminders are personal in the same way and are left out for the same reason.
`scripts/e2e-tasks.sh` asserts both directions.

**Tasks ride the same channel.** Anything that changes a task publishes
`{"type": "task", "task_id": …}` and the screen refetches — status, priority,
due date, project, tags, files, checklists, sheets, grants, time entries, hide/unhide. Three
things hold it together:

- **`tasks_service.announce()` is called from every mutation, after the
  commit.** There is no single choke point (tags and files are edited from
  their own routers, time from `time_tracking`), so the rule is simply "if it
  writes to a task, it announces". A missing call is a screen that quietly
  stops updating.
- **The client never branches on `change`.** It is there for the log. A screen
  that only refreshes for the kinds it recognises stops refreshing the day
  somebody adds a sixth one, and nothing fails loudly.
- **Losing access arrives as a 404.** Hiding a task pings its watchers; their
  refetch is what discovers the access is gone. That is the no-content rule
  paying for itself — the event says only "task X moved", so it is safe to
  send to someone who may no longer read it.

**One socket per tab, refcounted in `use-realtime.ts`.** A task screen has two
subscribers (the thread and the task), and the socket **lingers 250ms** after
the last one leaves. That is not a micro-optimisation: effects unmount and
remount around a render — twice over in StrictMode — and closing on the exact
moment the count hit zero opened three connections per page and dropped any
event that landed in the gap. It showed up as a change reaching the other tab
*most* of the time.

A test for this is easy to write so that it cannot fail. The first version of
the board test asserted the word "Blocked" appeared — which is a column
heading, on screen either way. It passed while the board was receiving
nothing at all. **Assert on the card's column**, and check a live test fails
when you remove the subscription.

Notification debouncing: a comment notifies only when the recipient has nothing
unread in that thread already. It fails silently in both directions — too eager
and a back-and-forth is one email per line, too lazy and the notification
nobody got is the one that mattered — so `scripts/e2e-comments.sh` tests both
sides of it.

### @mentions — read `services/mentions.py`

Type `@`, choose a name, and that person is notified. Two decisions carry the
whole feature.

**Who can be named is who can see the task — never the organisation's
roster.** Offering somebody with no route into a task would either notify them
about a title they can't open (a task title in an inbox outside the access
model, the thing `services/notifications.py` exists to avoid) or notify nobody
at all, which is worse than no picker. The candidate set applies
`access.effective_task_level` — the **Python** statement of rule 2, the one
`tests/test_access_matrix.py` proves over the whole grid — to each active
member, with every input (task grants, project grants, the teams they name)
fetched once up front. Deliberately **not a third derivation of the rule**:
the reverse question "who can see this one task" can't reuse
`task_level_expression`, which takes a `user_id` literal and an `org_role`
known at build time, and inverting it would mean writing the six routes out in
SQL a second time. Four queries and a pure-Python fold over the roster is the
cheaper honesty — and this is one task, not a list, so the "one statement per
list" rule isn't in play. Teams are expanded to their members, which is the
reason this is its own route (`GET .../tasks/{id}/mentionable`) rather than a
field on `/access`: that response says *how* each person got in and shows a
team grant as the team, which is what the access card renders and the wrong
answer for a picker.

**The comment body is the only record of a mention.** No `message_mentions`
table, no marker syntax: the server resolves `@Name` against the candidates at
post time. One source of truth rather than a body and an id list that can
disagree — the same reasoning `notifications.organisation_id` gives for being
a real column rather than a value parsed back out of a display string, pointed
the other way round, because here the prose *is* the value. Four things follow:

- **Every writer gets mentions**, not just the composer — a comment posted
  over MCP or curl naming somebody notifies them, because nothing in the
  resolution depends on the client having a picker.
- **An edit that adds a name notifies it; one that doesn't, doesn't.**
  `edit()` resolves the old body as well and tells only the difference.
  Without it "I forgot to @ them" is a silent no-op; without the diff, fixing
  a typo is a second nudge.
- **A rename doesn't rewrite history.** The stored text keeps the name that
  was typed, so an old comment stops resolving. A mention is a notification,
  not a link that has to survive forever, and the alternative is markers in
  the prose that render as noise anywhere they aren't parsed.
- **`find_mentions` is a pure function with its own unit test**
  (`tests/test_mention_parsing.py`) — longest candidate wins at each `@` (a
  Sam and a Samantha is the ordinary case), the `@` must not follow a word
  character (so `bob@example.com` in a sentence is an address), and the match
  must end on a word boundary. The access half is proved through Postgres
  instead, the same split `test_access_matrix.py` documents.

**Rule 5 of `services/conversations.py`: a mention skips the unread-run
debounce, and replaces the ordinary notification rather than adding to it.**
Being named is a direct address, and "you already have unread messages in
that thread" is exactly the case where the person still needs telling — it is
why the author typed a name instead of just posting. `KIND_COMMENT_MENTION`
is its own kind for that reason, and the mention loop runs *before* the
debounced one so it can skip anybody already told the specific way. The
notification carries no snippet, matching every other comment nudge: the
title says who wants you and the link says where.

**Adding a notification kind means backfilling `notification_channels.
enabled_kinds`, and this was already broken once.** That column is an
explicit array, filled with every kind that existed when the channel row was
created — so a new kind is *disabled* on every channel that already exists
and its email silently never sends. `book_shared` (0037, six migrations after
channels landed in 0031) never had that backfill and had therefore never been
delivered to anyone whose channel predated it; migration 0045 appends both
kinds where missing. `book_shared` was also missing from
`NOTIFICATION_KIND_LABEL`, which is what builds the Account screen's "which
notification goes where" table — so it had no row and couldn't be configured
either. Both fixed. **A new kind is four places, not one:** the constant,
`NOTIFICATION_KINDS`, the CHECK-constraint migration *plus* the
`enabled_kinds` backfill, and the frontend label map.

**The picker's list renders in flow, below the box — not absolutely
positioned and not portaled.** `Card` sets `overflow-hidden` unconditionally,
which is the bug `EntityPicker` had to portal to escape; in a plain flow the
question doesn't arise. Below rather than above so the caret never moves
under the pointer mid-word. Two more things in
`components/mention-textarea.tsx` are load-bearing: **Enter is intercepted
while the list is open** (the composer sends on Enter, so without it choosing
a name posts a comment reading "@Sam"), and **an option cancels its own
`mousedown`** or the click blurs the textarea first and the name lands at the
wrong offset — the same trap the rich-text toolbar already documents.
`MentionedText` picks the names out of a posted body for display: cosmetic
only, a second and deliberately simpler reading of text the server already
resolved, and safe by construction the way Sparks' own `Linkified` is —
every segment is a React text node, so there is no markup to sanitise
because none is ever parsed as markup.

**Project threads have no mentions**, and the affordance is absent rather
than present and silently doing nothing: no candidate builder, so no picker
and no resolution. `mentions.for_task` has an obvious sibling the day it's
wanted (a project has three routes in, not six); nothing pretends otherwise
in the meantime.

**On a wide screen, Comments gets its own column between Details and the
sidebar — decided in JS, not with a CSS breakpoint alone.** `TaskDetail.tsx`'s
content grid was two items (a main column, a sidebar) with an implicit
single column below `lg`. The first version split the main column into
three DOM children so Comments could sit between Details-through-Files and
History+PrivateNote at `lg`, and move to its own column at `2xl` — each
child carrying its own `col-start`/`row-start` per breakpoint. That shipped
two real bugs before landing on the current shape:

- **The sidebar rendered in an empty-looking cell, nothing in row 1 above
  it.** CSS Grid's sparse auto-placement (the default) tracks one cursor
  for the whole grid, in DOM order, and never backtracks it. History+note
  (child 3, `col-start-1`, no row) wants column 1, finds row 1 already
  taken by Details, and drops to row 2 — advancing the cursor to row 2
  with it. The sidebar (child 4, only a column, no row) then resumes its
  own search *from row 2 onward*, walking straight past the still-empty
  row-1 cell in its own column. Pinning the sidebar and Comments to
  `row-start-1` fixed the visible hole — but:
- **That fix opened a second, worse one: a dead gap between Files and
  History.** Once Details-through-Files, Comments and the sidebar all sit
  in row 1, the row's *auto height* is the tallest of the three — the
  sidebar, by far the longest card on the screen — and CSS Grid stretches
  every item in that row to match. Details-through-Files (a few hundred
  pixels of real content) got stretched to the sidebar's ~1800px, leaving
  the extra space as dead air below Files before History (row 2) even
  started. Two grid rows sharing a track with a much taller sidebar is the
  actual trap; no combination of `row-start` fixes it, because the row
  track's height doesn't care which item is aligned where within it.

The fix that stuck: column 1 is **one single grid item**, always — Details
through Files, then the private note, in one `space-y-4` div, so its
height is governed purely by its own content and can never be stretched
by a taller sibling. `hooks/use-media-query.ts`'s `useMediaQuery` (mirroring
the grid's own `2xl`, hardcoded to the same 1536px — both must stay in
sync) decides, once per render, *where* `<CommentThread>` mounts: inline at
the end of that div (below `2xl`) or as its own sibling grid item, between
column 1 and the sidebar (at `2xl`). It only ever mounts once — never twice
behind a `hidden` class toggled by CSS — because it owns a realtime
subscription and its own thread state; two live copies would double both.
This is generally the shape to reach for when a component needs to change
*DOM position* by breakpoint, not just show/hide or restyle: Tailwind's
responsive classes can express the latter, never the former.

**Comments is a flexible track, weighted above the main column —
`minmax(0,1fr) minmax(0,1.2fr) 22rem`, not the fixed `28rem` it shipped
with.** A fixed column couldn't answer the question actually asked of this
screen: collapsing the rail handed every pixel it freed to column 1 while
the thread — where the reading and the typing happen — stayed exactly as
narrow as before. The weight is also what makes it wider at any given
width (463px rather than 448 at `2xl`, 785 rather than 448 at 1920 with
the rail hidden). The sidebar stays fixed: it's a column of form fields
with a natural width, and stretching those buys nothing. **`minmax(0, …)`
rather than a bare `1fr` on both** — a bare `1fr` is `minmax(auto, 1fr)`,
whose content-based floor one long unbreakable string (a URL in a comment,
an id in a description) is enough to blow past, taking the whole grid into
a sideways scroll.

The trade, stated because it's real and was measured rather than guessed:
at exactly 1536 **with the rail open** there is no slack left, so the
Details column drops to 385px and the rich-text toolbar wraps to two rows.
Every other combination is one row — including 1536 with the rail hidden,
which is the case this change was asked for. Buying that one row back
would mean container queries plus a second breakpoint plus plumbing the
sidebar's open state into the `isWide` decision below, which is a lot of
machinery for a toolbar that wraps gracefully.

**History travels with Comments, through the same `isWide` decision** —
it's the tail of the same conversation (who changed what, beside who said
what), so it's held in a `history` variable and rendered immediately after
`commentThread` in both branches rather than being left stranded under
Files once the thread moves to its own column. That's also what freed the
private note to move up: it is now the last card in column 1 at `2xl`, and
sits directly under Files at every width, which is what lets its reveal
button join the row with the other four (see the Checklists section).

**The order toggle is a client-side reversal of an already-fetched array,
not a second backend query.** `services/conversations.py::list_messages`
already orders by `Message.id` ascending — oldest-first falls out of
UUIDv7 for free, and always has — so there was nothing to add server-side.
`comment-thread.tsx` keeps that as the source of truth and derives
`orderedMessages` by reversing it in memory when the toggle is set to
newest; the toggle itself persists through `lib/view-preference.ts`, the
same brand-free `localStorage` helper board/list and cards/table already
use, under a new `"comment-order"` key. Newest-first also flips which end
of the list a fresh comment scrolls to — `top` when the newest lands first,
`bottom` (the existing behaviour) otherwise — via a second ref that sits
before the `<ul>`, not inside it: an early attempt put it as the list's
first child, which is invalid HTML (`<ul>` may only contain `<li>`), caught
before it shipped rather than by a test.

**A Playwright gotcha worth carrying forward: the composer's own async
clear can outrace the next keystroke, and a one-shot DOM read can outrace a
render.** Posting several comments in a loop — type, click Send, assert
posted, repeat — needs to wait for the *previous* send's `setDraft("")` to
actually land before typing the next one; `send.click()` only waits for the
click itself; whatever `onClick` triggers asynchronously keeps running
after it resolves. Skipping that wait let the next comment's leading
keystrokes land while the field was still being cleared by the last one,
silently truncating "Second comment" down to "omment". And reading a
comment's ordering back with `.allTextContents()` — a one-shot, non-polling
query — can run a beat before React has painted the latest state update,
reporting one fewer comment than actually exists a moment later. Both were
mistaken for product bugs before turning out to be test-only races; the
fix in both cases was to use Playwright's auto-retrying assertions
(`toHaveValue`, `toHaveText`) instead of a manual read-then-compare.
