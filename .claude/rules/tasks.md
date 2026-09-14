---
paths:
  - "apps/api/src/app/services/tasks.py"
  - "apps/api/src/app/services/dependencies.py"
  - "apps/api/src/app/models/task*.py"
  - "apps/api/src/app/api/routers/tasks.py"
  - "apps/api/src/app/schemas/task*.py"
  - "apps/web/src/views/Task*.tsx"
  - "apps/web/src/views/Triage.tsx"
  - "apps/web/src/views/Tasks.tsx"
  - "apps/web/src/components/task-*.tsx"
  - "apps/web/src/components/dependencies-panel.tsx"
  - "apps/web/src/components/new-task-dialog.tsx"
  - "apps/web/src/components/priority.tsx"
  - "apps/web/src/components/status-*.tsx"
  - "scripts/e2e-tasks.sh"
  - "scripts/e2e-triage.sh"
  - "scripts/e2e-hidden.sh"
  - "scripts/e2e-task-*.sh"
  - "scripts/e2e-dependencies.sh"
  - "e2e/tests/task*.spec.ts"
  - "e2e/tests/hidden.spec.ts"
---

# Tasks, triage and task versions

## Tasks

Read the `services/tasks.py` docstring. Five rules, all of which fail
*silently* if broken — a notification that doesn't arrive, one that arrives
twice, a history row that never gets written. `tests/test_task_rules.py` pins
each individually.

**Status and open/closed are two fields.** Closing is not a status; a task can
be closed from any status, and "closed while still `blocker`" is expressible
because that is what happens when work is abandoned rather than finished.
There is deliberately no `done` status — a test asserts its absence. The board
has no Closed column for the same reason: a closed task keeps its real status.

**Only the owner closes** (org admins resolve to `owner` level, so they
qualify). A non-owner who can see the task gets **403, not 404** — they can see
it, so pretending it doesn't exist would be the wrong lie. `can_close` is
resolved server-side and sent on every task, so the UI hides the button rather
than showing one that 403s.

**The picker only offers people who can already see the task, and that is a
UI rule rather than an API one.** `TaskDetail.tsx`'s Action-required field,
the comment composer's "with this comment" switch and every row in Triage
all list `GET /tasks/{id}/mentionable` — `services/mentions.py::for_task`,
"everyone who can see this task, teams expanded" — never the organisation's
roster. Saying "this is waiting on you" to somebody who can't open the task
is a nudge they can do nothing with, and it is the same question the mention
picker two inches below already answers, so it is the same list rather than
a second one. Widening it is sharing: the Who-can-see-this card is in the
same column, and `AccessPanel`'s `onChanged={load}` refetches the candidates
with everything else, so a person shared in appears in the picker without a
reload.

**The API and MCP are deliberately *not* restricted to match.** Being named
still carries its own access (`effective_task_level`'s action-required
route), so `PATCH /tasks/{id}` will still hand a loose task to somebody with
no other way in — that route is what makes the assignment openable at all,
and an integration acting on a person's behalf keeps it. What changed is
only which names a human is offered. The two `e2e-tasks.sh` assertions that
exercise the permissive path stay exactly as they were; the browser suite
(`tasks.spec.ts`, "only offers people who can already see this task") is
what pins the picker, because a picker's contents is precisely the thing an
HTTP suite cannot see.

**Owner is the exception, and stays the whole roster.** Handing a task to a
colleague is how it *becomes* theirs, and `owner` is a route in by itself —
scoping that list to people who can already see it would make "give this to
somebody new" impossible.

**Action-required notifies on the transition.** `should_notify_action_required`
is the whole rule: same person again → nothing, clearing → nothing, yourself →
nothing. Every save resubmits the whole form, so a naive `if incoming: send`
pings that person on every keystroke-save.

**Clearing it notifies back, the symmetric other half.** The owner set
someone as action-required because they were waiting on them; the moment
that clears, the ball is back in the owner's court and they should hear
about it without having to keep checking. `should_notify_handback` is the
mirror of the rule above — fires only on the clearing transition (someone
*was* action-required, now nobody is), never on setting it or moving it to
someone else, and never notifies the owner about their own edit, the same
"never about yourself" shape. It fires regardless of *who* clears it — the
common case is the assignee marking themselves done, not the owner — which
is exactly why the self-check is on the *owner*, not the *actor*: an owner
clearing their own task's action-required already knows, but an assignee
clearing it is news to the owner. `KIND_ACTION_REQUIRED_CLEARED` is one
more entry in the closed `NOTIFICATION_KINDS` set (another CHECK-constraint
migration, following 0019/0028's own pattern), and needed no frontend
change — `Notifications.tsx` already renders every kind uniformly.

**The dates live in their own Schedule card, directly above Reminders.**
`due_on`, `estimated_start_on` and `estimated_hours` used to sit at the
bottom of the Status card, which made Status five questions long and buried
the due date under two pickers and a planner bucket. They read together —
by when, from when, for how long — and a reminder is what you set once
you've answered them, so the card sits immediately above the one that does
that. `RecurrenceControl` moved with them rather than staying in Status: it
only renders once the task *has* a due date to anchor the cadence to, so in
Status it was a control whose precondition had moved two cards away. Status
keeps the three switches it is actually opened for — where it stands, who
it's waiting on, how urgent — plus Planner, which is a state the task is in
for you rather than a date.

**`estimated_start_on` and `estimated_hours` are purely informational.**
Both optional, both on the task screen, and neither feeds anything else —
not the access model, not the board, not a sweep, the way `due_on` does.
That's also why setting or clearing either writes no `task_events` row: the
same silent-set treatment `position` already gets, because nothing reads
either field back to decide access, notify anyone, or drive a scheduler
job. `estimated_hours` is `Numeric(6, 1)`, not a float — `_as_decimal()`
goes through `Decimal(str(x))`, not `Decimal(x)`, specifically to avoid
carrying a binary float's own rounding noise (`2.1` becoming
`2.100000000000000088817841970012523...`) into a column someone will read
back and expect to match what they typed. Deliberately *not* on
`NewTaskDialog`: that dialog doesn't even capture `due_on` today, by design
— title/description/status/priority/project only, so a quick add stays
quick — and adding two more optional fields there would be the wrong kind
of inconsistency to introduce for two fields with no urgency behind them.

**"Depends on" is informational, and there is no enforcement to find.**
`task_dependencies` (`models/task_dependency.py`, `services/dependencies.py`)
records that one task is waiting on another — closing a task with open
dependencies still works. The ask was visibility ("to see if it's not
blocking"), not a gate, and this codebase doesn't invent enforcement beyond
what's asked; a search for a `can_close` check against open dependencies
will come up empty on purpose.

- **You can only point a dependency at a task you can already open.** Adding
  a link reuses `tasks_service.context_for` for the *other* task exactly the
  way every other cross-task reference in this codebase already does — there
  is no second access path written in `services/dependencies.py`. A task
  neither side can see fails the ordinary way: 404.
- **The graph stays a DAG, checked with one recursive query, not a Python
  walk.** Before inserting `task_id → depends_on_task_id`,
  `_reachable_from()` walks forward through existing edges starting at
  `depends_on_task_id` — everything it already (transitively) depends on. If
  `task_id` turns up in that set, the new edge would close a cycle and is
  refused with 409. One statement regardless of how many hops the cycle
  would take to close, the same "one statement, not a query per hop"
  discipline every list endpoint in this codebase follows once a graph is
  involved. `scripts/e2e-dependencies.sh` proves it past the trivial
  reversed-edge case with a three-node cycle (A→B, B→C, C→A refused).
- **Reads are two-directional; the edit surface is one.**
  `GET .../tasks/{id}/dependencies` returns both `depends_on` (what blocks
  this task — add/remove lives here) and `blocks` (the reverse query, free
  off the same table — what's waiting on *this* task, read-only on this
  screen, because editing it means editing the *other* task's own list).
- **Each referenced task resolves through the caller's own visibility, not
  the requester's.** Task-level access can differ between two people looking
  at the same edge — the same "task access has six routes in" fact the
  bullets below explain. `list_dependencies` batches this as one visibility
  check across every id on the page (`access.visible_task_ids_stmt`, the
  identical builder the dashboard's Pinned card re-applies for the same
  reason), never a lookup per row. A dependency the viewer can't see comes
  back with `task: null`; the frontend renders it as a muted "a task you
  don't have access to" row and never shows a title or status for it.
- **Every add and remove writes a `task_events` row** — `dependency_added` /
  `dependency_removed`, two more entries in the closed `EVENT_KINDS` set,
  needing the same CHECK-constraint drop/recreate migration every other
  addition to it already uses.
- **The frontend picker is deliberately not `EntityPicker`.**
  `components/task-search-picker.tsx` calls the existing
  `GET /organisations/{id}/search` endpoint per keystroke — already
  access-scoped and fuzzy, no new backend search path — because
  `EntityPicker` filters an already-fully-fetched array client-side, which
  is fine for people or projects and wrong for "every task in the
  organisation." It reuses `search-palette.tsx`'s debounced,
  sequence-checked, abortable request shape (stale out-of-order answers and
  a mid-flight "nothing found" are both real bugs on a real connection) but
  keeps `EntityPicker`'s `Popover.Portal` shell, because a field inside a
  `Card` needs the identical clipping fix either way.

Task access has **six routes in**, three more than a project — see
`effective_task_level`. Two worth knowing:

- **Being asked to act carries `write`**, even on a project you've never been
  given. You cannot ask someone to act on something they can't open.
- **A loose task** (`project_id IS NULL`) is this with the project route
  absent, which settles PLAN.md §4's open question: visible to its creator,
  owner, action-required user, grantees and org admins, and *nobody else in
  the organisation*. The inherited-project rank is a correlated subquery
  precisely so a NULL yields "no route" instead of a join dropping the row.

**A hidden task is the one place access is subtracted, and it is not a deny
rule.** `tasks.hidden_at` short-circuits **ahead of** the whole expression in
both `effective_task_level` and `task_level_expression` — if it's set and you
aren't the owner, no route is resolved at all. Grants stay in place and resume
on un-hiding, so rule 2 is untouched.

Three things that follow, all of them surprising to somebody:

- **Organisation admins can't see it either.** That is the one deliberate hole
  in "an admin can do anything" (private notes are the other), and the recovery
  path when an owner leaves is offboarding, which reassigns ownership.
- **Only the actual owner may hide**, not an admin — `can_hide` is deliberately
  not `can_close`'s rule. An admin hiding somebody else's task would be hiding
  it from themselves.
- **Hiding is refused while another person is action-required**, and setting
  action-required is refused while hidden. Being asked to act is one of the six
  routes in; taking it away silently would leave them a notification that 404s.

**Removing a member reassigns their work; it does not block.** Both
`projects.owner_user_id` and `tasks.owner_user_id` are RESTRICT, so without
`_reassign_everything_owned_by` the DELETE fails with a raw foreign-key error
no admin could act on. PLAN.md §5 asked which way to go — blocking makes
offboarding a puzzle, since you'd have to find every task a departing colleague
owns with no screen that lists them. Every reassignment writes a `task_events`
row saying why.

**Comments are the conversation thread, not a second system.** They are the
Phase 6 thread anchored to a task — attachments, voice notes, realtime and the
unread badge all came with it. There is no `task_comments` table and there
must not be one.

**Priority is a third field, independent of both.** Six levels, `normal` the
default and the middle of the range. `PRIORITY_RANK` in `models/task.py` is
the only place the order is written down; `services/access.py` turns it into
SQL with `case(PRIORITY_RANK, value=Task.priority)` so the board can sort by
it in the same statement that resolves access. Changing it writes a
`priority_changed` event like everything else.

On the frontend it renders as a **direction glyph, not another coloured
badge** — six distinct shapes, colour on Critical and Urgent alone. Status
already owns the only red and the only amber, and a second colour scale per
card would stop red meaning "this needs you". Every glyph carries a `title`
and an `aria-label`, so the level is never conveyed by colour alone.

## Triage

`views/Triage.tsx`, at `/orgs/{id}/triage`, its own rail item directly under
Tasks. Open tasks with **nobody action-required** — the queue for work that
has fallen between "what's mine" (the dashboard's escalation cards, the
Planner) and "what's everything" (the list, the board), because nobody has
picked it up.

**One filter, not a second list endpoint.** `access.visible_tasks_stmt` grew
`action_required_unset: bool`, the same shape `loose_only` already has beside
`project_id`: where `action_required_user_id` narrows to one person, this
narrows to the tasks asking nothing of anybody. A flag rather than a magic
value on the existing filter, because "unset" is a different question from
"this person", not a special case of it — and it composes with every other
filter for free, which is how `include_closed=true` widens the queue without
either filter knowing about the other.

**Everything you can see, not just what you own** — settled deliberately when
the screen was asked for. A triage queue scoped to your own tasks is a
personal follow-up list; the work most likely to be forgotten is the work
nobody has claimed. Access still decides the rest: it's `visible_tasks_stmt`,
so a plain member's queue holds none of the owner's loose tasks, and an org
admin's holds the organisation's whole unassigned pile — the same escape
hatch admin rank is everywhere else. `scripts/e2e-triage.sh` pins both ends
of that.

**Both halves of a triage decision are on the row — how urgent, and who
takes it.** Priority is an `EntityPicker` beside the people one, not a
`Select`, for the reason CLAUDE.md's own field rule gives: a row where one
control opens differently from the one next to it reads as a bug. Only
assigning empties the queue, though — re-prioritising patches the row in
place and leaves it there, because the task still has nobody on it, which is
the only thing this list is about. It also deliberately doesn't jump to its
new position in the priority-first order: re-sorting under the pointer moves
the next row you were reaching for. Assigning gets a toast and
re-prioritising doesn't, for the same reason — the glyph changes where
you're already looking, whereas a vanishing row needs explaining.

**A row leaves the moment you assign it**, removed locally rather than by
refetching. The list is *defined* by action-required being unset, so a task
that now has one is no longer a member of it — and keeping your place in a
long queue is the difference between working through one and starting it
again on every save. The picker is an ordinary `EntityPicker` (`placeholder`
**and** nothing else — there is no clearing row, because clearing is what
every row here already is), absent rather than disabled for a read-only
viewer, the same "don't show a control that 403s" rule as `can_close`.

**Its candidates are fetched per row, when the picker opens.** The queue
mixes projects and loose tasks, so "who can be asked" has no one answer for
the screen — only one per row, and a hundred rows fetched on load would be a
hundred requests for lists nobody looked at. `EntityPicker` grew an `onOpen`
for this (and an `emptyMessage`, so a list that is empty because it is still
loading doesn't claim nothing matches a filter nobody typed); it fires on
every open rather than the first, which is what makes a person shared in
while the queue sat on screen appear without a reload.

**Assigning notifies exactly as it does from the task screen**, because it's
the same `PATCH /tasks/{id}` — `should_notify_action_required` is not
reimplemented here, and a Triage assignment writes the identical
`task_events` row.

## Task versions — recovering a save somebody made over yours

Read `models/task_revision.py`. Reported plainly: "sometimes somebody can
overwrite that and it's a problem not being able to recover." They were
right, and the gap was worse than it looked — a title change had always
written a `renamed` event carrying `was`/`now`, so a title was at least
readable out of the history, but **a description change wrote nothing at
all.** No event, no old value, nowhere to look. Overwritten meant gone.

**A row holds the content the save *replaced*, not the new content.** That
one choice is what lets this table exist without a second answer to "what
does this task say now": `tasks.title` and `tasks.description` stay the only
source of the live version, and every row in `task_revisions` is strictly a
version already overwritten. This is deliberately **not**
`article_revisions`' shape, where the latest revision *is* the live body —
that works for the knowledge base because an article's content lives in its
revisions and nowhere else, but a task's lives on the task, and the newest
row and the task row both claiming to be current is exactly the kind of
disagreement this codebase keeps getting bitten by.

The consequence to hold on to: `created_at` and `replaced_by_user_id`
describe the **overwrite**, not the authorship of the text in the row —
"this is what the task said until Bob saved over it at 14:03". Which is the
question somebody asks when their description has vanished.

- **One row per save, however many of the two fields moved.** The Details
  card saves title and description in one `PATCH`, so the snapshot is taken
  once, from the outgoing values, before either is applied. Two rows would
  claim two edits happened.
- **A save that changes nothing records nothing**, so the list stays a list
  of real overwrites. The comparison normalises both sides with `or ""` —
  a task that never had a description holds NULL while the editor posts
  back `""` for it, and without that, opening such a task and pressing
  Save with nothing typed would file a revision of nothing.
- **Sanitised before the comparison, not after.** Same reason: a save that
  only reformats markup into what is already stored isn't an edit.
- **Reading is `read`, restoring is `write`.** Somebody with read-only
  access who watched a description they contributed get overwritten is
  exactly who needs to look it up — and copy-paste out of the dialog is a
  legitimate recovery for them. Putting it back is an edit and clears the
  ordinary bar.
- **`restore_revision` is a plain `update()`, not a second write path.**
  Everything that makes an edit an edit — the `write` check, the snapshot of
  what the restore is *itself* replacing (so a restore is undoable in turn),
  the history rows, the realtime announce — already lives there. The only
  thing added is the `restored` event, so the trail says the text came back
  from a version rather than being retyped from memory.
- **No re-resolution of the caller's level after a restore**, unlike
  `PATCH /tasks`. A restore only ever touches title and description, neither
  of which is a route into the task, so the "you can lose your own access by
  editing" case that handler's `try/except HTTPException` exists for cannot
  arise here.
- **Not paged, and no cap.** The same reasoning as `list_events` beside it,
  but sharper: a silently truncated answer on a recovery surface means the
  version you needed is the one missing.
- **No `description_text` generated column**, unlike `article_revisions`'
  `body_text` — search matches the live content only, the same "search the
  live content, not history" rule the knowledge base already follows, so
  there is nothing here to index.

Two things on the frontend are worth knowing before touching it:

- **It's called "Versions", not "History".** The History card on the same
  screen is the append-only trail of *what happened*; this is the
  recoverable *text*. Two controls with one name would leave people
  guessing, and would make every `getByText("History")` in the browser
  suite ambiguous.
- **Each row carries a snippet of its own prose, and that is what makes the
  list usable at all.** Several versions of one task routinely share a
  title — a description edited three times gives three rows whose title,
  author and even minute are identical, and picking the right one by
  opening each in turn is a guessing game rather than recovery. Found
  immediately, by a browser test that couldn't tell two rows apart either.
- **Restoring has to remount `Details`, and a refetch alone will not do
  it.** `Details` seeds the title and the description into
  `useState(task.title)`, which runs on mount and never again — the same
  fact behind the stale-title bug `Keyed` fixes for navigation between two
  tasks. Here nothing navigates, so there's no route key to lean on:
  `load()` updates every field fed straight from props while the editor
  keeps showing the text the restore just replaced, which looks exactly
  like a restore that silently did nothing. A `detailsKey` counter bumped
  **after** `load()` resolves is what forces the reseed. Deliberately not
  keyed on `task.updated_at`: that moves on every save, every comment and
  every realtime nudge, and remounting the editor under somebody
  mid-sentence would throw away what they were typing. A restore is the one
  moment discarding the editor's contents is the right thing to do, because
  replacing them is what was asked for. `rich-text.spec.ts` fails on
  exactly this assertion with the key removed.

## The task screen's project links

- **The task screen linked its own project unconditionally, in two places,
  and both were wrong for the same reason.** The breadcrumb's project crumb
  and the access card's "Anyone who can see {project}" sentence both used
  to render as links regardless of whether the caller could actually open
  the project. Task access has six routes in — three more than a project's
  — so a task-level grant (or being action-required, or having created it)
  can make a task visible to someone with **zero** access to the project it
  happens to be filed in; `access.inherits_from_project` is purely
  structural ("does this task have a project", `task.project_id is not
  None` server-side) and says nothing about *this caller's* access to it.
  The fix in both places is the same: check membership in the `projects`
  list `TaskDetail.tsx` already fetches for the move-task picker — that
  list is scoped to exactly what the caller can see
  (`access.visible_projects_stmt`), so `projects.some(p => p.id ===
  task.project_id)` is the real answer, not a guess from a structural
  field. Found by testing a task-level-only grant specifically, the same
  case `effective_task_level`'s own docs call out as surprising.
  **Traced through a test-authoring trap on the way**: shadcn's
  `BreadcrumbPage` (the non-clickable "current page" marker) sets
  `role="link" aria-disabled="true"` for accessibility, so
  `getByRole("link", { name })` matches it exactly like a real `<a>` —
  proving "this is not a link" needs `locator('a:has-text(...)')`, not a
  role query, or the assertion passes for the wrong reason.
  **The breadcrumb's destination changed again afterwards, and the two
  links earned different answers.** The crumb now goes to
  `/orgs/{id}/tasks?project={projectId}` — the task list filtered to that
  project — instead of the project's own detail page: "Tasks" then
  "ProjectName" reads as a drill-down, and it's the screen a board or list
  click actually came from. The access card's "Anyone who can see
  {project}" sentence keeps linking to the project detail page on purpose —
  that sentence is specifically about the project's sharing settings, which
  live on that page, so redirecting it to a filtered task list would
  disagree with its own wording. Same
  `projects.some(p => p.id === task.project_id)` guard on both, only the
  breadcrumb's target moved.
