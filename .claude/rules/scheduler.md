---
paths:
  - "apps/api/src/app/tasks/**"
  - "apps/api/src/app/services/recurrence.py"
  - "apps/api/src/app/services/deadlines.py"
  - "apps/api/src/app/services/daily_summary.py"
  - "apps/api/src/app/models/task_series.py"
  - "scripts/e2e-recurring-tasks.sh"
  - "docker-compose.yml"
---

# The scheduler, recurring tasks and the worker

## The scheduler

A tenth container, `taskiq scheduler app.tasks:scheduler`, running three
hourly jobs — `sweep_reminders` (:05), `sweep_deadlines` (:15) and
`sweep_daily_summaries` (:25), staggered so they don't all land on the same
tick and compete for it. It earns its place because a reminder has to arrive
whether or not anybody has the app open: a loop inside the API dies on every
reload in dev and fires twice the day somebody runs two replicas.

It only **enqueues** — the work happens in the worker, so a slow sweep can't
delay the next tick. `LabelScheduleSource` reads the cadence off the task's own
`schedule=` label, so a job's timing lives next to the code it runs rather than
in a config file that can disagree with it.

Everything it triggers must be idempotent regardless. That is a rule about the
jobs, not about the scheduler, and it is why the reminder claim exists — and
why `services/deadlines.py` and `services/daily_summary.py` copy it rather
than inventing their own.

**The deadline sweep** (`services/deadlines.py`, `tasks/deadlines.py`)
notifies whoever's on the hook — the owner, and action-required if that's a
different person — the day before an open task's due date, once. Same
conditional-`UPDATE`-as-claim shape as `reminders.claim`
(`Task.deadline_notified_at IS NULL`), and the same `<=` rather than `==` on
the date so a sweep that missed its slot still catches up instead of skipping
the notification forever. **Whose "tomorrow"?** A task can have two
interested people in two timezones; the **owner's** decides, because they're
the one accountable for the date — the same reasoning that makes them, not
action-required, the one who can close the task. `tasks_service.update()`
clears the claim whenever `due_on` changes, for the identical reason
`reminders.update_one` clears its own stamps on a move: without it,
rescheduling a task leaves it permanently silent about its new date.

**The daily digest** (`services/daily_summary.py`, `tasks/daily_summary.py`)
sends what's planned for today (the Planner's Today bucket, **open tasks
only**) and what closed yesterday (tasks the person owns, closed in their
local yesterday), once per organisation with something to report, at each
person's own local hour. Open-only is the same rule the Planner's own buckets
apply — a plan is what's still to do — and without it a task closed
yesterday arrived under both headings of the same message. Reported after it
shipped, from a real digest; the Planner was corrected to match immediately
afterwards, having been left filtering nothing on a first reading of the
same report.
**Opt-out, default on** (`users.daily_summary_enabled`) — the point of a
digest nobody has to remember to check is defeated by a setting defaulting to
off that almost nobody would ever find. The claim
(`users.last_daily_summary_sent_on`, a date, not a timestamp — the question
is "did they get today's") is gated on the **hour** as well as the day,
which neither reminders nor the deadline sweep need: a digest that could
arrive at 3am is not a digest anybody reads, so `claim()` works out what
time it is in that zone once, in Python, and compares it against each
person's own column inside the same claiming UPDATE — one statement per
zone however many different hours the people in it chose.

**The hour is `users.daily_summary_hour` (default 6), set on the Account
screen — it used to be one hardcoded `SUMMARY_HOUR = 7` for the whole
installation.** Reported by somebody whose digest was arriving just after
midnight, which is what a single hardcoded hour does the moment a stored
timezone is wrong: the hour is only ever read against `users.timezone`, so
a stale zone moves the digest by exactly its own error and there was no
setting to reach for either way. Three things follow. The match stays
**strict equality**, not "at or after" — a missed tick costs one day's
digest, where `>=` would let a worker that was down all morning deliver at
11pm the message this gate exists to prevent. The default moved to 6 rather
than being preserved at 7, because nobody chose 7; it was the only value
there was. And the Account screen names the timezone next to the picker
(`Your own time, in Europe/Lisbon`), so a wrong zone is visible where the
hour is chosen instead of only in the read-only list below it — the zone
itself is still detected from the browser on `GET /me`, never typed, so
loading the app corrects a stale one on its own.

**One notification per organisation, never one merged across all of
them** — a digest links somewhere, the Planner is scoped to one organisation
like everything else that isn't the notification inbox, and there is no
sensible single landing page for "your day across three organisations." An
organisation with nothing to report that day is skipped rather than sent an
empty one.

**Both new notification kinds needed a migration, not just a Python
constant** — `notifications.kind` is a closed set enforced by a `CHECK`
constraint (migration 0004, extended in 0013 and again in 0019), and
`test_notification_kinds_are_a_closed_set` pins `NOTIFICATION_KINDS` against
exactly that set so the two can't drift. Adding a kind in Python without the
matching `ALTER` raises an `IntegrityError` at the worst possible moment —
while notifying somebody.

## Recurring tasks

Read `services/recurrence.py`. `task_series` is its own table (like
`task_pins`, `task_notes`, `planner_entries`) rather than columns on `Task` —
a series outlives any one occurrence of it, so it can't be a property of one.
`attach()` snapshots the task's title, description, project, owner and
priority onto a new series row, points the task at it via `tasks.series_id`,
and from then on the two are decoupled: editing the task afterwards never
edits the series, the same way editing a reminder's note doesn't reach back
into the task it's about.

**On schedule, regardless of whether the last occurrence closed — a product
decision, not an oversight.** Like a calendar event, not a checklist:
"pay rent" for September appears whether or not August's got closed, and two
open occurrences of the same series can coexist on the board. That's an
honest backlog, not a bug to hide, and it's why generation has no rule tying
it to the previous task's status.

**`sweep_recurring_tasks`** (:35 past the hour — reminders, deadlines and the
digest already hold :05, :15 and :25) claims a series with `try_claim`, then
generates the occurrence through `tasks_service.create()` — there is
deliberately not a second path that writes a `Task` row, the same reason
`app/mcp/server.py` has no `select()` of its own. Generation runs *as the
series owner*, which is what keeps `task.owner_user_id` from ever differing
from the person who set the cadence, and is why no "you're now the owner"
notification fires for a task they already knew was coming.

**No notification on generation, on purpose.** The owner set the cadence
themselves; pinging them every time their own recurring task reappears is
the exact noise `services/conversations.py` already argues against for
comments. The daily digest's "planned for today" and the dashboard's Due
soon card already cover the nudge, once the task actually needs attention.

**The claim can't be one shared-value `UPDATE`, unlike reminders and
deadlines.** Those two sweeps claim every due row in a single statement
because the claimed value is always the same (`func.now()`, or today's
date). Here the advance amount is per-row — a week for one series, a month
for another — so `try_claim` reads `next_due_on`, computes the new value in
Python, and issues a per-row `UPDATE … WHERE next_due_on = <the value just
read>`. Still race-safe (a second sweep's UPDATE matches zero rows once the
first one has advanced it), just N statements instead of one.

**`advance()` is calendar-aware for months, not `+ timedelta(days=30)`.**
The 31st plus a month lands on the shorter month's last day (Jan 31 → Feb
28/29), not six days into March — the trap naive arithmetic falls into.
Pinned by `tests/test_recurrence_rules.py`, the pure-function half of this
feature; the sweep and the claim are proved through
`scripts/e2e-recurring-tasks.sh` instead, the same split `test_access_
matrix.py`'s docstring explains for the access model.

**Stop, not delete, and not resumable.** `stop()` sets `active = False` —
the same non-destructive default as un-pinning or hiding — and the UI shows
"Stopped repeating" as permanent history on that task rather than offering a
restart. A new series always starts from whichever task is due next, the
same direction generation itself runs: forward, never back into an
occurrence that already happened. **Managing a series is creator-or-admin,
not the task's own access level** — `can_manage()` checks
`created_by_user_id`, deliberately not `can_edit` on the current task, the
same way `services/pins.py` needed its own rule rather than reusing a task
one. The reason is structural: a series can outlive the particular task it
first attached to, so by the time someone wants to stop it there may be no
one task's access level left to check against.

**Offboarding reassigns series ownership too.** `task_series.owner_user_id`
is `RESTRICT`, same as `tasks.owner_user_id`, so
`organisations._reassign_everything_owned_by` calls
`recurrence.reassign_owned_series` alongside the task and project
reassignment it already does — without it, removing a member who set up a
recurring task fails the whole removal with a raw foreign-key error.

**A service that mutates a `Task` field outside `tasks_service.update()`
must `db.refresh()` it before anything reads `updated_at` back.** Found
building `attach()`: `SessionLocal` sets `expire_on_commit=False`, so a
commit does *not* normally force a re-fetch — except `Task.updated_at`
carries `onupdate=func.now()`, and any commit that touches a dirty `Task`
still needs that one column's real value back from Postgres regardless of
the session-wide flag. Read it before that refresh happens and SQLAlchemy's
async ORM raises `MissingGreenlet` — a lazy load attempted outside an
awaited call — which look nothing like "you forgot to refresh an object"
unless you already know to look for it. `tasks_service.update()` already
gets this right (it refreshes at the end); `recurrence.attach()` didn't
until this bug surfaced it. Anywhere else that flips a `Task` column via a
raw `db.execute()`/`db.commit()` rather than going through
`tasks_service.update()` is a candidate for the identical crash.

## The worker registry

- **New taskiq handler modules must be imported in `tasks/__init__.py`** or the
  worker never registers them, with no error anywhere to say why.

## The redis pin

- **`redis` is pinned `<6`**: taskiq-redis 1.2.x's blocking listen loop crashes
  on redis-py ≥6.
