---
paths:
  - "apps/api/src/app/services/projects.py"
  - "apps/api/src/app/services/teams.py"
  - "apps/api/src/app/api/routers/structure.py"
  - "apps/api/src/app/models/structure.py"
  - "apps/web/src/views/Project*.tsx"
  - "apps/web/src/views/Teams.tsx"
  - "apps/web/src/lib/view-preference.ts"
  - "scripts/e2e-projects.sh"
  - "e2e/tests/access.spec.ts"
---

# Projects, teams and the projects list

## The Projects list: stats, filtering, table view

`GET /projects` carries two counts per project now —
`open_task_count` and `important_task_count` — from
`access.project_task_stats_stmt`, one `GROUP BY` over every project in the
organisation rather than one query per card. **Grouped over *task*
visibility, not project visibility.** Those are different sets: a project
grant doesn't override a hidden task, and a task-level grant can reach
further than the project's own — so counting by `task_level_expression`
rather than by "projects I can see" is what keeps the number from leaking
what's on a project beyond what the rest of the product already shows. Only
`list_projects` populates real numbers; `create_project`/`get_project`/
`update_project` send the schema's `0`/`0` default, the same scope choice
`_recurrence_for` made for the task list — accurate where the feature
actually lives, not threaded through every endpoint that touches the model.

**"Important" merges critical, urgent and high into one number, on
purpose.** The three-way breakdown already exists — it's the dashboard's own
Critical/Urgent/High cards — and repeating it here on an already-dense card
would be the same information twice, differently shaped. Muted, not
coloured: status still owns the product's only red and only amber, and this
number is a sum across three priority levels, not an instance of either.

**The name filter is client-side**, unlike the task list's server-side
one. "Everything you can see" was never paginated to begin with — it's one
full fetch already — so narrowing what's already on screen doesn't earn a
round trip the way filtering a paged list does. The **view toggle does**
live in the URL (`?view=table`), same reasoning as the task board/list
toggle: a view somebody arrived at is one they can send a colleague. The
table is a real `<table>`, the first one in the product — the task list's
own "list" view is div rows, not semantic markup, and there was no reason
to match that when the ask was specifically a table.

**Absent the param entirely, both toggles fall back to a remembered
preference, not always the same hardcoded default.** `lib/view-preference.ts`
is a thin `localStorage` wrapper, the same shape and the same brand-free-key
reasoning as `lib/theme.ts`. Set only on an explicit toggle click, never on
landing via a URL that already names a view — a colleague's table-view link
must not silently become your own permanent default just because you
followed it once. The URL still wins whenever it's present; the remembered
value is only ever the fallback for "no `?view=` at all," which is what
happens the next time you navigate here from the rail rather than from a
link.

**Each project now carries a second, explicit link — straight to its
board — alongside the name that has always gone to its own page.** Before
this, the only way to a project's tasks was a detour through that page
first (which itself already had an "Open the board" button once you got
there); the list only ever offered the one destination. Added, not
swapped: the name still goes to the project's own page — access, rename,
export, the danger zone, everything that reads as "settings" — because
`createProject`'s own e2e helper (and everything built on it, `access.
spec.ts` among others) clicks that link and asserts it lands there, and
changing what the primary link means out from under a shared helper would
have been a silent, test-suite-wide regression for a UX call nobody asked
to make. `KanbanSquareIcon`, not `LayoutGridIcon` — the page already uses
that one for its own Cards/Table toggle, and reusing it here for an
unrelated destination would read as the same button doing two things.

**The card grid's outer element had to stop being a `<Link>`, not just
grow a second link inside it.** An anchor can't nest another anchor — the
identical "no interactive element inside another one" rule the notepad's
own card and the notification inbox's row both hit — so the card became a
plain `<div>` holding two sibling links (name, board icon) instead of one
link wrapping everything. The table view never had this problem: its Name
cell was always just the name, never the whole row, so the new board icon
is simply one more cell.
