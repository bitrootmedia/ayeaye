---
paths:
  - "apps/api/src/app/api/routers/tasks.py"
  - "apps/api/src/app/services/tags.py"
  - "apps/api/src/app/services/notes.py"
  - "apps/api/src/app/services/pins.py"
  - "apps/api/src/app/services/reminders.py"
  - "apps/api/src/app/services/checklists.py"
  - "apps/api/src/app/services/sheets.py"
  - "apps/api/src/app/models/tag.py"
  - "apps/api/src/app/models/checklist.py"
  - "apps/api/src/app/models/sheet.py"
  - "apps/api/src/app/models/note.py"
  - "apps/api/src/app/models/reminder.py"
  - "apps/api/src/app/api/routers/reminders.py"
  - "apps/web/src/views/TaskDetail.tsx"
  - "apps/web/src/views/Reminders.tsx"
  - "apps/web/src/components/checklist*.tsx"
  - "apps/web/src/components/sheet*.tsx"
  - "apps/web/src/components/tag-*.tsx"
  - "apps/web/src/components/reminder-panel.tsx"
  - "apps/web/src/components/private-note*.tsx"
  - "scripts/e2e-tags.sh"
  - "scripts/e2e-notes.sh"
  - "scripts/e2e-checklists.sh"
  - "scripts/e2e-sheets.sh"
  - "scripts/e2e-reminders.sh"
  - "e2e/tests/notes.spec.ts"
  - "e2e/tests/tags.spec.ts"
  - "e2e/tests/reminders.spec.ts"
---

# Tags, notes, reminders, pins, checklists and sheets

## Tags, notes, reminders and pins

Four small subsystems on the task, and each has exactly one rule worth
remembering.

**Tags: `lower(name)` is unique per organisation.** Without that you get `kb`,
`KB` and `Kb` inside a week and no filter finds all three. The API is
get-or-create by name, so the picker can offer "create «foo»" without two
people racing into two tags. Display keeps whatever case was typed.

**`off_board` is the only tag property that changes behaviour.** Tasks carrying
one leave the board and the list — that's how "this is a knowledge-base item
rather than a task" is expressed without a second entity type — but they stay
searchable, stay on their project, and appear the moment you filter for that
tag. Search matches tag names precisely so an off-board task is still reachable
by typing the word it was filed under. Members create and apply tags; only
admins rename, delete, or move one off the board, because all three change what
every existing tagging means.

**Private notes: there is no branch that grants anybody else access.** Every
statement in `services/notes.py` filters on the caller — not "unless they're an
admin", not "unless they own the task". The absence of an override *is* the
feature. One note per person per task, upserted on `uq_task_notes_task_user`
because the editor autosaves and two saves can overlap.

**Reminders: `notified_ahead_at` / `notified_due_at` are a claim, not an audit
trail.** The sweep is `UPDATE … WHERE <stamp> IS NULL … RETURNING id` — it
selects and marks in one statement, so a scheduler restart, a retry or two
schedulers racing produce one notification rather than several. Select-then-
update leaves a window where both runners think the row is theirs, and the
failure only shows up as everybody getting the same email twice.

Two more that will bite:

- **A date has no timezone**, so the sweep groups by `users.timezone` and
  computes "today" per zone. The column is filled in from the browser on
  `GET /me` — detected, never asked for, because a setting nobody finds stays
  wrong.
- **Moving a reminder clears both stamps.** Otherwise snoozing until next week
  silences it permanently.

**Reminders are editable, from both surfaces.** The date, the note, and a
standalone one's title — `PATCH /reminders/{id}` always accepted all three,
so the gap was a missing control rather than a missing feature, and it
presented as "I can only delete it and retype it". Edited in place rather
than in a dialog: two or three short fields don't earn a modal, and the row
is where you are already looking. The task panel offers no title field,
because a task-anchored reminder takes its name from its task
(`ck_reminders_one_anchor`) and there is nothing there to edit. Both
editors reseed their fields when opened rather than trusting `useState`'s
initial value — the same stale-local-state trap `Keyed` fixes for the task
screen, which here would hand you last week's date on a second edit.

**A reminder doesn't need a task.** `ck_reminders_one_anchor`
(`num_nonnulls(task_id, title) = 1`) is the same one-of-two-anchors idiom
`attachments` and `conversations` already use — a standalone reminder carries
its own `title` where a task-anchored one uses the task's. It still needs an
organisation, because the calendar reads reminders one organisation at a
time and a standalone row has no task to read one from —
`ck_reminders_org_iff_standalone` (`(task_id IS NULL) = (organisation_id IS
NOT NULL)`) is what keeps `organisation_id` from drifting out of sync with
which shape a row actually is. `mine_stmt` outer-joins `Task` rather than
requiring one; every caller — the sweep, the calendar, both `ReminderOut`
schemas — has to handle `task is None` rather than assuming a task exists.
Created from `/reminders`, not from a task screen, with its own
organisation picker (there's no URL to infer one from, unlike the task-
anchored form which already has an org in its path).

**Pins: personal, like the note, not shared, like the tag.** `task_pins` is
the same one-row-per-person-per-task shape as `task_notes` and
`planner_entries`, and for the same reason — pinning is what *you* want on
*your* dashboard, and there is no admin override, the same absence-of-a-branch
discipline as `services/notes.py`. `read` is enough to pin, the same reasoning
that lets read-only access log your own time: it's a record of what you find
worth watching, not a change to the work. A pin outlives whatever access
justified it — nothing deletes the row when a grant is revoked — so the read
that builds the dashboard's Pinned card re-applies `visible_task_ids_stmt`
rather than trusting the join, the identical reasoning `services/planner.py`
already documents for its own bucket read.

## Checklists

Read `services/checklists.py`. A task can carry more than one — "packing
list" and "before we ship" are two different lists, not two sections of
one — and unlike everything in the section above, a checklist is **shared
task content, not a personal record**: `write` gates every mutation
(`services/checklists.py`'s own docstring), the same bar tagging and
attaching a file already clear, not the `read`-is-enough rule reminders,
notes and pins get for a record of what *you* did.

**`write`, not the task owner, and not an org admin's special case.** There
is no `can_manage_checklists` rule distinct from `can_edit` — an editor and
the owner see identical controls, which is correct: a checklist item is no
more the owner's alone than the description is.

**Ordered by `id`, no `position` column.** UUIDv7 sorts chronologically, so
creation order falls out for free — the same reasoning `list_members`
already uses for the roster, and simpler than the midpoint-position
convention the planner and the task list use, because nothing here needs
drag-and-drop reordering.

**Every mutation announces, and the panel needs its own nudge to hear it.**
`tasks_service.announce()` after every add/toggle/remove is what makes a
second open tab see a checked-off item without a manual refresh — the same
"if it writes to a task, it announces" rule as tags and files. But the
Checklists panel fetches on its own, the identical shape `TaskFilesPanel`
already has: `TaskDetail.tsx`'s realtime handler bumps a `checklistsKey`
alongside the existing `filesKey`, and the panel's `refreshKey` prop is a
dependency of its own load effect. Missing that wiring is invisible in
testing and shows up as "I checked it off and the other tab still shows it
unchecked."

**Empty, this panel isn't a panel — it's a `+ Checklist` button, and the
same goes for Sheets, Depends on, Files and the private note.** All five
are rare on any given task, and five cards each saying "nothing here" was
most of a screen spent on features most tasks never use. Each now renders **nothing at all**
— not even its heading — until it either turns out to hold something or
somebody presses its button, which is `TagStrip`'s own `+ Tag` affordance
(`size="xs"`, ghost, muted, a bare `PlusIcon` and a word). Five things
about the wiring:

- **Where a button sits is decided by where its card will appear**, not by
  tidiness. All five share one row placed *between* them — Checklists,
  Sheets and Depends on reveal upwards into the space they already occupy,
  Files and the private note reveal downwards into their own, and either
  way the card lands where you were already looking. **The private note's
  card had to move up for it to earn a place in that row.** It used to sit
  last on the page, after History, on the reasoning that everything above
  it is shared with somebody by construction and this one card never is —
  which meant a fifth button up in the row would have revealed something
  below the fold, reading as a button that did nothing, so it got a row of
  its own at the bottom instead. Asked to put it with the others, the
  honest fix was to move the card to directly under Files rather than
  leave the button pointing off-screen; the sharedness ordering is the
  thing that gave way. It's still the last card in its column at `2xl`,
  where Comments and History move out of it.
- **The row is not gated on `editable`, and the private note is why.**
  Every other button in it writes shared task content and needs `write`;
  a note is yours, and `services/notes.py`'s rule is that seeing the task
  is enough to keep one. So the filter that builds the row admits the
  note for anybody and the other four only for an editor
  (`extras[key] === "empty" && (editable || key === "note")`), and a
  read-only viewer gets a row holding exactly one button. Gating the row
  itself — which is what it did while the note had its own — would
  quietly remove the feature from the read-only viewer most likely to be
  keeping notes on somebody else's work. `notes.spec.ts` pins it: the
  second person there is only action-required, and still opens a note.

- **The panels still mount and still fetch while collapsed.** Returning
  `null` from render is what hides them; the effects underneath run as
  they always did. That's deliberate — it's what makes a task that *does*
  have a checklist show the card with no button press, and what lets a
  realtime `checklistsKey` bump reveal one the moment somebody else adds
  it in another tab.
- **`open` and `onLoaded` are the whole contract**, and `open` defaults to
  `true` so a panel used anywhere else behaves exactly as it did before.
  `TaskDetail.tsx` holds one `"loading" | "empty" | "open"` per panel:
  `"loading"` offers no button yet (otherwise it flashes on every task
  that has one), `"empty"` offers the button, `"open"` renders the card.
- **A panel never closes itself again.** `onExtraLoaded` only ever moves
  *towards* `"open"` — deleting the last checklist would otherwise yank
  the card out from under the person who just deleted it, mid-click.
- **`onLoaded` is held in a ref and reported from its own effect**, not
  called from `load()`. The task screen passes an inline arrow, which is
  a new function identity every render; in `load`'s dependency list that
  is an infinite refetch loop. This is the same class of trap as the
  `useMatch(a) ?? useMatch(b)` hook-order bug below — cheap to write, and
  it presents as the network tab quietly catching fire.

The old `if (empty && !canEdit) return null` guard in each panel is gone,
subsumed by this: a read-only viewer never gets the button that sets
`open`, so an empty panel stays hidden for them exactly as it did before.

**`PrivateNote` reports from its fetch rather than from its state**, which
is the one place this pattern differs. The others answer "is the list
non-empty"; a note answers "was there anything here when I arrived", and
what the box holds after that is the person typing — by which time `open`
is already true, so re-reporting would say nothing new.

**Collapsing Files and the note cost ten browser tests a line each**, and
that is the honest price rather than a reason not to: a test that writes a
task's *first* file or note now has to open the panel, because there is
nothing to drop on or type into until it does. `openFilesPanel` and
`openPrivateNote` in `e2e/tests/helpers.ts` do it. **Both wait on
`card.or(button)` before deciding, and that wait is the whole point** —
each panel only chooses between its card and its button once its own
fetch lands, so the first version's bare `count()` on the button (which
waits for nothing) read zero on a freshly opened task, skipped the click,
and left six tests timing out against a card that was never coming. Tests
where the content arrives *through* something else — a file posted in a
comment, a screenshot pasted into the description — needed no change at
all, because the panel opens itself the moment the refetch comes back
with content, which is the behaviour worth having.

**Two assertions had to change meaning rather than just gain a line.**
`notes.spec.ts` proved "the note is gone" and "Bob has his own empty box"
by reading an empty textarea that was always on screen; an empty note is
now no card at all, so both now assert the card's *absence* and then open
it to check the box is empty. That is the truer statement of what the
product does, and it was worth noticing rather than reaching for the
smallest edit that made the red go away.

**A freshly created checklist's `items` must never be touched before the
router builds its response.** Found building `add_checklist`: assigning
`checklist.items = []` to "seed" the relationship still triggers SQLAlchemy
to load the *current* value first to diff against, and an unloaded
relationship on a session-attached object is a lazy load — outside an
awaited call, that's the identical `MissingGreenlet` trap
`recurrence.attach()` hit (see "A service that mutates a `Task` field
outside `tasks_service.update()`" above). The fix isn't a workaround, it's
not touching `.items` at all: the router builds `ChecklistOut(..., items=[])`
directly for a create response, since a checklist that was just made
provably has none. Everywhere else that reads `.items` —
`get_checklist_or_404`, `for_task` — eager-loads it with `selectinload` up
front instead, and `rename_checklist`'s own `db.refresh()` is scoped to
`attribute_names=["title"]` so it doesn't expire that already-loaded
collection and reintroduce the same trap one call later.

## Sheets

Read `models/sheet.py`. A grid checklist under a task: rows and columns are
freeform labels you type in — servers down one side, repeatable checks
across the top — and a cell is a checkbox at their intersection. It exists
for exactly the case a single flat checklist can't express: "run the same
three checks across twenty servers" is 3 items × 1 list in a checklist, or a
2D grid here, and the difference is whether you can see at a glance which
server still needs which check.

**A cell's existence IS the check.** There is no boolean column on
`task_sheet_cells` — checking inserts a row (`ON CONFLICT DO NOTHING`, the
same idempotent-apply idiom `tags.apply` already uses), unchecking deletes
it. That single choice is what makes "a newly added row or column starts
unchecked against everything else" free rather than something to backfill:
an added row simply has no cells yet, for any column, until someone checks
one. `services/sheets.py`'s `cells_for_sheets` reads them back as a sparse
map in one query per page of sheets — the same one-lookup discipline every
list endpoint in this codebase follows once access gets interesting, never
one query per cell.

**Every check records who and when.** `checked_by_user_id` plus `created_at`
ride along on the same row whose existence is the check — no separate
audit table, because the row already carries everything worth knowing.
On a race (two people click the same cell within milliseconds), the
`ON CONFLICT DO NOTHING` insert means the response has to be **read back**
rather than assumed from the request: whoever's insert actually landed is
who the cell belongs to, and the caller that lost the race needs to know
that, not report themselves as the checker.

**More than one sheet per task, ordered by `id`.** Same "packing list" vs
"before we ship" reasoning as checklists, and the identical no-`position`-
column convention — UUIDv7 sorts chronologically and nothing here needs
drag-and-drop reordering.

**`write` gates every mutation, `read` is enough to see the grid.** The
identical bar checklists, tags and files already clear — this is shared
task content, not a personal record.

**A `<td>` is not a flex container, and Base UI's `Checkbox` root is a plain
inline `<span>`.** Its explicit `size-4` width and height are simply
ignored outside a flex or grid context, and the checkbox collapses to a
hairline — the two side borders of a zero-width box — rather than a square.
Every cell wraps its `Checkbox` in a `<div className="flex justify-center">`
for exactly this reason; dropping that wrapper is the kind of regression a
screenshot catches immediately and a type-check never will.
