---
paths:
  - "apps/api/src/app/services/planner.py"
  - "apps/api/src/app/models/planner.py"
  - "apps/api/src/app/api/routers/planner.py"
  - "apps/api/src/app/api/routers/calendar.py"
  - "apps/web/src/views/Planner.tsx"
  - "apps/web/src/views/Calendar.tsx"
  - "scripts/e2e-planner.sh"
  - "scripts/e2e-agent-queue.sh"
  - "e2e/tests/planner.spec.ts"
---

# The day planner and the calendar

## The day planner

Read the `services/planner.py` docstring. A personal board over the tasks a
person can see — a pool of open, unplanned work, and five fixed buckets
(Today, Tomorrow, This week, Next week, Someday, in that urgency-decreasing
order — the same convention as `STATUS_RANK`/`PRIORITY_RANK`: a fixed set
ordered by what it means, not by spelling). Deliberately **not on the Task
model at all** — `planner_entries` is a new, additive table, one row per
(task, user), and "unplanned" is the absence of a row rather than a sixth
bucket.

**Yours, or an organisation admin's override — the shape of time entries, not
notes.** Private notes have no override at all; this isn't that private. An
admin may view and rearrange *any* member's planner, reusing
`access.administers_organisation` exactly as everywhere else that escape hatch
already exists. What the override does **not** do is widen the target's own
access: every read and write resolves visibility against the *target* user's
membership and role, never the caller's — an admin cannot place a task into
someone else's bucket that person couldn't otherwise see (404, the same
"no access reads as 404" rule as everywhere else), and a task hidden from the
target disappears from their planner exactly as it disappears from their
board, admin's view included.

**A `planner_entries` row outlives whatever access justified it**, the same
as a note or a reminder — nothing deletes it when a grant is revoked or a task
is hidden. The bucket read has to re-apply `visible_task_ids_stmt` for that
reason; trusting the join alone would let a hidden task stay visible in its
own bucket, which for an admin viewing someone else's planner is a real leak,
not a cosmetic one. This is the one thing `scripts/e2e-planner.sh` has a
dedicated regression case for, and it's worth re-reading if this file is ever
touched: removing that re-check makes the test fail, which is the point of it.

No realtime channel, on purpose — like notes and reminders, this is refetch-
after-mutation, not a socket. `position` is a plain integer, the same
no-resequencing convention as `Task.position`: the client computes a value
(the midpoint of its new neighbours, or ±1000 at an end) once per drop, and
nothing server-side ever renumbers a bucket.

**`position` is optional on `PUT`, and that's a second, narrower caller
speaking, not a loosening of "the client always computes it."** The Planner
board itself never omits it — it always knows a drop's new neighbours and
still computes the value itself, unchanged. The task screen's own bucket
picker is different: it has no visibility into a bucket's existing rows
(fetching the whole planner just to place one task would be a strange
trade for a single dropdown), so `services/planner.py::place` computes
`MAX(position) + 1000` for that bucket server-side when `position` is left
out — "append to the end," the one sensible default for a control that
can't see the list it's appending to.

**A task's own screen carries the caller's own bucket, read-only next to
`is_pinned` in `TaskOut`, not built into `TaskUpdate`.** `planner_bucket`
is set via `_planner_bucket_for` (`api/routers/tasks.py`) — one batched
lookup, the identical shape `_recurrence_for` already uses for the same
reason: called only from the single-task endpoints (`GET`, `PATCH`,
`POST .../closed`, `POST .../hidden`, and the shared `_task_response` pin/
recurrence rebuilder), never the list or board, which don't pay a personal
per-row lookup's cost for a field only one screen renders. Setting it goes
through the planner's own `PUT`/`DELETE`, not `PATCH /tasks/{id}` — a
bucket assignment isn't a task field the way status or due date are, it's
personal to whoever's looking, the identical "yours alone" bar pinning
already clears. **The one exception is creating a task**, where
`TaskCreate.planner_bucket` places it on the creator's own planner in the
same request — the New task dialog offers the bucket, and a create followed
by a separate `PUT` could leave a task existing having lost the bucket
chosen for it. Still not the planner's rule leaking into tasks: the router
composes `planner_service.place()` after `tasks_service.create()`, there is
no `?user_id=` (it is always the creator's own board), and `TaskUpdate`
still has no such field. The task screen's picker (`views/TaskDetail.tsx`) is an
ordinary `EntityPicker`, matching CLAUDE.md's own "short fixed lists use it
too" rule for Status and Priority, with **both** `placeholder` and
`emptyLabel` set to `"Not planned"` — matching Action Required's identical
two-prop shape. Setting only `emptyLabel` looks right while the list is
open (the row is there to clear it) and is wrong at rest: `EntityPicker`'s
trigger button resolves its own label by finding `value` in the raw
`items` array, which never contains the synthetic empty-label row — that
row only exists in the *filtered* list shown while open. Skip `placeholder`
and clearing the field silently reverts the button to the picker's own
generic "Choose…" instead of "Not planned," found live testing this exact
field, not by reading the component's source first.

**The five buckets are one horizontally-scrolling row, never a wrapping
grid.** They used to be `sm:grid-cols-2 xl:grid-cols-5`, which at `xl` forced
five fixed columns into whatever the pool left over — about 670px at 1280
with the rail open. That truncated every task title to a single letter and
clipped Someday off the edge entirely, and the screen was *more* readable at
1024 (two columns) than at 1280, which is how it was found. Each column now
has a `basis-56` floor and still `grow`s, so nothing scrolls until it
actually has to. Wrapping to two columns was the alternative and reads worse
on a board: the whole point of these five is that they're one line in
decreasing urgency, and a 2×3 wrap says something different about the
ordering. The pool stays a tray on the left rather than becoming a sixth
column — it's what you drag *from* — and only stacks above once there's no
room beside. dnd-kit needed no change: its auto-scroll already handles a
scrollable ancestor, and the keyboard sensor still reaches the columns past
the edge. Pinned by "the buckets stay readable when there isn't room for
five columns", which asserts on **geometry, not `toBeVisible`** — every one
of those elements was perfectly "visible" the whole time it was unreadable —
and which fails if the grid is put back.

The frontend's drag-and-drop is `@dnd-kit` — the first dependency of its kind
in this codebase, chosen for a first-class keyboard sensor. That sensor isn't
a nicety: `e2e/tests/planner.spec.ts` drives the actual reorder through
keyboard events rather than synthetic pointer movement, because dnd-kit's
mouse sensor is pointer-event-driven and genuinely flaky to script through
Playwright's `mouse.move` steps. Two things cost real time writing that test:
**a bare Space/ArrowRight/Space sequence races dnd-kit's own collision-state
update**, which lands on the next animation frame rather than synchronously
with the keydown — a short pause after each key is what the interaction
actually needs, not a Playwright quirk. And **which bucket a single
`ArrowRight` lands on is dnd-kit's own spatial collision algorithm**, not a
product decision worth pinning in a test — asserting "left the pool, landed
in *some* bucket, survives a reload" is the honest claim; asserting "landed
in Today specifically" is asserting an implementation detail that has no
product meaning.

## The planner is also the agent queue

**There is no queue table, and there must not be one.** Handing work to an
assistant — a Claude Code session with a write token, holding its own member
account — is arranging its planner: a `planner_entries` row *is* what "queued"
means, its bucket and position *are* the order, and the board a person drags
into shape and what `next_task` hands back cannot drift apart because they are
the same rows read the same way round. Four tools in `app/mcp/server.py`:
`next_task` (the top of your own board, in full), `my_planner` (the whole
board), `plan_task` / `unplan_task`.

This came out of wanting ayeayecaptain to be a feed an agent works down rather
than a thing you prompt at. Everything it needs already existed under another
name, and the shape below is why nothing was added:

- **The agent is an ordinary member with its own account and `ayc_…` token.**
  `services/access.py` scopes it like any colleague, its comments are ordinary
  thread messages with realtime delivery and unread badges, `messages.via`
  records which credential wrote them, and `task_events` says "Claude changed
  status" rather than blurring into somebody's own edits. **Not a `users.kind`
  column** — CLAUDE.md's rule forbids it, and nothing here needs one.
- **`action_required_user_id` is the plate, the planner is the order.** They
  stay orthogonal on purpose: being asked to act already carries `write` on a
  task with no project route into it (the six routes in), already notifies on
  the set transition, and already notifies *back* on the clearing transition
  (`KIND_ACTION_REQUIRED_CLEARED`) — which is the handback half of the loop
  with no new notification kind. A tag would have given none of that and no
  order either, which is why "tag it `agent`" was the branch not taken.
- **Nothing is skipped, including a task already `in_progress`** — see
  `next_stmt`'s docstring. A run that stopped halfway leaves exactly that, and
  a queue that steps over what it already started starts the same work twice
  and strands the first attempt. There is no lease and no claim: two workers
  on one person's planner is not defended against, and saying so is better
  than a lock that half works.

**The finishing order has the trap in it, and it is the same trap three times
now.** Comment, then `unplan_task`, then hand the work back *last*: moving
`action_required_email` away from yourself can be the only thing that was
letting you see the task at all, so anything attempted after that may find it
gone. Same rule as `POST .../owner` returning 204 with no body, and as
`update_task`'s re-resolution fix — don't re-resolve a level a successful
write just took away. It is stated in `next_task`'s own description because
that is the tool that frames the loop, and `unplan_task` deliberately checks
no task access of its own so a board can still be cleared after the task has
left reach. `scripts/e2e-agent-queue.sh` walks the whole loop and asserts the
handback both succeeds *and* makes the task 404 for the agent immediately
afterwards.

**`plan_task` is your own board only**, matching `planner_bucket` on
`create_task` — there is no `user_id` argument over MCP at all. Queueing work
*for* somebody is the admin override on the web screen, done deliberately by
somebody who meant to, not a thing an assistant does quietly.

**`BUCKET_RANK` (`models/planner.py`) is the only place bucket order is
written down**, the same convention as `STATUS_RANK`/`PRIORITY_RANK`.
`bucket` is a plain string column, so `buckets_stmt` ordering by it directly
spelled the board *alphabetically* — next_week, someday, this_week, today,
tomorrow — and a Someday task would have been handed back ahead of everything
in Today, silently and forever. The Planner screen never noticed because it
re-buckets the rows into a dict keyed by `BUCKETS`; `next_stmt` reads them in
order and would have. It is now `case(BUCKET_RANK, value=PlannerEntry.bucket)`,
the identical shape `access.py` uses for status and priority. `my_planner`
still walks `BUCKETS` itself when rendering rather than trusting the rows'
order, so the answer cannot be re-spelled by a future change to the statement.

**`_task_detail` in `app/mcp/server.py` is shared by `task` and `next_task`.**
The top of a planner is the task somebody is about to start, and giving it a
thinner answer than an explicit read would be the wrong half to save tokens
on — so it is the same renderer, not a second one that drifts.

## The calendar

Read `api/routers/calendar.py`'s own docstring — it states the one thing
worth knowing before touching any of this. `GET /organisations/{id}/calendar
?start=&end=` returns three lists with **deliberately different visibility
rules on the same grid**: every visible task's due date is team-wide (the
same access as the Tasks list — `tasks_service.list_visible` with
`due_after`/`due_before`, two new params on `access.visible_tasks_stmt`
alongside its existing filters, both inclusive so a task due on the grid's
last day still shows), while reminders stay `reminders_service.mine_stmt` —
private, exactly like every other reminder surface. Two people in the same
organisation see the same task dots and different reminder dots on the same
month. That split was the one real design question here, decided in favour
of a genuinely shared "what's due when" over a quieter personal-agenda
version scoped like the dashboard's escalation cards — see the router
docstring for the reasoning kept next to the code it explains. A standalone
reminder (see "Tags, notes, reminders and pins" above) shows here too —
`mine_stmt` outer-joins `Task`, so `CalendarReminderOut.task_id` comes back
`None` for one and `Calendar.tsx`'s own `ReminderChip` renders it as a plain
label instead of a link, since there's no task screen for it to open.

**Out-of-office rides with tasks, not reminders — because it was never
private to begin with.** `presence_service.away_between(start, end)` is the
dashboard's own fortnight-ahead OOO query generalised to an arbitrary window,
with `away_in_org` kept as a thin wrapper over it so the dashboard's call
site didn't need to change. CLAUDE.md's own presence rule — "its whole value
is a colleague checking before they ask you for something" — is what decides
the visibility here, the same as everywhere else OOO appears: every member of
the organisation sees every absence, scoped to membership rather than task
access, because OOO is about people rather than about anything you'd need a
grant to see. Unlike a task's single `due_on` or a reminder's single
`remind_on`, an absence spans `[starts_on, ends_on]`, so the frontend can't
bucket it with a single map lookup by date — `Calendar.tsx` walks every grid
day against every absence and does a plain range-overlap test, the same
`starts_on <= day <= ends_on` shape `presence.is_away()` already uses.

**The window is capped at 42 days** (`MAX_WINDOW_DAYS`) — a month grid is
never more than six weeks, and a caller wanting more than that already has
the Tasks list, which actually paginates. Both `start > end` and an
oversized window are `422`, not silently clamped — a silent cap is the same
mistake the task list's own "no default limit" rule exists to avoid.

**Hand-rolled month grid, not a calendar library.** The first calendar
surface in the product and there was no reason to reach past a CSS grid and
some date arithmetic for it — `@dnd-kit` is the precedent for what actually
justifies a new dependency here (a keyboard sensor doing something plain
CSS/JS can't), and click-through-only navigation never needed one. The one
place this bit: **`toISOString()` converts to UTC first**, which slides the
date near midnight for anyone not on UTC — `isoDate()` builds `YYYY-MM-DD`
from the local `Date` fields instead, the same reasoning
`services/reminders.py` gives for doing its own date arithmetic rather than
trusting a library to get local-day boundaries right.

**The visible month is in the URL** (`?month=YYYY-MM`), same reasoning as
every other view/filter in the product: a month somebody navigated to is one
they can send a colleague, and a reload should land back where they were
rather than snapping to today.
