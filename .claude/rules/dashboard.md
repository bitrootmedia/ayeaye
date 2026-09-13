---
paths:
  - "apps/api/src/app/api/routers/dashboard.py"
  - "apps/api/src/app/services/presence.py"
  - "apps/api/src/app/services/working_hours.py"
  - "apps/web/src/views/Dashboard.tsx"
  - "apps/web/src/views/Account.tsx"
  - "apps/web/src/views/OrganisationDetail.tsx"
  - "apps/web/src/components/working-hours-grid.tsx"
  - "apps/web/src/lib/working-hours.ts"
  - "scripts/e2e-dashboard.sh"
  - "scripts/e2e-working-hours.sh"
  - "e2e/tests/dashboard.spec.ts"
---

# The dashboard, presence and working hours

## The dashboard, and what belongs to a person

`/orgs/{id}` is the organisation's home. The people roster moved to
`/orgs/{id}/people` — a roster is a reference screen you visit on purpose, and
it was only the landing page by accident of being built first.

Announcements and Away lead the page, in that order, ahead of any one
person's own escalations — the org's front page, not your personal one.
Everything below them answers a different question, and `api/routers/
dashboard.py`'s `dashboard()` builds all of it in the one request the page
needs, for the reason `services/conversations.py` gives for batching a
thread: three round-trips to render one landing screen is three chances to
show it half-built.

**Announcements are per organisation because there is no global administrator.**
No staff tier, no backoffice, nobody who *could* write to every installation.
The architecture decides that. Admins write, everyone reads, and one can carry
an expiry date — a noticeboard nobody prunes is a noticeboard nobody reads.

**Out-of-office is deliberately not private.** Its whole value is a colleague
checking before they ask you for something; a private one is a diary. You set
it on your own account, and members of organisations you share see it. The
dashboard looks two weeks ahead.

**A status line and an announcement are different things**, which is why both
exist: the first is one person's answer to "what are you on with", the second
has an author and an audience.

**Critical, Urgent, High priority, Due soon and Pinned are the same question
at five filters, and `access.my_priority_tasks_stmt`/`my_due_soon_tasks_stmt`
say so by staying siblings.** High priority is `my_priority_tasks_stmt(
priority="high")` — the identical builder Critical and Urgent already call,
not a new statement — and the identical scope too: yours, unbounded, no "top
N" cap. A request to cap it at ten was traded for staying consistent with
the two cards already there, so a future fourth priority card is one more
call to a function that already exists, not a new thing to build. Each is
"open, and mine" — either I own it or I'm
asked to act — ORed rather than the list view's usual AND filters, because
"work that's mine, either way" is one question, not two lists stitched
together client-side. `pins.my_pinned_tasks_stmt` is the odd one out only in
its source (a join to the caller's own pin rows, not a column filter); the
shape it returns and the card it renders in are identical. **Not "critical in
the organisation"**: an admin already sees everything, and mailing them every
critical task in the company is the exact notification-fatigue mistake the
comment socket avoids for the same reason. Every row on every one of these
cards distinguishes **"your action" from "waiting on someone else"** —
`is_action_required` vs `waiting_on`, resolved server-side so the UI never
has to reverse-engineer which one a task is from raw ids — and every row
also carries `is_overdue`/`is_due_today`, computed once against the same
per-viewer `today` the whole endpoint resolves, so a date's colour (the
product's one red, the product's one amber, same as status) can't disagree
with itself between cards. An empty card renders nothing: a card for a
filter that currently matches nothing is clutter, not reassurance.

**Recent activity is the one card that is not "mine."** Ten most-recently-
updated tasks, organisation-wide, sorted by `updated_at` — which a comment
bumps exactly like a status change does (`services/conversations.py`'s
`_announce()`), so a comment posted a minute ago is why a task is at the top
of this list even though nothing about its status moved. It answers "what is
everybody up to", which is a different question from every card above it,
and reuses `access.visible_tasks_stmt` rather than a bespoke query for
exactly that reason — it's the ordinary list, `.limit(10)`, nothing narrowed
to the caller's own stake.

**Changing your password verifies the current one** (`verify_credentials`, not
`sign_in` — checking a password shouldn't mint a session). A session left open
on a shared machine must not be enough to lock its owner out of their account.
SuperTokens owns the password policy and its rejection is passed straight
through; restating it here would be two rules that can disagree.

## Working hours

Read `services/working_hours.py`. A Mon–Sun × 0–23 weekly grid, yours to set
on the Account screen and any colleague's to see from the People roster —
the same "not private, deliberately" shape `services/presence.py` already
applies to out-of-office, just a recurring weekly pattern instead of a date
range. **Purely informational, for now.** Nothing reads this to decide
anything yet; the plan it exists for is a later feature that skips sending
someone a notification outside their own hours, but until that lands this
is only ever what a colleague sees, the same starting point private notes
and pins had before anything was built on top of them.

**A cell's existence IS the check**, the identical idiom `task_sheet_cells`
and `task_tags` already use: marking an hour inserts a row into
`working_hours`, clearing it deletes one. `weekday` is 0=Monday through
6=Sunday, matching Python's own `date.weekday()`, so there's no second
day-numbering convention to keep in sync with the first.

**Only you can set your own — there is no admin override.** The same
absence-of-a-branch discipline `services/notes.py` documents for private
notes, just applied to a fact this product doesn't actually keep private:
`set_cell`/`clear_cell` take the caller's own `User`, never a target id.

**Visible to anyone who shares an organisation with you**, via
`GET /organisations/{id}/members/{user_id}/working-hours` — scoped to
membership, the identical pattern `presence.away_between` already uses, not
to any finer-grained task or project access. That route's `{user_id}` is,
unlike every other `{member_id}` on the organisations router, the *user's*
own id rather than the membership row's: working hours belong to the
person, not to any one membership record, and the two only coincide by
accident. Worth knowing before adding a sibling route on that prefix.

**The timezone conversion is entirely client-side, and rounds to the
nearest hour.** The server hands back raw cells plus the owner's own
`users.timezone` (already IANA, already auto-detected — see `App.tsx`'s own
`Intl.DateTimeFormat().resolvedOptions().timeZone` call on first sight,
nothing new here); `lib/working-hours.ts`'s `convertWeek` does the shift in
the browser once both timezones are known and actually differ, using
`Intl.DateTimeFormat`'s own offset for *today* for both zones rather than
the offset on whatever day each cell nominally falls on — so a grid never
shows two different shifts for cells either side of a DST transition it
happens to straddle. A half-hour-offset zone (India, Nepal, …) is
necessarily approximate here, the same kind of documented simplification
the calendar's own hand-rolled date math already accepts elsewhere in this
product — there's no finer resolution than an hour to shift *to*, so a
40-minute-accurate answer would be false precision.

**The grid is one component, `components/working-hours-grid.tsx`, used
both editable and read-only** — `onToggle`'s presence is what tells them
apart, rather than two near-identical grids to keep in sync by hand.
Editable cells are real `<button>`s (native focus and click, no hand-rolled
keyboard handling needed); read-only cells are plain `<div>`s, so a grid
that can't be changed doesn't also claim to be clickable. Dragging across
several cells paints every one to the value the *first* cell in the drag
was set to, so marking a whole afternoon is one gesture instead of a dozen
clicks — reset on a *window* `mouseup`, not just the grid's own, so
releasing outside it still ends the drag, the same "don't trust only the
element under the pointer" reasoning `main.tsx` already applies to
cancelling a stray file drop.
