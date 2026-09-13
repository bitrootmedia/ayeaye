---
paths:
  - "apps/api/src/app/services/time_tracking.py"
  - "apps/api/src/app/models/time_entry.py"
  - "apps/api/src/app/api/routers/time.py"
  - "apps/web/src/views/Time.tsx"
  - "apps/web/src/components/timer-bar.tsx"
  - "apps/web/src/components/time-panel.tsx"
  - "scripts/e2e-time.sh"
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
