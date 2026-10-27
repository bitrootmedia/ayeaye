---
paths:
  - "apps/api/src/app/services/time_tracking.py"
  - "apps/api/src/app/models/time_entry.py"
  - "apps/api/src/app/api/routers/time.py"
  - "apps/web/src/views/Time.tsx"
  - "apps/web/src/components/timer-bar.tsx"
  - "apps/web/src/components/time-panel.tsx"
  - "scripts/e2e-time.sh"
  - "apps/api/src/app/services/work_reports.py"
  - "apps/api/src/app/api/routers/work_reports.py"
  - "apps/web/src/views/WorkReports.tsx"
  - "scripts/e2e-work-reports.sh"
---

# Time tracking

## Time tracking

Read the `services/time_tracking.py` docstring. Four rules, and the first is a
database constraint rather than a convention.

**One running timer per person, globally.** `uq_time_entries_one_running` is a
partial unique index on `(user_id) WHERE ended_at IS NULL`. Not scoped per
organisation — you are only doing one thing at a time, and a per-org constraint
would let someone run three timers by belonging to three organisations.

**Starting a timer stops the one already running**, and returns it in the
response so the UI can say so. Refusing with a 409 would make the answer to
"why won't it start" a modal; switching tasks is the commonest thing anyone
does with a tracker.

**`read` on a task is enough to log your own time.** It is a record of what
*you* did. A contractor with view access who can't record their own hours is
the wrong failure. Only the person who logged an entry — or an organisation
admin — may change it; **the task owner cannot**, because someone else's
timesheet isn't theirs. That distinction is only testable between two plain
members, which is why `scripts/e2e-time.sh` has four accounts.

**Entries stay editable, with a trail** (PLAN.md §9). Every correction stamps
`edited_at` and writes a `task_events` row, so a rollup that changes has an
explanation.

Things that bite:

- **The clock ticks client-side.** `TimerBar` computes elapsed from
  `started_at` against the browser clock and corrects for drift using the
  server's own `seconds`. Polling per second would be a request per second per
  tab to render a predictable number; the 30-second poll only exists to notice
  a timer started or stopped in *another* tab.
- **`ended_at IS NULL` is the only definition of "running".** There is no
  boolean beside it that could disagree.
- **Rollups compose `visible_task_ids_stmt`**, so they aggregate over exactly
  the tasks the board shows. Two people will legitimately see different totals
  on the same screen — that is the access model, not a bug in the arithmetic.
- **Anything that writes a `task_events` row must also refresh the task**, not
  just its own panel. The History card sits on the same screen, and refreshing
  one and not the other makes the trail look like it recorded nothing.
- **A running timer asks "still working on this?"** — `services/check_ins.py`,
  read its docstring. The server asks, never a client: a question only the menu
  bar app could ask reaches only people running it, and the forgotten timer
  belongs to somebody who isn't. State is three columns on the running entry
  (`next_check_in_at`, `check_in_asked_at`, `check_in_deadline`);
  `sweep_timer_check_ins` runs **every minute**, because an hourly tick would
  stretch a 15–30 minute wait to 75. Asked in Telegram (two inline buttons,
  arriving at the webhook as a `callback_query`), in the web header
  (`GET /me/timer`'s `check_in_deadline`, answered by `POST /me/timer/check-in`)
  and in the menu bar app (`running_timer`'s `check_in_deadline=`, answered by
  the `answer_check_in` MCP tool). No answer ends the entry **at
  `check_in_asked_at`**, not at the deadline — the unanswered wait is the one
  stretch known not to be work — and raises `timer_paused`. Preference and
  daily cap are `users.timer_check_ins` / `timer_check_ins_per_day`, on the
  Account screen; the cap counts the person's own local day. Asking publishes
  a realtime ping directly rather than through `tasks_service.announce`, which
  would bump the task's "last activity" for a question nobody has answered.
  `scripts/e2e-check-ins.sh` proves every path by moving the clock with psql.

## Work reports

`views/WorkReports.tsx` at `/orgs/:orgId/reports`, over
`GET .../reports/work` and `GET .../reports/now`. Read the
`services/work_reports.py` docstring. **Organisation admins only** — the
rail only offers it to them (`canSeeWorkReports`) and the server answers
anyone else with a **403**, which the screen turns into a sentence. `/time`
already shows everyone the hours on tasks they can see; this is a question
about *people*, which is an admin's.

- **It composes `entries_in_scope` and does not widen it.** Hours on
  somebody else's hidden task are missing from the report exactly as the
  task is missing from the board. Counting them under a placeholder would
  tell an admin a hidden task exists. `e2e-work-reports.sh` pins it.
- **Entries are clipped to the window and spread across the wall-clock
  hours they cover** (`spread`), so an overnight entry lands on both days
  and a three-hour block fills three cells of the activity grid. Slices are
  **fractional seconds, rounded once at the end** — truncating each slice
  lost a second an hour and showed a 2h 30m entry as 2h 29m.
- **Dates and hours are the viewer's zone**, sent as `tz` from the browser
  and echoed back; a zone the server doesn't know reads as UTC rather than
  an error, the same "ignore what you can't read" rule as an unknown sort
  key.
- **The arithmetic is Python over one statement's rows.** Access is still
  one SQL statement; an admin's window over a team is a few thousand rows,
  and the range is capped at 366 days.
- **"Right now" is four statements, never one per member**: active members,
  running timers in scope, open in-progress tasks they own, and last logged
  time. A timer on a task the admin can't see reads as nothing running.
- Filters live in the URL (`since`, `until`, repeated `user`, `project`).
  The charts are hand-drawn divs, not a chart library: one hue, bars from
  the baseline, a hover readout above each plot.
