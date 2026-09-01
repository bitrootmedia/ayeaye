# ayeayecaptain

Project and task management, self-hosted first. One FastAPI backend, one React
app, one Postgres, one hostname.

[PLAN.md](PLAN.md) is the brief and the reasoning behind the decisions. This
file is the state of the code and the rules that hold it together. Where the
two disagree, PLAN.md is the intent and this file is what actually exists.

**Reference implementation:** `/Users/q/Projects/tuts/modern` (the `prohandl`
repo) — same stack, different domain. Its `CLAUDE.md` is worth reading for the
chat, media and notification subsystems that land in later phases here. Copy
from it deliberately, never wholesale: the domain overlap is close to zero.

## Where we are

**Phases 0 through 9 are done and verified. The plan is complete.**

*Phase 0 — foundation.* Register, sign in, sign out, forgot password, reset
password with the link landing in Mailpit and the old password rejected
afterwards. A local `users` row is created on first authenticated request. The
app shell, the design tokens, `GET`/`PATCH /me`, light/dark.

*Phase 1 — organisations.* Create, list and switch between them; membership
with `owner`/`admin`/`member`; invite by email with pending binding at signup;
a copyable invite link that works with no SMTP at all. Org switcher in the
rail, people roster, role editing, leaving, and deleting an organisation.

*Phase 2 — structure and access.* Teams, project groups, projects, and
`services/access.py`. Projects are private to their owner; grants go to a
person or a team at `read`/`write`; organisation admins see everything. The
project screen states all three routes in explicitly. Plus archiving,
ownership transfer, and the access panel.

**PLAN.md sequences access as Phase 3, after structure. It was built with
Phase 2 instead**, because the product decision is that projects are private
by default — shipping "every member sees every project" first and inverting it
later is exactly the kind of default that survives by accident. What remains
of Phase 3 is task-level grants, which arrive with tasks.

*Search.* Fuzzy search across tasks and projects from anywhere (⌘K), inside
the access model by construction. Postgres + `pg_trgm`, not a search engine —
the reasoning is below and it is a decision, not an assumption.

*Phase 4 — tasks and workflow.* Tasks in a project or loose, the five-status
set with open/closed separate, owner and action-required, per-task grants, the
append-only `task_events` history, and a per-person notification inbox with
email nudges from the worker. Board and list views, task detail, and offboarding
that reassigns rather than blocking.

*Phase 5 — time.* One running timer per person enforced by a partial unique
index, manual entries typed the way people say them ("1h30"), corrections with
a trail, rollups by person/project/task, and the work history. A live clock in
the header that follows you across screens and organisations.

*Phase 6a — comments and realtime.* Threads on tasks and projects, live over a
WebSocket, with notification debouncing. Editing, soft delete, per-person read
cursors.

*Phase 6b — attachments and voice notes.* Files and images on comments,
uploaded browser → storage directly via a presigned three-step handshake.
RustFS behind Caddy at `/media/*`. In-browser voice notes with a waveform
decoded from the real audio.

*Auth screens.* Restyled with the product's own tokens, light and dark.

*Phase 7 — self-host polish.* `scripts/setup.sh` generates real secrets;
`scripts/diagnose.sh` triages an installation read-only. Verified by wiping
every volume and walking the stranger's path — two commands to a working
install, then every suite green against it.

*Phase 8 — the task screen.* Priority (six levels, `normal` the default), a
unified Files panel on the task with image thumbnails and a lightbox, the
searchable `EntityPicker` in place of every dropdown that can grow, changing a
task's project from the task itself, and a board that groups by status **or**
by priority.

*Phase 9 — the things people asked for once they'd used it.* Hidden tasks,
tags (including the one that takes work off the board), private notes,
reminders with a scheduler, the account screen, and an organisation dashboard.
Six features, in dependency order rather than the order they were asked for:
hiding rewrites the access expression everything else composes.

Verified by 229 infra-free unit tests, 534 end-to-end checks over HTTP
(`./scripts/e2e-*.sh`) and 125 browser tests in a real Chromium
(`./scripts/e2e-browser.sh`), which also photograph every screen in both
themes into `e2e/artifacts/shots/`.

The plan is complete. What's left is judgement calls, not phases: the open
questions in PLAN.md §9 that are genuinely product decisions, and whatever
using it surfaces.

## The four decisions that shape everything

Taken in PLAN.md, restated here because they are the ones most likely to be
undone by accident.

**1. No policy engine.** The reference project carried Casbin and it earned
nothing: plain RBAC with exact string matching can neither express "user U may
read task 47" nor answer "list every task U can see" — and that second question
is what every list endpoint asks. This product is *entirely* per-resource and
has no staff tier at all, so authorization is `services/access.py`: a membership
row, grant tables, and SQL builders that resolve visibility in one statement.
Org-level roles are a column, not a policy store.

Consequence enforced by a test: **`users` has no `role`, `kind` or `is_admin`
column.** What a person may do comes from their membership and their grants,
never from an attribute of the account. A second place to look when something
is denied is exactly the thing being avoided.

**2. One React app, no shared package.** Four apps forced `source(none)` plus a
per-app `@source`, a repo-root Docker context and a workspace-aware install.
None of that exists here: standard Tailwind, app-scoped Docker contexts,
shadcn components copied straight into `apps/web/src/components/ui/`. Extract
`packages/ui` the day a second frontend appears, not before.

**3. One compose file, and it is the production one.** In the reference, dev
and prod were two files and a deploy that forgot `-f compose.prod.yml` brought
up the dev stack on the server: no reverse proxy, the site dark, every
container healthy. Here `docker-compose.yml` is production-shaped and
`compose.override.yml` — auto-loaded in a checkout, absent on a server — makes
it dev. `docker compose up -d` is correct in both places and there is no flag
to forget.

**4. Email is optional.** SMTP is the biggest obstacle to a five-minute
self-host, so nothing may hard-depend on it. With `SMTP_HOST` empty the mailer
logs the message and returns. Password reset degrades to a link in the API log
(`security/email.py` swallows send failures on purpose — the token is already
issued, and failing the request would tell the user to try again while a
perfectly good link sat in the void). Every invite must also produce a copyable
link in the UI.

## Single origin

The SPA, the API, the auth routes and every future upload share one hostname.
This is a product decision — there is no backoffice and no second surface — and
it is load-bearing:

- the session cookie is first-party, so no cross-site cookie rule applies;
- CORS is a formality, kept only for someone hitting the API port directly;
- a self-hoster needs one DNS record and one certificate.

`SITE_URL` is the single source of it, **scheme included**. `http://localhost`
tells Caddy to serve plain HTTP with no certificate, which is what makes the
laptop case work with zero edits; `https://tasks.example.com` turns on
automatic HTTPS. The same variable configures Caddy's site address and the
API's `api_domain` / `website_domain`, so they cannot drift.

**Dev uses Caddy too.** The Vite dev server is behind it on `http://localhost`
exactly as nginx is in production, and its port is deliberately not published.
Cookies, redirects and CORS therefore behave identically in dev and prod, which
kills the class of bug you otherwise only find after deploying. The one
consequence: Vite's HMR websocket has to be told the port the *browser* sees
(`hmr.clientPort` in `vite.config.ts`), or it silently dials 5173 and never
connects.

The frontend bundle contains **no hostname**. `config.ts` falls back to
`window.location.origin`, so one built image runs on any domain — which is what
makes self-hosting a `docker compose up` rather than a rebuild.

## Layout

```
ayeayecaptain/
├── docker-compose.yml       # production-shaped. THE stack.
├── compose.override.yml     # dev: bind mounts, reload, Mailpit
├── .env.example             # committed; it IS the configuration docs
├── infra/
│   ├── caddy/Caddyfile      # one site, path-routed
│   └── postgres/init.sql    # creates the separate `supertokens` database
├── scripts/                 # end-to-end suites; need the stack up
├── e2e/                     # Playwright. Its OWN package — see below.
└── apps/
    ├── api/
    │   ├── alembic/         # migrations, authored in dev and committed
    │   └── src/app/
    │       ├── main.py      # create_app(): middleware + router mounting ONLY
    │       ├── core/        # config, logging, lifespan, mailer
    │       ├── db/          # base.py (no engine), session.py
    │       ├── models/      # user, organisation (+ membership/invitations),
    │       │                #   structure (teams, groups, projects, grants),
    │       │                #   task (+ grants, events), tag (+ task_tags),
    │       │                #   checklist (+ items), sheet (+ rows/columns/cells),
    │       │                #   note (private, per person), personal_note (the notepad),
    │       │                #   mfa (totp devices, backup codes — hand-rolled, see below),
    │       │                #   export (a ZIP build, requester-only, autodeletes),
    │       │                #   reminder,
    │       │                #   presence (out of office, announcements),
    │       │                #   notification,
    │       │                #   time_entry, conversation (+ messages, reads,
    │       │                #     attachments — anchored to a task OR a thread)
    │       ├── api/         # deps.py, router.py, routers/ (thin)
    │       ├── services/    # the business logic
    │       │                #   access.py        — ★ who can see what. read first
    │       │                #   organisations.py — pure rules on top, SQL below
    │       │                #   invites.py       — the two ways in
    │       │                #   teams.py projects.py tasks.py
    │       │                #   time_tracking.py search.py
    │       │                #   conversations.py — comments ARE the thread
    │       │                #   tags.py checklists.py sheets.py notes.py personal_notes.py
    │       │                #   mfa.py — hand-rolled TOTP, not SuperTokens' paid recipe
    │       │                #   exports.py — yours only, not even an admin's
    │       │                #   reminders.py presence.py
    │       │                #   notifications.py — everything notifying goes here
    │       ├── realtime/    # ConnectionManager + Redis pub/sub
    │       ├── storage/     # s3.py — two endpoints, and why
    │       ├── security/    # authn (SuperTokens), email (reset delivery)
    │       └── tasks/       # taskiq broker + scheduler; handlers MUST be
    │                        #   imported in __init__.py or the worker never
    │                        #   sees them
    └── web/
        ├── Dockerfile{,.prod} + nginx.conf   # app-scoped context
        └── src/
            ├── main.tsx     # SuperTokens.init + routes
            ├── App.tsx      # shell: rail, header, the /me gate
            ├── api.ts       # fetch helper + ApiError(status)
            ├── config.ts    # origin derivation
            ├── index.css    # THE design tokens
            ├── components/ui/   # shadcn (generated; re-add to update)
            └── views/       # one file per screen
```

## Conventions

**UUIDv7 primary keys, everywhere.** A single column called `id`,
`server_default=text("uuidv7()")` (a Postgres 18 builtin). Time-ordered, so it
indexes like a sequence and sorts chronologically, without leaking a row count.
A test walks `Base.metadata` and fails any table that departs from this — a
model that forgets the server default works fine from Python and then breaks on
any raw INSERT.

**No access reads as 404, never 403.** 403 means only "you can see this, but not
at that level". `ApiError` on the client carries the status so the UI can tell
them apart.

**Every list endpoint resolves access in ONE statement.** Never a per-row check
inside a loop. This is the discipline that makes the access model survive
contact with real data.

**A list that can grow is paged, and says what it is a page of.** `/tasks`
takes `limit`/`offset` and returns `X-Total-Count`; the board has its own
endpoint because a board **cannot** be paged with `LIMIT` — its rows come back
priority-first, so the first N of several thousand are all criticals and four
columns arrive empty. `access.board_stmt` bounds each column with
`ROW_NUMBER() OVER (PARTITION BY …)` and reports each column's real size with
`COUNT() OVER (…)`, in the same statement. There is **no default limit**: a
silent cap is worse than a big response, because the caller believes they have
everything.

**Routers are thin.** HTTP in `api/routers/`, logic in `services/`. `main.py`
assembles and does nothing else, so it doesn't grow as the API does.

**The rail's organisation is not the URL's.** Your notifications, reminders,
account and the organisations list all sit outside any organisation — but you
are still *working in* one, and dropping the whole nav section the moment you
glance at a list leaves no way back except clicking through it. `railOrg`
falls back to the last one you were in; the header still describes the *page*,
so the two don't contradict each other. Search follows the rail for the same
reason: if the nav claims an organisation, ⌘K has to search it.

**Sans for interface, mono for data.** Every id, duration, timestamp and figure
is `font-mono` with tabular figures so columns line up. Time tracking makes
this pay off.

**Colour lives in a dot, not a pill.** Status renders as a stock
`Badge variant="outline"` plus a coloured dot. A table of saturated pills is
confetti, and the dot keeps the label at full contrast.

**One colour scale, and status owns it.** Exactly one red (blocked) and one
amber (in review) across the whole product. Anything else that needs a scale
gets shape instead — priority is six chevrons, with colour on the top two
only. Add a second full colour scale and red stops meaning "this needs you".

**The list is a table; the board is cards.** They answer different questions,
so they are not two skins on one component: the table shows task, project,
status, priority, owner, action-required, created and updated, every column
sortable, with filters above it. **Sorting and filtering are the server's
job** — the list is a page, so ordering in the browser would only order the
hundred rows it happens to be holding. Both live in the URL, so a view
somebody arrived at is one they can send to a colleague.

**Status and priority sort by rank, never alphabetically.** "blocker,
in_progress, on_hold, review, todo" orders the spellings, not the work.
`STATUS_RANK` and `PRIORITY_RANK` are the only places that order is written
down. People and projects sort by *name*, not id, through correlated scalar
subqueries — a join would change the statement's shape and the board shares
the builder.

**An unknown sort key is ignored, not rejected.** The value comes from a URL
people edit and share; a link naming a column that no longer exists should
show the default order, not an error page.

**A field that can grow uses `EntityPicker`, not a `Select`.** Projects and
people are unbounded; a native-feeling dropdown you can only scroll is fine at
six entries and useless at eighty. The picker opens with its filter already
focused, so choosing is "type three letters, Enter". Short fixed lists
(status, priority) use it too — a card where one control opens differently
from the four above it reads as a bug.

## Access — read `services/access.py` first

Four rules, in that module's docstring, and everything follows from them:
private until shared, most-permissive-wins, no-access-is-404, one statement per
list. Do not re-derive any of them anywhere else.

**The rule exists twice, deliberately.** `effective_level()` is the Python
statement of most-permissive-wins; `project_level_expression()` is the same
rule as a `GREATEST(...)` for the planner. They live in the same module so they
can be read together. `tests/test_access_matrix.py` proves the Python one over
the full grid with no database; `scripts/e2e-projects.sh` proves the SQL agrees
with it through Postgres. Neither test can cover the other's half — that is why
there are two.

Things that will bite:

- **`owner` is never stored.** It's what owning the project or administering
  the organisation *resolves to*. A stored `owner` grant would be a second
  answer that can disagree with `projects.owner_user_id`.
- **The grant subquery's join to `team_members` must be a LEFT join.** An inner
  join drops every direct grant, because a direct grant has a NULL `team_id`
  and matches no team-member row. The single `OR` over both principals only
  works because of it.
- **A project group is a label, not an access boundary.** You cannot grant on
  one, and filing a project in a group gives nobody access. Deleting a group
  is `ON DELETE SET NULL` — the folder goes, the work stays.
- **There are no deny rules and there must not be.** The consequence people
  expect otherwise: you cannot make one member of a team read-only when the
  team has write. Rule 2 says the broader grant wins. **A hidden task is not a
  counter-example** — it short-circuits before any route is resolved rather
  than competing with them inside the `GREATEST`. See the top of `access.py`.
- **Handing over ownership can cost you the project.** `POST .../owner` returns
  204 with no body on purpose: re-resolving the caller's level to build a
  response 404s, on a commit that already succeeded. Task ownership (Phase 4)
  has the identical shape — don't rediscover it. **It wasn't rediscovered in
  time.** `update_task`'s `PATCH` handler *did* re-resolve the caller's level
  after every edit, to build the response — and a member clearing their own
  `action_required` (their only route into a loose task) got a 404 on a save
  that had just succeeded: the mutation committed, the owner's notification
  sent, and the response itself claimed the task no longer existed. Fixed by
  wrapping the re-resolution in `try/except HTTPException`, falling back to
  the pre-update level on failure — the same "don't re-resolve a level a
  successful commit just took away" rule as the bullet above, just with a
  body to still build rather than a 204 to skip. `scripts/e2e-tasks.sh` pins
  it: clearing your own action-required now asserts `200`, not `404`.
- **A task can be shared without sharing its project.** `TaskDetail.tsx`'s
  "Who can see this" card is `components/access-panel.tsx` — the identical
  component `ProjectDetail.tsx` already used — reused, not duplicated.
  Generalizing it took one prop: `projectId: string` became
  `basePath: string` (the caller passes
  `` `/organisations/{orgId}/projects/{projectId}` `` or
  `` `/organisations/{orgId}/tasks/{taskId}` ``), and the three URL template
  literals inside it (share, change level, revoke) read `${basePath}/access...`
  instead of rebuilding the project path by hand. The `access` prop needed no
  type change at all: `TaskAccess` is a strict structural superset of
  `ProjectAccess` (same four fields, plus `action_required`, `project_name`,
  `inherits_from_project`), and TypeScript accepts a wider-typed variable
  wherever the narrower type is expected — excess-property checks only fire
  on object literals, never on variables — so the panel stays typed against
  `ProjectAccess` and a task's own access state passes straight through with
  no cast. The task screen's own `TaskAccessCard` kept only what
  `AccessPanel` doesn't know about — the hidden-task banner, the
  action-required row, and the "Anyone who can see {project}" sentence — and
  stopped rendering owner/grants/admins itself. `scripts/e2e-task-sharing.sh`
  is the dedicated regression: a colleague with zero project access gains
  exactly the one task they were granted, never the project it's filed in,
  and a `read` grantee can't re-share it (sharing is `write`).

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
sends what's planned for today (the Planner's Today bucket) and what closed
yesterday (tasks the person owns, closed in their local yesterday), once per
organisation with something to report, around each person's local 7am.
**Opt-out, default on** (`users.daily_summary_enabled`) — the point of a
digest nobody has to remember to check is defeated by a setting defaulting to
off that almost nobody would ever find. The claim
(`users.last_daily_summary_sent_on`, a date, not a timestamp — the question
is "did they get today's") is gated on the **hour** as well as the day,
which neither reminders nor the deadline sweep need: a digest that could
arrive at 3am is not a digest anybody reads, so `claim()` checks
`datetime.now(tz).hour == SUMMARY_HOUR` in Python before it ever runs the
UPDATE. **One notification per organisation, never one merged across all of
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

## Organisation settings, and where the data export lives

`/orgs/{id}/settings` — its own screen, with its own gear icon in the rail,
`views/OrganisationSettings.tsx`. It didn't start that way: rename, the
two-factor requirement, deletion and `ExportCard` were all a second,
unrelated card at the bottom of `/people`, because that screen already
existed when data export shipped and nobody had asked for a settings screen
yet. The result was a genuine discoverability bug — a real "take your data"
button existed from the day exports landed, and the only way to find it was
to scroll past the entire member roster on a page whose own nav label is
"People." Moved out once it was reported.

**`ExportCard` is visible to every member, not gated on the same role check
as the rest of the page.** A data export is scoped to the requester's own
visibility (`services/exports.py`'s own "no branch that grants anybody else
access" rule), not an admin privilege — a plain member exporting their own
view of the organisation is exactly the intended use, so the card renders
unconditionally while the rename/MFA/delete card beneath it stays gated on
`canRename` / `canRequireMfa` / `canDeleteOrg`, precisely as it was on the
People page. `screenshots.spec.ts` photographs the new screen in both
themes (`03b-organisation-settings`, `17-organisation-settings-dark`).

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

## Rich task descriptions

Read `services/richtext.py`. A description is **sanitised HTML** now, and that
one change touches three things people don't expect:

**The client is never trusted.** The editor emits tidy markup and that is
irrelevant — anyone can `PATCH` a `<script>` with curl, and the next person to
open the task runs it. Every write goes through `sanitise()` and an
**allow-list**, because a block-list is a list of the attacks somebody already
thought of. `dangerouslySetInnerHTML` in `RichText` is safe *only* because of
this; don't point it at anything that hasn't been through that function.

**Search must not match markup.** `ILIKE '%div%'` against stored HTML matches
every task in the database, and snippets would show tags instead of prose.
`tasks.description_text` is a **generated column** — Postgres strips the tags,
so it cannot drift the way a column maintained in Python would, needs no
backfill and no second write path. Search and snippets read it; nothing else
does. `regexp_replace` is immutable, which is what makes it indexable.

**An image is an attachment, not a URL.** A presigned URL expires, so storing
one would fill a description with dead images within the hour. The body holds
`data-attachment-id` and nothing else; the server mints a fresh URL per read,
batched per page. Two consequences worth having: a `src` from the client is
*dropped*, so a description can't load a tracking pixel from someone else's
server — and a pasted screenshot is a task attachment like any other, so it
turns up in the Files panel with no second mechanism.

Things that will bite:

- **Tiptap's `Image` node silently drops unknown attributes.** `TaskImage`
  re-declares `data-attachment-id` with `parseHTML`/`renderHTML`; without it
  the id survives exactly until the first round trip and every picture goes
  blank.
- **The editor keeps the URL that `confirm` returned.** The body stores only
  the id and the server adds `src` on read — so before the first save there is
  nothing to display, and a freshly pasted screenshot rendered as its own alt
  text. An upload that worked, looking exactly like one that hadn't. The copy
  is for the current editing session only; `sanitise()` drops `src` on write,
  so nothing stale is ever stored.
- **A toolbar button must `preventDefault` on mousedown.** Otherwise clicking
  it blurs the editor, the chain's `.focus()` restores it a tick later, and
  the first character typed afterwards is swallowed — it cost the first letter
  of every emphasised word.
- **Old descriptions are plain text and stay that way.** A one-way conversion
  of everybody's data, to fix rendering, is a trade nobody asked for. `RichText`
  detects the absence of `<` and renders with `whitespace-pre-wrap`.
- **No font families and no text colours.** Colour in this product means
  status; a description that can paint itself red can imitate "blocked". Code
  blocks are the exception — there the colour carries syntax.

## MCP — somebody's own assistant

Read `app/mcp/server.py`. **Every tool resolves through `services/access.py`,
as the token's owner** — there is deliberately not a single `select()` in that
module. A query written there would be a second access path, and the moment
there are two, one of them is wrong and nobody knows which. `scripts/e2e-mcp.sh`
proves the refusals: a stranger's token, an org admin against a hidden task,
and a read-only token against every write.

**Personal access tokens, not OAuth and not the session cookie.** An MCP client
is not a browser, and a self-hosted installation should not have to run an
authorisation server to let one person connect one assistant. The token is the
authority, so it is shown once, SHA-256 at rest, scoped `read`/`write`, and
revocable from the screen that made it. `require_write` is the single place a
read-only token is turned away.

**`attach_file` is the one place a file's bytes pass through the API**, and
that is a deliberate, narrow exception to Attachments' "browser → storage
directly" rule below — an MCP client has no browser and no direct route to
the bucket, so the three-step handshake collapses into one call: create the
`pending` row, write the bytes with `s3.put_object_bytes` (the same primitive
the thumbnail worker uses — same class of caller, not a browser subject to
its own bandwidth), then run the *same* `confirm()` the browser path runs, so
the real size and the real content-type still win over whatever was declared.
Base64 costs roughly a third more than the file's own size, both on the wire
and in the calling assistant's context, which is the reason this isn't
positioned as a bulk-transfer channel — it exists for what someone would
plausibly paste into a chat, not for shipping a phone video through an LLM's
context window.

Four things cost real time here, all of them non-obvious:

- **There are two classes called `Context` in the SDK.** The tool decorator
  only recognises `mcp.server.mcpserver.context.Context`; passing the other
  type-checks fine and then fails at registration with a Pydantic
  `IsInstanceSchema` error that says nothing about the actual mistake.
- **`Mount` never matches its own bare path.** Mounting the transport at
  `/mcp` puts the endpoint at `/mcp/`, and a POST to `/mcp` gets a 307 that
  the client doesn't follow — surfacing as "Unexpected content type:", the
  empty body of the redirect. `MCPPath` in `main.py` rewrites the one path.
- **DNS-rebinding protection defaults to 127.0.0.1.** Behind Caddy the Host is
  whatever `SITE_URL` says, so every call is refused with "Invalid Host
  header", which reads like a proxy fault. `SITE_URL` feeds it, as it feeds
  everything else.
- **Stateless, on purpose.** A stateful transport hands out a session id and
  expects the next call to reach the worker that issued it — but uvicorn runs
  several and nothing is shared. Same reasoning as putting realtime through
  Redis; here the cheaper answer is to need no session at all.
- **The claude.ai web/desktop "Add custom connector" UI cannot connect to
  this server, full stop — and the error it gives ("Couldn't register with
  ayeaye's sign-in service… add an OAuth Client ID") looks like a config
  problem on our side and isn't one.** That UI unconditionally attempts
  OAuth Dynamic Client Registration against whatever URL it's given, even
  when the server advertises no OAuth metadata at all — a reported,
  currently-open limitation on Anthropic's side
  ([anthropics/claude-ai-mcp#457](https://github.com/anthropics/claude-ai-mcp/issues/457),
  [#112](https://github.com/anthropics/claude-ai-mcp/issues/112)), not
  something a server can opt out of. The "add an OAuth Client ID" fallback it
  offers doesn't help either — there is no client ID, because there is no
  authorisation server, on purpose (the point above). The Claude Code CLI's
  `claude mcp add --header "Authorization: Bearer …"` is the one client path
  that actually skips OAuth discovery and uses the static token, which is why
  that's the only command README's "Your own assistant" section shows —
  don't add a second one for the web connector, because there isn't a working
  one to add.

**A warning about testing it from a shell.** `e2e-mcp.sh` builds every payload
with `python3 -c json.dumps`, never with escaped quotes inside a shell string.
The inline form silently mangled the request for the calls with the most
arguments — the shell passed a fragment, the server correctly answered
"Parse error", and the harness's own helper swallowed it. It looked exactly
like MCP was losing writes, and it cost an hour of hunting a bug that was
never in the product.

## Self-hosting

The bar from PLAN.md §8, and how each part is held:

- **Two commands to a working install.** `./scripts/setup.sh && docker compose
  up -d`. Verified by wiping every volume and doing exactly that, then running
  all eight end-to-end suites against the result.
- **Secrets are generated, not copied.** `cp .env.example .env` was a trap: it
  works, which is the problem — the stack comes up with a database password
  that is committed to a public repository. `setup.sh` refuses to overwrite an
  existing `.env`, because that file holds the only copy of the password that
  opens the volume.
- **Missing configuration aborts loudly.** `${VAR:?...}` in compose, so a
  `.env` that predates a release stops everything with an explanation rather
  than starting eight healthy containers around an empty value. `diagnose.sh`
  diffs `.env` against `.env.example` for exactly this.
- **Works on localhost with zero edits**, because `SITE_URL` carries its scheme
  and `http://` tells Caddy not to attempt a certificate.
- **Migrations apply themselves** via the one-shot `migrate` service. A
  self-hoster is never asked to run alembic.
- **Backups need two commands, and the README says so.** The database *and* the
  attachment volume — a database backup alone restores every comment with every
  attachment broken.

`diagnose.sh` is deliberately read-only and every check is a failure that has
actually happened in this stack. One is worth repeating: **`/media/` returning
200 is a bug, not health.** S3 answers an anonymous bucket listing with 403, so
403 proves RustFS replied; a 200 means the SPA catch-all swallowed the route
and every attachment is quietly broken.

**The Storage section reuses the app's own code to test itself.** Rather than
reimplementing an S3 client in bash, it `docker compose exec`s into `api` and
calls `storage.s3.internal_client().head_bucket(...)` with `PYTHONPATH=/app/src`
— the exact endpoint, credentials and signing the app uses for every upload
ticket. A wrong `S3_ACCESS_KEY`, a nonexistent bucket and an unreachable
endpoint come back as three distinguishable botocore exceptions (403, 404,
`EndpointConnectionError`), which is a five-second answer to a question that
otherwise surfaces as an opaque `SignatureDoesNotMatch` in a browser console
with no indication which of the three is wrong. The CORS preflight check only
runs when storage is managed — same-origin uploads through the bundled RustFS
need no CORS at all, so running it there would be testing something that
doesn't apply and can't fail. It sends the literal request a browser sends
before a presigned PUT (`OPTIONS` with `Origin`/`Access-Control-Request-*`)
against `S3_PUBLIC_ENDPOINT`, because a provider that doesn't recognise the
origin typically doesn't error — it just omits `Access-Control-Allow-Origin`,
which is invisible unless something goes looking for it.

**The CORS probe's own URL has to respect `S3_ADDRESSING_STYLE`, or it tests
the wrong URL and reports the wrong thing — found on a real deployment
immediately after adding addressing style, because the two were written in
different sessions and this one wasn't updated to match.** With `virtual`
(DigitalOcean Spaces), the bucket belongs in the *host*
(`bucket.region.digitaloceanspaces.com`), not appended to the path. A
path-style probe against a virtual-hosted-only endpoint gets a response with
no `Access-Control-*` headers regardless of what the bucket's actual CORS
rule says — which looks *exactly* like a missing CORS rule and isn't one, so
someone who correctly configured CORS sees this script insist they hadn't.
The fix mirrors the addressing logic by hand in bash (`bucket.host` vs
`host/bucket`) rather than asking boto3 for it, because there's no
unauthenticated-URL-only helper worth reaching for to save four lines.
Anywhere this codebase builds an object URL outside `storage/s3.py` itself is
a candidate for this exact bug; this was the one place it had happened.

And the old `/media/*` reachability probe is now gated on `LOCAL_STORAGE`:
that Caddy rule always points at `rustfs:9000`, which is dead code once
storage is managed — without the gate, a correctly-configured managed
deployment reported a false warning for a route nothing was ever supposed to
serve.

**Allowed Origins is not the whole CORS rule, and checking only that half was
a real gap the moment someone asked "should I also allow headers?".**
`Access-Control-Allow-Origin` alone is what the check verified; it never
looked at `Access-Control-Allow-Headers`. `Content-Type` is a CORS "simple"
header for exactly three values (`application/x-www-form-urlencoded`,
`multipart/form-data`, `text/plain`) — every real upload this product
handles (an image, a PDF, a voice note) has neither, so the browser
preflights it, and a bucket that allows the origin but not the header still
fails every one of those uploads with nothing CORS-shaped in the console to
point at. The check now fails specifically on that combination — origin
allowed, header not — rather than reporting success on half the requirement.
Confirmed against a throwaway local HTTP server standing in for three
provider responses (both headers present, origin only, neither), because
there was no live external bucket handy to prove the distinction against.

**HeadBucket passing doesn't mean uploads work — a real upload is the only
thing that proves a real upload works.** Confirmed twice on the same real
deployment: `HeadBucket` only exercises list/read-level permission, and a
bucket policy that grants that but not `PutObject` answers it 200 and then
refuses every real upload — the browser's actual failure mode. Worse,
`HeadBucket` in this script goes through `internal_client()`, but the browser
never touches that client at all; every real upload is signed by
`public_client()` against `S3_PUBLIC_ENDPOINT`, a different setting that can
be wrong in ways `HeadBucket` against the internal one would never surface.
So for managed storage only (gated on `LOCAL_STORAGE`, same reasoning as the
CORS check — this signs against `S3_PUBLIC_ENDPOINT` and PUTs to it from
inside the `api` container exactly like a browser would from the internet;
for the bundled RustFS, `S3_PUBLIC_ENDPOINT` defaults to `SITE_URL`, and
`http://localhost` from inside a container reaches the container itself, not
Caddy — a false failure that has nothing to do with storage) it does the real
three-step thing: `presigned_put()`, an actual `PUT` over the network via
`urllib` (no new dependency — `boto3` signs, it doesn't have to be what sends
the bytes), a `head_object()` read-back, then deletes what it wrote. This is
the **one check in the script that isn't read-only**, and it's the only way
to actually answer "do uploads work" rather than "does something upstream of
uploads look fine." A 403 here with a 200 on `HeadBucket` above is a specific,
actionable diagnosis (list-but-not-write policy) that neither check alone
would have named.

### Bringing your own Postgres or S3

`docker-compose.yml` is still the ONE file — decision 3 doesn't bend for this.
`postgres` and `rustfs` each carry a Compose **profile**
(`local-db`, `local-storage`), read from `COMPOSE_PROFILES` in `.env`, and
every other service reaches them through `DATABASE_URL` /
`SUPERTOKENS_DATABASE_URL` / `S3_*` — plain connection details, never a
hardcoded `postgres` or `rustfs` hostname. Dropping a profile is a `.env`
change, not a fork of the compose file, and `docker compose up -d` stays the
one correct command in every configuration.

Two Compose behaviours make this work, and both are non-obvious enough to
re-break if the file is edited casually:

- **`depends_on` needs `required: false` on the profiled dependency**, not
  just the profile itself. `api` (always on) naming `postgres` (sometimes
  absent) as a dependency is otherwise `invalid compose project` even when the
  profile that would start `postgres` is inactive — Compose refuses to
  generate the config at all, not just to wait for a container that isn't
  coming. `required: false` is what turns "wait for it" into "wait for it if
  it exists."
- **A required variable (`${VAR:?...}`) is checked for every service in the
  file, active profile or not.** `postgres`'s own `POSTGRES_PASSWORD` and
  `rustfs`'s own `RUSTFS_SECRET_KEY` therefore can't be `:?` — a managed
  deployment that never starts either container would still fail
  interpolation on a variable it has no reason to set. They're soft-defaulted
  instead; the vars that actually matter regardless of mode (`DATABASE_URL`,
  `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`) stay `:?`, because those
  are read by services that are always on.

**Two separate credential pairs for storage, on purpose.** `S3_ACCESS_KEY` /
`S3_SECRET_KEY` describe whatever storage the app is actually configured to
use; `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` are only the bundled
container's own init credentials. In the default local setup they're the same
value twice — `scripts/setup.sh` generates one secret and writes it under both
names — but a managed bucket only ever touches the first pair, and the second
sits there unused rather than becoming ambiguous about which box it describes.

**`scripts/setup.sh` stays non-interactive**, exactly as before — nothing
above changes what it writes for the plain default. `scripts/setup-interactive.sh`
is the new, separate entry point for a person at a terminal who already has a
connection string to type in; it computes the same variables by asking rather
than generating. Both are checked against `.env.example` for exact key parity
— `diagnose.sh`'s "your `.env` is missing variables a newer release expects"
check depends on that staying true.

**`diagnose.sh` reads `COMPOSE_PROFILES` before judging anything.** Container
checks, the secret-looks-like-the-example checks, and the Data section all
skip `postgres`/`rustfs`-shaped questions when that profile is off — a managed
database was never `.env`'s password to judge, and `docker compose exec
postgres` on a service that was never asked to exist isn't a health check,
it's a crash.

**A managed Postgres instance has to be version 18 or later**, confirmed the
hard way on a real deployment. `uuidv7()` is a Postgres 18 builtin — see
"UUIDv7 primary keys" below — and there's no polyfill for it. Against an older
instance the failure isn't at connection time: `migrate` connects fine, logs
its two boilerplate INFO lines, and then exits 1 the moment the first
`CREATE TABLE` tries to call a function that doesn't exist. That reads exactly
like a connection problem and isn't one. README's "Bring your own Postgres or
S3" says so now; `diagnose.sh` can't check a version it has no client to ask
for, so the `migrate exited $code` hard-failure — already there — is the
actual signal, and it points at `docker compose logs migrate`.

**`compose.override.yml` is committed, and that's the trap on a real
deployment.** It's what makes local dev a plain `git clone`, but Compose
auto-loads it whenever it's present — including on a server somebody reached
by cloning this same repo. Also confirmed the hard way: the symptom isn't the
"site dark, no reverse proxy" story decision 3 tells about the reference
project — Caddy is a base-file service and still comes up — it's the *Vite
dev server* refusing the request outright, `Blocked request. This host (…) is
not allowed`, because its dev-only host allowlist has never heard of a real
domain. Deleting the file, not adding the domain to `vite.config.ts`'s
`allowedHosts`, is the fix — the dev stack also publishes Postgres's own port
to the internet and turns on the RustFS/pgweb consoles, none of which belong
on a public box. `diagnose.sh` now checks for exactly this combination
(the file present, `SITE_URL` not localhost) and says so.

**DigitalOcean Spaces needed a real code change, not just a `.env` fix —
confirmed on a real deployment where the symptom was a plain "that file
didn't upload," nothing more specific.** `storage/s3.py` hardcoded
`addressing_style: "path"` unconditionally, because that's what makes
`/media/<key>` a literal, Caddy-forwardable path for the bundled RustFS. But
that reasoning is specific to same-origin storage behind Caddy — a managed
bucket is never reached through `/media/*` at all — and DigitalOcean's own
docs are explicit that path-style isn't supported for regular operations,
only virtual-hosted (`https://<space>.<region>.digitaloceanspaces.com`, bucket
in the host). `S3_ADDRESSING_STYLE` (default `path`, unchanged for everyone
else) is what lets a managed provider override it. The second, independent
DigitalOcean requirement — `S3_REGION` has to be the literal string
`us-east-1` regardless of where the Space actually is, because the real
region lives only in the endpoint hostname — is env-only and easy to get
backwards precisely because "region" reads like the field where your actual
region goes. `scripts/setup-interactive.sh` detects a `digitaloceanspaces.com`
endpoint and sets both correctly rather than asking; `diagnose.sh` checks both
independently of that, in case someone configured `.env` by hand.

## The front door

`views/Landing.tsx` is the **only screen a signed-out visitor can reach**, and
`Root` in `main.tsx` is what decides that. It sits in front of the whole app
route, so the pathname test is load-bearing: **only the bare `/` is public**.
Every deeper URL still falls through to `SessionAuth`, which is what carries
`redirectToPath` and lands somebody on the page they were actually following
after they sign in. Drop the test and every "please sign in" becomes a
marketing page with the original link thrown away.

Two things follow from it being outside the shell:

- **It fetches nothing.** No `/me`, no rail, no session-dependent copy — so it
  renders instantly and works with the API down.
- **It restates no colours**, same rule as the auth screens. Every value comes
  from the tokens, so it follows dark mode and a palette change on its own. A
  landing page with its own accent is a second scale, and status owns the only
  red and the only amber.

**Deliberately just a headline and the two ways in — no feature list, no
pitch, no self-hosting sales copy.** `BRAND.tagline` ("Just another take on
the to-do app.") is the whole page; it's doing self-aware comedy on purpose,
not undersizing a marketing effort. Someone who found a to-do app already
knows what a to-do app is, and a wall of feature cards before they've signed
up is exactly the kind of thing the tagline is joking about. If a future pass
adds sections back, keep the tagline honest about it.

**The sign-in/sign-up/reset screens carry the same header and footer.** They
are SuperTokens' own routes — `getSuperTokensRoutesForReactRouterDom` hands
back a flat list of `<Route>`s with their own absolute paths, so they can't be
nested under a layout route the way `orgs/:orgId/*` is under `Root`.
`AuthChrome` in `main.tsx` wraps the whole `<Routes>` tree instead and checks
the pathname against `AUTH_BASE_PATH`; everywhere else it's a no-op
passthrough, since the app shell already supplies its own chrome. `Header`,
`Footer` and `Wordmark` are exported from `views/Landing.tsx` for exactly this
reuse — a second copy would drift from the first the next time either
changes. `Wordmark` is a link to `/`, deliberately: without it `/auth` was a
dead end with no way back except the browser's own Back button, which doesn't
exist if it's the tab's first page.

**An unmatched URL needs a wildcard route, or the page is blank — not just
without content, `Root` itself never renders.** `<Route path="/" element={<Root />}>`
with children only matches a path its children actually cover; a URL none of
them declare doesn't match the parent either, so nothing in the tree renders
at all — no rail, no header, nothing to click, which is a worse failure than
a 404 page because there's no indication anything is even running. `views/NotFound.tsx`
is the last child under `Root`, on `path="*"`, and being the *last* child
matters no more than any other route here (React Router tries children in
order, and a wildcard placed earlier would swallow paths meant for routes
declared after it — this one just happens to be declared last because
everything above it is declared first). It renders inside the same `Root` →
`SessionAuth` → `App` chain as everything else, so signed out it asks for a
sign-in first (with `redirectToPath` carrying the bad URL, exactly like any
other deep link) and only signed in does it actually show "Nothing here" —
inside the shell, rail and header intact, because it's a 404 *inside* the
app, not instead of it.

## The in-app user manual

`views/Help.tsx`, at `/help`. Landing.tsx already answers "what is this" for
someone who hasn't signed up yet, deliberately with no feature list (see its
own section above); Help answers a different question — "what can I actually
do with this" — for someone who has, and who'd otherwise have to find each
feature by clicking around. Linked from the bottom of the rail, beside the
theme toggle and Log out rather than in the main navigation: **deliberately
unobtrusive**, the exact placement asked for, because it's a reference
screen you reach for on purpose, the identical reasoning the People roster's
own move off the dashboard already established for this codebase.

**One page, not a multi-page docs site.** Fifteen sections, a sticky anchor
table of contents down the left on `lg` and up (`<nav>` of plain `<a
href="#id">` links, no scroll-spy JS — a reader either arrives from the TOC
or scrolls, and both already work with nothing fancier than
`scroll-mt-4` on each `<section>`), content on the right. Each section's
heading carries the identical icon the rail uses for the nav item it
describes where one exists (Tasks the same glyph as the Tasks link, Time
tracking the same as Time), so the two visibly correspond — a small thing,
but it's what makes "which of these do I want" answerable at a glance
rather than by reading every heading.

**User-facing language throughout, not this file's own voice.** No
`services/access.py`, no "resolves to owner", no file paths — a reader here
is asking "how do I share a project," not "how is sharing implemented." Two
sections link to real screens (`/account`, for tokens and notification
channels) because those are personal, cross-organisation routes Help can
name directly; nothing here links to an organisation-scoped screen like
Tasks or Settings, because Help itself carries no organisation context to
build that URL from — those are described in words ("your organisation's
Settings screen, near the bottom of the rail") instead of guessed at.

**Finding this prompted a real fix, not just a new page.** Writing the
"your own assistant, and the API" section and wanting to point at
interactive API docs surfaced that they were never reachable outside
development. FastAPI's own defaults put `/docs`, `/redoc` and
`/openapi.json` at the bare root; Caddy proxies only `/api/*`, `/mcp*`,
`/health` and `/media/*`, and the API's own port is published in dev alone
(see "Running and testing" below) — so in any real self-hosted deployment,
a request to `/docs` fell through Caddy's catch-all to the SPA, which has
no route there either, and rendered "Nothing here" instead of Swagger UI.
`main.py::create_app` now passes `docs_url="/api/docs"`,
`redoc_url="/api/redoc"` and `openapi_url="/api/openapi.json"` to
`FastAPI(...)`, moving all three under the one prefix that's actually
proxied everywhere — the identical "single origin, no flag to remember"
reasoning behind decision 3 in this file's own opening section, just
reaching a corner FastAPI's own defaults hadn't.

`screenshots.spec.ts` photographs the page (`14b-help`, right after
Account) in both themes, alongside everything else it already covers.

**"Running this installation," the last section, is the one deliberate
exception to "user-facing language throughout."** It's operator content —
the exact Telegram bot setup steps (a token from @BotFather, both env vars,
restarting the stack, registering the webhook with `curl`) already in
README's own "Telegram — notifications, and creating tasks from chat — is
optional too" section — placed here too because a self-hoster hitting
"Telegram notifications aren't configured on this installation" while
signed into their own instance is faster served by a page already open
than by finding the README on disk. Explicitly labelled as skippable
("only relevant if you're the one who set this installation up") rather
than gated on a role, because Help carries no notion of "administers this
installation" at all — that's an operator role, not an organisation one,
and this codebase has no account attribute for it (see the "no policy
engine" decision at the top of this file) to gate on even if it wanted to.

## The auth screens

SuperTokens' pre-built UI ships its own look, and left alone it is the first
screen anyone sees telling them this is two products bolted together.
`lib/auth-theme.ts` restyles it — and **restates no colours**. Every rule
reaches for the same custom properties as the rest of the app, so the auth
screens follow a token change and dark mode without anyone remembering they
exist. A second palette there is a palette that drifts.

That works because **custom properties inherit through a shadow root**, and
SuperTokens renders inside one. The variables on `:root` are visible to rules
injected into the shadow DOM even though the markup is isolated.

Three things learned doing it, all pinned by `e2e/tests/theme.spec.ts`:

- **`applyStoredTheme()` runs before React mounts** (`main.tsx`). `useTheme`
  only runs inside the signed-in shell, so without it someone who works in
  dark mode signs out and gets a full-brightness page.
- **Their divider paints a background on a box with padding**, so `height: 1px`
  still renders about 7px. A `border-top` draws a hairline regardless of the
  box around it.
- **They layer an opacity on secondary text**, which lands under the contrast
  floor once the background is dark. `opacity: 1` alongside the colour.
- **`primaryText` — the body of every "it worked" screen across every
  recipe** ("a reset email has been sent", "your password has been updated",
  email verification, TOTP — grep `data-supertokens~="primaryText"` across
  the SDK and it is the same class everywhere — ships with no colour rule of
  its own. That is invisible, not merely low-contrast: it defaults to
  near-black text on what is, in dark mode, a near-black card. One rule
  (`color: var(--foreground)`) fixes every recipe at once, which is also why
  it was worth finding rather than patching just the reset-password screen
  that surfaced it.

The selectors are SuperTokens' own `data-supertokens` hooks — the documented
styling surface, but still someone else's markup. A test asserts the hooks
still exist, because an upgrade that renames one reverts the screen to stock
rather than breaking it, and that is exactly the regression nobody notices.
The button label is literally the string "SIGN UP"; that is their copy, not a
`text-transform`, and it is not worth overriding.

## Two-factor authentication

Read `services/mfa.py`. Optional per person, forceable per organisation —
and **hand-rolled**, not SuperTokens' own `totp`/`multifactorauth` recipes.
Both were tried first and both registered cleanly, but the first live call
to create a device answered:

```
SuperTokens core threw an error … status code: 402 … MFA feature is not
enabled. Please subscribe to a SuperTokens core license key to enable this
feature.
```

That's a licensing gate in the self-hosted core binary itself, confirmed
against a real core and against SuperTokens' own docs — not a config
mistake, and not something a self-hoster can route around. It conflicts
directly with this product's own bar (`docker compose up -d`, no paid
dependency, no backoffice), so the paid recipes were pulled out entirely
and TOTP was rebuilt on `pyotp` plus a **free** primitive the base `session`
recipe already provides: a custom session claim.

**One rule decides who needs a second factor**, in exactly one place —
`account_requires_mfa`. TOTP is required for an account if *either* they
already have a device (`mfa_totp_devices`, one per person — personal opt-in
is sticky, that's what "enabling 2FA" means) *or* they're an active member
of an organisation with `organisations.require_mfa` set. Union, not
override: turning an organisation's requirement off never revokes someone's
own enrollment, and enrolling personally is never a substitute for a
different organisation's requirement.

**Enforcement is a custom `BooleanClaim`, not the paid recipe's claim** —
`security/authn.py`'s `MfaSatisfiedClaim`. `BooleanClaim` is part of the
free, open-source `session` recipe (it's what "build your own MFA" looks
like in SuperTokens' own docs), and it gives the identical shape a paid
claim would: a value fetched into the access token payload, checked by a
validator on every `verify_session()` call. The validator is added
explicitly on the one shared `VerifiedSession` dependency
(`_add_mfa_validator`, `override_global_claim_validators=`) rather than
arriving for free the way a recipe's own claim would — there's no "default
global validator" registration hook to attach to for a claim that isn't a
recipe's own. That's the real security boundary; the frontend's `MfaGate`
is UX only, same as every other place this codebase draws that line.

**`default_max_age_in_sec=None` is deliberate.** With no max age, the claim
framework only refetches `_fetch_mfa_satisfied` when the access token
payload has no value yet — a brand-new session — never on a timer. The
requirement is decided **once, at first use per session**, and completing
TOTP or a backup code (`mark_mfa_satisfied`, calling `set_claim_value`
directly) sticks for that session's whole life. An organisation turning
`require_mfa` on reaches an already-open session at its *next* sign-in, not
mid-session — `scripts/e2e-mfa.sh`'s "not kicked mid-session" case pins
this on purpose, because it's the one behaviour most likely to read as a bug
report from someone who just flipped the toggle and expected it instant.

**No SuperTokens prebuilt UI is registered for this, on purpose.** Backup
codes aren't a concept the prebuilt TOTP screen knows about, and there's no
supported way to inject a "use a backup code instead" link into it. Both
SDKs expose the low-level primitives instead (`TOTP.createDevice` and
friends, on the paid recipe — unused here — but the same "build your own"
shape applies to a hand-rolled one): `components/mfa-enroll.tsx`'s
`TotpEnroll` (QR from a server-rendered `data:image/png;base64,…` URI, a
secret fallback, a code field, then the backup-codes reveal) is shared
between the Account screen's `TwoFactorCard` (turning 2FA on voluntarily)
and `components/mfa-gate.tsx`'s `MfaGate` (an organisation forcing it and
the account not enrolled yet) — one implementation of "scan a QR, confirm a
code," not two. `MfaGate` itself is rendered by `App.tsx` in place of the
whole shell whenever `GET /me` comes back with SuperTokens' own "invalid
claim" shape naming `st-mfa-ok` (`isMfaClaimError` checks the shape, not
just the status code, so an unrelated 403 doesn't get misread as "needs
2FA") — the identical top-level-gating shape the `ErrorBoundary` already
uses for "don't render a half-built app."

**Every `/me/mfa/*` route uses `MfaPendingSession`, not `CurrentUser`.** Not
just the challenge endpoints (verifying a code, redeeming a backup code —
both are *how* the claim gets satisfied, so the route that does it can't
itself require it) but plain enrollment too: turning 2FA on can itself be
what satisfies a freshly forced organisation's requirement, in the same
session, with no second sign-in. A session that already satisfies the claim
reaches these routes exactly the same way — skipping a check nobody fails
is a no-op for them.

**The secret is stored in the clear**, deliberately — see `models/mfa.py`'s
own comment. A TOTP secret can't be hashed the way a password or backup
code can (verifying a code requires computing one *from* the secret), and
it sits behind the identical trust boundary every other row in this
database already sits behind. Encrypting one column would need its own
key-management story — generation, a new required `.env` var, rotation —
for a bar this product doesn't hold anywhere else yet.

**Recovery, three layers, most to least self-service:**
1. **Backup codes** — ten single-use codes (`secrets.token_hex`, ~40 bits
   each), shown once at enrollment and on regeneration, hashed with
   `services.tokens.hash_token` — reused, not reimplemented, the same
   "plaintext exists once" rule access tokens already follow.
2. **Admin reset** — an org admin clears a member's device and codes from
   the People roster (`reset-mfa`, rank-checked the identical way
   `disable_member`/`remove_member` are, unlike the org-wide toggle which
   only needs admin rank with no target to rank-compare against). The same
   "an org admin can do anything" escape hatch offboarding already grants.
3. **`scripts/reset-mfa.sh <email>`** — an operator running
   `services.mfa.reset_totp` directly from a shell, for the one gap an
   admin can't reach: a lone owner locked out of their own account. Unlike
   `diagnose.sh`'s Storage checks, this needs no SuperTokens call at all —
   TOTP devices and backup codes are hand-rolled in this app's own tables,
   not held by SuperTokens' core — so it's pure database work.

**A bash gotcha that cost real time writing `scripts/e2e-mfa.sh`.** A
multi-key JSON literal built inline — `-d "{\"a\":\"$x\",\"b\":\"$y\"}"` —
and nested inside a `"$(...)"` capture (the `ok "label" "$(code … -d
"{...}")" "status"` shape every `e2e-*.sh` script uses) is silently torn in
two by bash: the comma inside `{...}` reads as a brace-expansion separator
once it's nested two quote-levels deep, turning one `curl` call into two
malformed ones — no error, no warning, just a request whose body is missing
half its fields. It reproduces even though the *exact same shape with one
key* (no comma, nothing to expand) is fine, which is what makes it so easy
to write once and then hit the moment a second field is added. The fix,
applied throughout `e2e-mfa.sh`: build the body into a variable first
(`BODY="{\"a\":\"$x\",\"b\":\"$y\"}"; … -d "$BODY"`) rather than ever
writing a literal `{…}` containing a comma inside a nested capture.

## Login history

Read `models/login_event.py` and `services/login_history.py`. Every
successful sign-in is recorded — IP, user agent, timestamp — with
**deliberately no UI reading it yet**. The data exists so a screen built
later starts with history already in it, rather than starting the clock
the day someone finally asks for one.

**Not foreign-keyed to `users`, on purpose.** The local `users` row is
created lazily on first authenticated request
(`services/users.get_or_create`) — on a brand-new signup, that hasn't
happened yet at the exact moment a session is created. Keying on
`supertokens_user_id` instead (already assigned by then, indexed, joinable
to `users.supertokens_user_id` whenever something reads this) sidesteps the
ordering problem rather than working around it.

**Hooked into `create_new_session`, not the emailpassword sign-in API.** A
session is created exactly once per successful sign-in, regardless of which
recipe did the authenticating — so this covers Google sign-in for free the
day that's added (see the "social login" reconnaissance elsewhere in this
file), instead of needing a second override the day it lands. `security/
authn.py`'s override calls the original implementation first and records
*after* — a failed sign-in never reaches this code at all, so there's
nothing to distinguish success from failure here; SuperTokens already did
that filtering by not calling `create_new_session` for a rejected password.

**Must never fail a sign-in**, the identical contract
`notifications.notify()` already has: a login event is a side effect of
something that already succeeded, so a database hiccup recording it must
not turn a working sign-in into a 500. `record()` catches broadly and logs
a warning rather than raising.

**The IP is read from `X-Forwarded-For`, not the socket peer.** Single
origin means Caddy fronts every request, so the raw connection's client is
always Caddy's own container — `get_request_from_user_context(user_context)`
(a SuperTokens SDK helper, not something built here) is what recovers the
underlying request from inside a `functions` override at all, and
`X-Forwarded-For` off *that* is what recovers the visitor behind it.

## Attachments

Read `services/attachments.py`. The bytes go **browser → storage directly**
and never pass through the API — a phone video must not occupy a worker for two
minutes — and that forces the three-step shape. (`app/mcp/server.py`'s
`attach_file` is the one deliberate exception, for a caller that isn't a
browser and has no route to the bucket of its own — see the MCP section.)

1. ticket (access checked, type validated, `pending` row, presigned PUT);
2. the browser PUTs to storage;
3. **confirm** — HEAD the object, enforce the size limit against the **real**
   size, flip to `ready`.

**Step 3 is the only point at which the API can inspect an upload.** A client
that declares "image/png" and uploads 60MB of something else is caught there
and nowhere else. `scripts/e2e-attachments.sh` does exactly that, through real
storage.

Things that will bite:

- **Content-Type is signed byte for byte.** The server normalises
  `audio/webm;codecs=opus` to `audio/webm`, signs *that*, and returns it for
  the client to echo. Sending the browser's own `file.type` back would fail
  with `SignatureDoesNotMatch`, which says nothing about codecs. This is the
  voice-note trap from PLAN.md §6, handled once for every file type.
- **`handle /media/*`, never `handle_path`.** The bucket is called `media` and
  addressing is path-style, so the object URL *is* `/media/<key>` and the path
  is covered by the signature. Stripping the prefix breaks every upload.
- **Two S3 endpoints.** Internal for our own calls, public for signing, because
  SigV4 covers the Host header. The public one defaults to `SITE_URL`, which is
  right whenever Caddy fronts `/media/*`.
- **A presigned URL is a bearer token until it expires.** Minted fresh at read
  time, never stored and never sent over the realtime channel.
- **`message_id` is nullable**: the attachment row exists before the comment.
  Binding is scoped to the conversation, the uploader, `message_id IS NULL` and
  `status = 'ready'` — each clause blocks a different way of borrowing someone
  else's upload.
- **The captured `XMLHttpRequest` in `lib/storage.ts`** is kept, but *not* for
  the reason the reference needed it. Single origin means uploads are
  same-origin, so the CORS-preflight failure it worked around cannot happen
  here. It stays so no interceptor mutates a signature-bound request, and for
  upload progress. It still breaks if a caller is behind `React.lazy`.

### One table, two anchors

`attachments` (renamed from `message_attachments` in `0009`) is anchored to
**a task or a conversation**, never both and never neither — a CHECK on
`num_nonnulls(task_id, conversation_id) = 1` says so, and a second CHECK stops
a `message_id` existing without a conversation.

Both live in one table because the task's Files panel shows both. A file
dropped into a reply is exactly as much "a file on this task" as one added
from the panel, and the question people ask is "where's the survey PDF", never
"was it attached or posted". `attachments_service.for_task()` is one statement
with an OR over the two anchors, so ordering stays the database's job.
Comment-sourced rows are filtered to `message_id IS NOT NULL`: something
staged and never sent is not on the task.

**Comment files can't be deleted from the panel.** The comment refers to them;
removing one from underneath would leave a message pointing at nothing. Delete
the comment instead. The UI omits the button rather than showing one that 403s.

**Both upload points take a drop** — the task's Files panel and the comment
composer, via `hooks/use-file-drop.ts`. Three things there are load-bearing:

- **`dragleave` fires when the pointer crosses onto a child**, so the hook
  counts depth (enter increments, leave decrements, zero means out). Without
  it the highlight strobes as you move across the panel.
- **`dragover` must `preventDefault()` on every event**, not just the first,
  or the browser refuses the drop and the drag just ends.
- **`main.tsx` cancels `dragover`/`drop` on the window.** Missing a drop
  target by twenty pixels is the normal case, and the browser's default for a
  dropped file is to *open* it — throwing away a half-written comment and
  everything else on the page.

Multiple files upload sequentially: there is one progress bar, and four
parallel uploads on a phone connection is four slow ones rather than one fast
one.

**Thumbnails are a worker job** (`tasks/thumbnails.py`, Pillow, 480px max
edge, EXIF transposed, alpha flattened onto white). `thumbnail_url` being
`None` is a real answer — the job may not have run yet, or it isn't an image —
and the UI falls back to the original. A worker that is down costs bandwidth,
not a broken image.

Two things that cost time here:

- **The worker needs its own S3 credentials.** They were on `api` and not on
  `worker`, so every thumbnail failed with `InvalidAccessKeyId` while the API
  looked perfectly healthy.
- **A task in `app/tasks/` that isn't imported by `app/tasks/__init__.py`
  silently doesn't exist.** The worker logs "task … is not found. Maybe you
  forgot to import it?" and nothing else happens. `tests/test_task_registry.py`
  now fails the build instead.

## Data export

Read `services/exports.py` and `models/export.py`. "Take your data" — a ZIP
per organisation or per project, one directory per task, its files inside.
Built in the worker (`tasks/exports.py`), the same reasoning `thumbnails.py`
already established: an organisation-wide export can mean hundreds of tasks
and their attachments, and building that inline would risk an HTTP timeout
and hold a request open for no reason when this container exists for
exactly this shape of work.

**Privacy: no branch that grants anybody else access, not even an admin —
the one rule that matters most here.** The zip's contents are the
*requester's own* `access.visible_tasks_stmt` result at build time, not
"everything in the organisation," so letting a different member — even an
org admin — download someone else's export would leak tasks that member
couldn't otherwise see. Every read in `services/exports.py` filters on
`requested_by_user_id == caller`, the identical absence-of-a-branch
discipline `services/notes.py` and `services/personal_notes.py` already
hold for their own private data. `scripts/e2e-exports.sh` proves this is
the one property worth testing hardest: an admin gets an empty list and a
404 on both status and download for a colleague's export.

**Autodelete after a confirmed download.** The server can't observe the
actual browser → storage transfer — that GET goes straight to S3, same as
every other download in this product (see Attachments) — so "confirmed"
means the one honest signal actually available: the person asked for the
file. `GET .../download` stamps `downloaded_at` the first time only (a
second click just re-mints the presigned URL without moving the clock, so
double-clicking Download can't postpone deletion), and a new scheduled
sweep, `sweep_expired_exports` (`:45` past the hour, next to
reminders/deadlines/the digest at `:05`/`:15`/`:25`), deletes the object and
flips `status` to `expired` once either that stamp is past a grace window
(`EXPORT_GRACE`, five minutes — long enough for a large zip on a slow
connection to finish) or, for one nobody ever downloads,
`created_at` is past a longer ceiling (`EXPORT_MAX_AGE`, seven days) — the
same "never claimed still shouldn't leak forever" reasoning applied to a
second, independent condition in the same claim. Re-requesting a download
on an `expired` row is `410 Gone`, not `404` — it existed and is gone on
purpose, a different fact from "never existed" (wrong owner) or "not ready
yet" (`409`).

**`services/exports.py::claim_expired` clears `storage_key` in a *second*,
separate statement from the one that claims the row — found writing it, not
guessed.** `RETURNING` reflects the row *after* an `UPDATE`, so a single
statement that both nulls `storage_key` and returns it hands back `NULL`
every time — exactly the key the caller needs to actually delete the S3
object. The claim itself (the part that has to be race-safe, the identical
`UPDATE … WHERE … RETURNING` shape `reminders.claim` already uses) is
entirely in the first statement; by the time the second one runs, only the
winner holds those ids, so it needs no claim of its own.

**Two new batched-by-many-task-ids functions, because this is the one
caller that would otherwise be N+1 across however many tasks are in
scope**, the same discipline every list endpoint in this codebase already
follows for a single page: `services/attachments.py::for_tasks` (mirrors
the existing `for_messages`'s batched-by-ids shape exactly) and
`services/conversations.py::for_tasks` (mirrors `list_messages`, minus the
tombstones — a removed comment already has its body cleared by `remove()`,
so there's nothing of the person's own words left to export, and it's left
out entirely rather than shown as a placeholder). `services/tags.py::for_tasks`
already existed and needed no counterpart. Checklists don't get one:
`checklists_service.for_task` stays a per-task loop in the builder, on
purpose — this is a background job with no request latency to protect, not
a live list endpoint, and the "one statement" discipline is specifically
about the requests a person is waiting on.

**The description in `task.md` is deliberately *not*
`richtext.to_plain_text()`.** That function collapses everything to one
line for a search snippet, which would turn a multi-paragraph description
into a wall of text here. `tasks/exports.py::_description_text` is a
second, small, export-only converter — block tags become line breaks, `<li>`
becomes a bullet, then the rest strips the same way — kept local to this
module specifically so the shared single-line contract other callers
(search) depend on stays untouched.

**Folder naming checks for *any* alphanumeric character before calling
`slugify`, not after.** A title of nothing but punctuation (`"!!!"`) has
nothing for `slugify` to keep, and its own fallback for that case is
`"org"` — the right word for a URL stem with no organisation name, the
wrong one for a task folder with no readable title. `_task_folder` decides
`"untitled"` itself rather than letting that fallback leak into a context
it wasn't written for. The first 8 characters of the task's own id are
appended regardless, so two tasks slugifying to the same stem still land in
different folders — and the identical short-id-prefix trick disambiguates
two attachments on the same task that happen to share a filename, which a
plain `filename` can't guarantee on its own.

**An org-wide export nests task folders one level under a project
folder** (or `no-project/` for a loose task); a project-scoped export skips
that level, since the scope is already the folder root. **A task-level
grant can reach further than its project's own** — the same gap
`effective_task_level` documents elsewhere — so the builder resolves every
project a *visible task* points at directly, not "projects this caller can
see": the task screen's own breadcrumb already established that a task's
project name is fair to show even without project-level access, and this
is the identical case.

## Voice notes

`lib/audio.ts` and `components/voice-note.tsx`. They ride the attachment
machinery — same three-step handshake, same upload function — rather than
having a path of their own.

- **`bareType()` is the trap.** `MediaRecorder` reports
  `audio/webm;codecs=opus`; the signature covers Content-Type byte for byte, so
  the parameter has to go. Both ends normalise, and a browser test asserts the
  `PUT` header has no `codecs` and that storage returned 200 — the second half
  is what actually proves the signature matched.
- **Tap to start, tap to send.** Not hold-to-record: holding is hostile on a
  trackpad and to anyone who can't sustain a press, and it makes a long note
  impossible. Cancel is its own button.
- **The send button IS the send** — a voice note uploads and posts in one
  action. A typed draft is deliberately left alone, because that's a separate
  message the person hasn't finished. There's a test for that.
- **`preferredMimeType()` asks rather than assumes.** Safari has no webm
  encoder and `new MediaRecorder(stream, {mimeType: "audio/webm"})` throws
  there outright.
- **The waveform is decoded from the real audio**, so it shows where the speech
  is. When a container can't be decoded it falls back to a plain progress bar
  rather than drawing an invented shape. Decoded on every load — storing peaks
  alongside the row is the upgrade if threads get long.
- **Always release the tracks.** Without `stream.getTracks().forEach(stop)` the
  browser's recording indicator stays on after cancelling or navigating away,
  which is both alarming and a real privacy problem.

Testable because Chromium has a fake capture device:
`--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`, set per
spec in `e2e/tests/voice-notes.spec.ts`.

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

**On a wide screen, Comments gets its own column between Details and the
sidebar — a fourth grid child, not a fifth breakpoint's worth of new
layout.** `TaskDetail.tsx`'s content grid was two items (a main column, a
sidebar) with an implicit single column below `lg`. Splitting Comments out
into its own middle column only at `2xl` meant splitting the main column
into three DOM children — Details-through-Files, Comments, then
History-and-PrivateNote — each carrying its own `col-start` per breakpoint,
so `lg` keeps the exact layout it always had (all three stacked in one
column) and only `2xl` pulls Comments into a real second column between
that stack and the sidebar's third.

**Every grid child needs an explicit `col-start`, and the two that must sit
flush with the top of their column need an explicit `row-start` too — CSS
Grid's own auto-placement will not put them there on its own, and the
failure is invisible unless you screenshot the exact breakpoint.** Found
exactly that way: at `2xl` the sidebar rendered in an empty-looking cell
with nothing in row 1 above it, while Details and Comments sat correctly at
the top. Sparse auto-placement (the default) tracks one cursor for the
whole grid, in DOM order, and never backtracks it. Details (child 1,
`col-start-1`) claims row 1. Comments (child 2) has an explicit column but
no row, so it auto-places — fine, since at `2xl` its column is free in row
1. History+PrivateNote (child 3, `col-start-1`, no row) wants column 1 too,
finds row 1 already taken by Details, and drops to row 2 — advancing the
cursor to row 2 with it. The sidebar (child 4) also has only a column, no
row, and now resumes its own search *from row 2 onward*, walking straight
past the still-empty row-1 cell in its own column that a naive reading of
"sparse" would expect it to fill. The fix is `row-start-1` on whichever
children must stay pinned to the top regardless of what a sibling did:
the sidebar unconditionally (`lg:row-start-1`, since its row is always 1
whether it's column 2 at `lg` or column 3 at `2xl`), and Comments only from
`2xl` on (`2xl:row-start-1` — at `lg` it must still auto-place into column
1's row 2, stacked under Details exactly as before). Once both axes are
explicit for an item, the placement algorithm seats it directly rather than
walking the cursor at all, so it can no longer be dragged along by an
unrelated sibling's overflow.

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

## Notification channels

Read `services/notification_channels.py`. Telegram and a generic webhook,
alongside email — configurable per notification kind, from `/account`.

**Email becomes a row in `notification_channels`, not a special case beside
it.** Every user gets one, auto-provisioned lazily the first time anything
needs to notify them (`get_or_create_email_channel`, the identical lazy
`get_or_create` shape `services/users.py` already uses for the local user
row) — not at signup, so existing accounts pick it up the moment they're
next notified rather than needing a backfill. `notify()` changed from
"always email" to "deliver to every channel with this `kind` enabled",
which is what makes adding Telegram and webhook *routing*, not two new
special cases bolted beside the old unconditional email send. A fresh
channel starts with every `NOTIFICATION_KINDS` value enabled — matching
today's "email always sends" default, so nobody who never opens the
settings screen notices anything changed.

**The webhook secret is stored in plaintext, deliberately — the one place
in this codebase a credential isn't hashed at rest, and that's a
considered exception, not an oversight.** A personal access token
(`services/tokens.py`) is a bearer credential the server only ever
*verifies*: hash it, and the server never needs the plaintext again. A
webhook signing secret is the opposite — a symmetric key the server has to
*use*, computing a fresh HMAC on every delivery, for the life of the
channel. There is no way to do that from a one-way hash. What makes this
an acceptable trade: the secret only ever signs nudges that carry no task
detail by design (the same "carries no detail" rule `services/
notifications.py`'s own docstring has always stated), it's scoped to one
channel and revocable independently of every other credential on the
account, and it is never sent back to the browser after creation — only a
preview (its own URL), the same "which one do I revoke" purpose
`PersonalAccessToken.prefix` already serves. Every delivery carries
`X-Ayeaye-Signature: sha256=...`, the same header shape GitHub and Stripe
already taught people to expect.

**Neither Telegram nor webhook gets the email job's per-notification
idempotency flag, and that's a scope trade, not an omission.**
`Notification.emailed` works because there's exactly one email channel per
person — one flag on the notification row is enough to say "this went."
Telegram and webhook are N channels per person, and a flag per
(notification, channel) pair was traded away: a webhook receiver is
expected to dedupe on the notification id in its own payload, the
identical at-least-once contract GitHub and Stripe already teach people to
expect, and a duplicate Telegram message on a worker retry is a minor
cosmetic cost, not a correctness one.

**Telegram linking is a two-step handshake through a pending channel row,
not a second table.** `POST /me/notification-channels/telegram/link-start`
deletes any existing Telegram channel for that person (linked or still
pending — a person has one Telegram account, and starting a fresh link is
how they'd re-point it at a different chat) and inserts a new one with
`verified_at IS NULL` and a one-time code in `config.link_code`. Tapping
`/start {code}` in the bot hits the new top-level `POST /api/telegram/
webhook` route — not organisation-scoped, not user-authenticated, because
Telegram has no session cookie and no idea what either concept is — which
resolves the code, sets `config.chat_id` and stamps `verified_at`. The
code expires after `LINK_CODE_TTL` (15 minutes); an expired or unknown
code is not an error, just nothing to do, and the route always 200s
regardless — Telegram retries a webhook call that doesn't, and there is
nothing here worth retrying.

**Two partial unique indexes, not a plain one, because webhook is the odd
one out.** `uq_notification_channels_user_email` and `_user_telegram` are
both `UNIQUE (user_id) WHERE kind = '...'` — at most one of each, the same
"a person has one inbox and one Telegram account" reasoning the linking
flow already relies on. Webhook carries no such index: several are
expected, one relay per destination. `get_or_create_email_channel`'s race
recovery — catch the `IntegrityError` from two concurrent `notify()` calls
provisioning email at once, then re-read what the winner inserted — is the
identical shape `tasks_service.grant()` already uses for its own
unique-grant race.

**`httpx` is now a direct dependency**, not just transitive via
supertokens-python — `services/telegram.py`'s Bot API calls and the
webhook delivery job both need a real HTTP client. `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_BOT_USERNAME` are both optional and empty by default, the
identical "optional infrastructure" contract `SMTP_HOST` already holds —
every function in `services/telegram.py` becomes a silent no-op with an
empty token, and `link-start` refuses with 422 rather than minting a code
for a bot that can't be reached, so the browser gets an honest reason
rather than a link nobody can ever open. Registering the webhook itself
(`setWebhook`, pointed at `{SITE_URL}/api/telegram/webhook`) is a one-time
operator step — see the README — because it needs `SITE_URL` to already
be a real HTTPS address Telegram's own servers can reach.

**`scripts/e2e-notification-channels.sh` proves the webhook path against a
real local HTTP listener** standing in for a receiver, the same "throwaway
local server standing in for a provider" precedent `diagnose.sh`'s own
CORS check already uses — and verifies the HMAC byte for byte, not just
"did a request arrive." Telegram's own Bot API isn't reachable from a dev
stack without a real bot token, so its linking logic is proved by calling
`services/notification_channels.py` directly rather than through the
router's `settings.telegram_bot_username` gate, alongside the HTTP-facing
parts that need no bot at all: the webhook route surviving a malformed
update, an irrelevant message, and a stale code without ever 500ing.

### Creating tasks from Telegram

Read `services/telegram_commands.py`. Four commands: `/start {code}` (the
linking handshake, unchanged), `/task <title>`, `/org <name>` and `/help`.
**A plain message creates nothing** — that was a deliberate call, not an
oversight: the ask was a `/task` command, not "every message is a task,"
because the second one is one accidental tap or stray reply away from a
task nobody meant to file.

**`/task`'s first line is the title, the rest is the description.**
`rest.partition("\n")`, title truncated to 300 (the column's own limit —
`tasks_service.create()` is called directly here, bypassing the `TaskCreate`
schema that would otherwise enforce it, so this module has to). Owner
defaults to the sender, exactly `tasks_service.create()`'s own "you own it
unless you say otherwise" rule — the identical shape `app/mcp/server.py`'s
own `create_task` tool already calls it with.

**Which organisation `/task` files into lives in `NotificationChannel.
config`, not a new table.** One more key, `default_organisation_id`,
alongside the `chat_id` a linked Telegram channel already carries — the
same "differs per kind, never queried on" reasoning the model's own
docstring already gives for `config`. `/org` is the *only* writer of it;
the Account screen shows it read-only ("/task creates tasks in {org
name}"), a deliberate design fork — organisation switching was asked to
happen inside Telegram, not from a second web picker duplicating the same
write.

**Membership is re-checked at `/task` time, not trusted from whenever
`/org` last ran.** Someone can be removed from their default organisation
between the two; `organisations_service.context_for` (the identical
"no access reads as 404" call every other organisation-scoped route
already makes) runs fresh on every `/task`, and its failure is a reply
asking to `/org` again, never a task silently filed into an organisation
the sender no longer belongs to.

**The single-organisation case never needs `/org` at all.** If `/task`
runs with no default set and the sender belongs to exactly one active
organisation, that one is used *and persisted* as the default — the
friction `/org` exists for only matters once there's an actual choice.
Zero organisations, or more than one with nothing chosen yet, both reply
pointing at `/org` with the real list of names.

**`/org`'s name matching is a pure function**, `match_organisation` — no
database, a real unit test (`tests/test_telegram_commands.py`), the same
"pure function over plain data" shape `services/tasks.py`'s own
notification rules already use. Exact (case-insensitive) match wins
outright even when it's also a substring of another choice — typing
"Acme" for an organisation literally named "Acme" must not get tangled up
with a second one named "Acme Corp." Only when there's no exact match does
a *unique* substring match get used; anything else (zero or several
candidates) is reported by name, never guessed at.

**A verified Telegram chat id is unique across every account, not just
within one — found live, not designed in from the start.** Re-linking the
same Telegram account to a *second* ayeaye account left two verified
`NotificationChannel` rows both claiming the same `chat_id`, and
`telegram_commands._channel_and_user`'s lookup by chat id had no way to
know which one governed — whichever the database happened to return
first, silently. `start_telegram_link` already deletes the *caller's own*
previous Telegram channel on re-link; `complete_telegram_link` now also
deletes any *other* account's channel already holding that exact chat id,
the identical "re-linking transfers the claim" rule, just extended across
accounts instead of within one — a real Telegram chat belongs to one
Telegram account, which can only sensibly be linked to one ayeaye account
at a time.

**No `update_id` de-duplication, on purpose.** Telegram retries a webhook
call that doesn't 200; this one (almost) always does, even on an internal
error (`handle_update`'s own errors are caught by the router, which still
replies `{"ok": true}`), so a retry double-filing a task is already rare.
Tracking processed update ids would be real infrastructure — a table, or
a Redis key — for a genuinely rare edge case on what is, at bottom, a
personal capture tool. The identical trade-off this same section already
makes for Telegram and webhook not getting the email job's
per-notification idempotency flag.

`scripts/e2e-notification-channels.sh` proves the whole loop against the
real HTTP route once a channel is linked at the service layer: `/task`
refusing with no default across two organisations, `/org` picking one,
`/task` filing into it, switching with a second `/org`, an unknown `/org`
query leaving the default untouched, and a 400-character title landing at
exactly 300.

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
already clears. The task screen's picker (`views/TaskDetail.tsx`) is an
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

## Search — why Postgres, and when to stop

Read the `services/search.py` docstring before proposing a search engine.

**Fuzzy matching must be written as an operator.** `word_similarity(q, col) >
0.3` and `col %> q` are the same test to a reader and completely different to
the planner: only the operator can be served by the GIN trigram index. Two
details un-index it again if you get them wrong — the **column goes on the
left**, and there must be **no `coalesce()`** around it. Measured on 10,000
tasks: search went from ~450ms to ~80ms. `%>` reads its threshold from
`pg_trgm.word_similarity_threshold`, which `apply_threshold()` sets per
transaction; without that call the default 0.6 applies and typo tolerance
quietly halves.

**The deciding factor is permissions, not scale.** What a person may see is
computed across five tables. Handing that to Typesense/Meilisearch/Elastic
means either denormalising an ACL onto every document — where one team-
membership change re-indexes thousands of docs and any lag is a *leak*, not a
stale cache — or over-fetching and filtering afterwards, which throws away the
speed you bought it for and breaks counts and pagination.

In Postgres the visibility expression ANDs into the same statement as the text
match. There is no moment at which a row the caller can't see exists in the
result set. Revoking access removes it from search on the next keystroke, with
nothing to reindex.

`pg_trgm` (migration 0005) supplies both halves: GIN indexes that make
`ILIKE '%…%'` an index lookup rather than a scan, and `word_similarity()` for
typo tolerance. Measured at **~20 ms** on a small database and **~80 ms across 10,000 tasks**,
end to end including HTTP.

**Revisit when** — genuinely, not never: cross-organisation search (no per-org
filter to prune with), ranking over message bodies past ~1M documents, or
wanting synonyms/highlighting/learn-to-rank. The shape to reach for then is an
engine fed by a change stream with the ACL check *still* in Postgres on the
returned ids: the engine ranks, the database authorises.

Adding a searchable kind is one more `*_stmt` in that module returning the same
shape. Messages and comments (Phase 6) inherit visibility from the task or
project they hang off, so it's the same `level > NO_ACCESS` test.

**The new-task dialog's duplicate check is `tasks_stmt` called directly, not
`search()`.** `GET /tasks/similar` reuses the exact same access-scoped
fuzzy-title statement the search palette uses, skipping the two other kinds
`search()` also checks — a duplicate task isn't a duplicate project or a
duplicate note, so there's no reason to fetch either. `snippet()` (formerly
private, promoted the same way `recurrence.advance` was — a second real
caller is what that promotion is for) formats the match the identical way a
palette result reads. **A failed check must never block creating the task**
— it's a courtesy, not a gate the feature depends on — so the frontend
treats a network error identically to "nothing similar found" and lets the
task through. The confirmation itself is click-Create-twice, not a second
dialog: the first press that finds something shows what it found and stops:
the *second* press — button now reading "Create anyway" — is the
confirmation, the same "say it again to mean it" shape as the delete
dialogs elsewhere, minus the retyping, because a title is not a name someone
picked on purpose the way a project's is.

On the client, `components/search-palette.tsx`. Three things there are load-
bearing and easy to delete by accident:

- **Requests are aborted *and* sequence-checked.** Eight keystrokes are eight
  requests that can return in any order; without the monotonic guard a slow
  answer for "ant" overwrites the fast one for "antifoul". Invisible on
  localhost, constant on a real connection. There is a browser test that
  injects latency to prove it.
- **Old results stay while new ones load.** Clearing on every keystroke makes
  the panel strobe.
- **"Nothing matches" only after a settled search**, never mid-flight.

## Organisations and membership

Read the `services/organisations.py` docstring before touching any of this. The
four rules there — creator owns it, you only grant what you hold, you can't act
on someone above you, the last owner can't leave — are tested exhaustively in
`tests/test_organisation_rules.py` as **pure functions with no database**. That
file is the template for the Phase 3 access matrix.

Two structural choices worth not undoing:

**Membership and invitations are one table.** `organisation_members` holds both;
the difference is `status`. Binding an invitation at signup is then one UPDATE
rather than a copy between tables with a window in the middle. The model
docstring has the four legal row shapes and the CHECK constraints that allow
exactly those — `invited`, `active`, and now `disabled`.

**Disabling a member reuses `context_for`'s own gate rather than adding a
second check.** `context_for` only ever resolves an `active` membership; a
`disabled` row just stops matching it, so every organisation-scoped route
404s for that person from the next request on, with nothing else anywhere
in the codebase that needs to know the status exists. `disable_member`/
`enable_member` (`services/organisations.py`) reuse rules 2 through 4
exactly as written — rank, and the last-owner check — rather than
introducing a fifth rule. **Deliberately not `remove_member` in miniature**:
removal reassigns every project and task the person owns, because the row
is about to stop existing and a thing with no owner is a thing nobody can
administer. Disabling is a pause, not a departure — their work stays
exactly where it was, for the admin who re-enables them to find again.

**No separate self-block, on purpose.** `remove_member` already lets you act
on yourself (that's how leaving works), protected only by the last-owner
rule. Disabling copies that shape rather than inventing a "you can't disable
yourself" rule that doesn't exist anywhere else in this module: a plain
admin can disable their own access same as they could leave outright, and a
lone owner disabling themselves is caught by the ordinary last-owner check,
not a bespoke one.

**An invitation never joins anyone automatically.** Signing up with an invited
address *attaches* the invitation (`user_id` set, still `invited`) and it
appears in `GET /me/invites` for the person to accept. The reference project
bound shares outright and then listed the consequence in its own known-problems
section: anyone who knows your email can drop something into your account. One
click closes that.

The exception is the invite link, where **opening it is the consent** and it
activates immediately. The trade that comes with it is written out in the
`services/invites.py` docstring: the token is the authority, so whoever holds
it joins regardless of the address it was sent to. Mitigated by being
single-use, revocable, and 256 bits — and reversible in one condition if it
ever stops being an acceptable trade.

Two rules that only exist in SQL, so they're easy to lose in a migration:

- **`uq_org_members_org_user`** is partial (`WHERE user_id IS NOT NULL`).
  Without the partial clause, several invitations to people who don't have
  accounts yet would collide on NULL.
- **`uq_org_members_org_invited_email`** is scoped to `status = 'invited'`, so
  re-inviting someone who left doesn't collide with their historical row. This
  is also why removal is a hard DELETE rather than a `revoked` status.

`bind_pending_for_user` has a `NOT EXISTS` guard that is load-bearing: without
it, someone already in an organisation who also has an outstanding invitation
to it violates the unique index, and it fails **their first authenticated
request** with a 500 — the single worst place for it.

## Product decisions taken outside PLAN.md

These came from the product owner after the plan was written and supersede it
where they differ.

### Projects are private by default

**Whoever creates a project owns it.** The owner controls its access and can do
anything to it. **By default nobody else can see it** — not the rest of the
organisation. Access is only ever explicit: a named user or a named team, with
a level, listed in the UI so "who can see this" is always answerable by looking
rather than by reasoning about inheritance.

This tightens PLAN.md §4 rather than contradicting it: access still flows down
and most-permissive still wins, but the starting set is empty. Org `owner` and
`admin` remain able to see everything in the organisation — that is what stops
"the only person who could see it has left".

### Task status and open/closed are two different fields

Status is a fixed set, widened from PLAN.md §9 with a landing spot for new work:

```
TODO  →  IN PROGRESS  →  REVIEW  →  (closed)
           ↕
  ON HOLD / BLOCKER
```

A new task is **TODO**. `ON HOLD` then means "deliberately parked", which is a
real signal — as the default it would have been the most common status in the
system and meant nothing.

**Open/closed is a separate boolean, not a status**, and only the task owner
sets it. A task can be closed from any status; closing is not a transition to
`DONE`. Keeping them apart is what lets "closed while still BLOCKER" be
expressible, which is what actually happens when work is abandoned.

The design tokens define exactly one red (`--status-blocker`) and one amber
(`--status-review`), so red always means "this needs you".

### Task owner

The creator is the owner. The owner can change the owner; so can an
organisation admin. **An org admin can do anything** — that is the escape hatch
that keeps the product operable, and it is a membership role, not a Casbin
policy or an account attribute.

### Comments are the conversation thread

Trello-style comments under a task are not a second system: they are the
`conversations`/`messages` machinery copied from the reference, anchored to a
task instead of an accepted offer. Attachments, voice notes, realtime delivery
and the unread badge come with it. Do not add a `task_comments` table.

## Traps carried forward from the reference

Not yet reachable in this codebase, but they cost a day each if rediscovered.
Read these before starting Phase 6.

- **Capture `window.XMLHttpRequest` at module load, before `SuperTokens.init()`
  runs.** SuperTokens patches both `fetch` and `XMLHttpRequest` and injects
  `st-auth-mode` into requests it doesn't own. RustFS answers
  `Allow-Headers: *` alongside `Allow-Credentials: true`, which browsers refuse
  to treat as a wildcard, and RustFS has no way to configure allowed headers —
  so the fix has to be client-side. Copy `packages/ui/src/lib/storage.ts` with
  its comment intact. It breaks if a caller is ever behind `React.lazy`.
- **Voice notes must send the bare content type** (`audio/webm`, never
  `audio/webm;codecs=opus`) because the presigned signature covers Content-Type
  byte for byte. Chrome/Firefox produce webm, Safari mp4. Copy the unit test.
- **Two S3 endpoints.** `S3_ENDPOINT` is what the API calls; presigned URLs are
  signed against `S3_PUBLIC_ENDPOINT`, because SigV4 covers the Host header.
  The bucket is called `media` so the object URL is literally `/media/<key>`
  and Caddy can pass it through with **no** prefix stripping — stripping would
  invalidate every signature.
- **`redis` is pinned `<6`**: taskiq-redis 1.2.x's blocking listen loop crashes
  on redis-py ≥6.
- **Base UI, not Radix.** Triggers take `render={<Button />}`, not `asChild`;
  `Select` needs an `items` prop. `Button render={<a/>} nativeButton={false}`
  puts `role="button"` on the anchor, so a test's `getByRole("link")` won't
  find it.

## Gotchas in what exists now

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
- **The notification inbox's body span had no `whitespace-pre-wrap`, and it
  took the daily digest to notice.** Every notification before it was
  effectively one line, so the missing wrap was invisible; a digest body with
  real line breaks (`Planned for today:\n- …\n\nDone yesterday:\n- …`)
  rendered as one run-on sentence. Same fix as a comment or an announcement
  body — `views/Notifications.tsx`'s body `<span>` needed the class everyone
  else already has.
- **Each inbox row got its own Mark-as-read and Delete buttons, not just
  the page-level "Mark all read."** `DELETE /notifications/{id}` and
  `POST /notifications/{id}/read` (already existed) sit beside each other
  in `services/notifications.py` with the identical "not found is fine"
  shape — a foreign or already-gone id 204s rather than 404ing, since
  DELETE is supposed to be idempotent and there's nothing here worth a
  second person ever seeing (no org scoping, no access check beyond
  `user_id == caller`). The row itself couldn't stay a `<button>` once it
  needed to contain two more buttons — nested interactive elements are
  invalid HTML — so it's `role="button"` on a `<div>` with `tabIndex`/
  `onKeyDown`, the identical shape the notepad's own card already
  documents here, and for the identical reason: a Playwright role query for
  the inner button matches the outer row too, since its computed
  accessible name concatenates the row's own text with the nested button's
  `aria-label`. Scoped to the real `<button>` tag instead of a role query
  when this needed testing.
- **`.env` beats a `${VAR:-default}` in the override.** `:-` only applies when
  the variable is *unset*, and `.env` is production-shaped. That is why
  `compose.override.yml` pins `SMTP_HOST: mailpit` / `SMTP_PORT: 1025`
  literally — with the indirection, dev inherited the production port 587 and
  every message failed to connect. Anything dev must force, force literally.
- **A new frontend dependency needs the node_modules *volume* recreated, not
  just a rebuild.** `compose.override.yml` shadows `/app/node_modules` with a
  named volume so the container's Linux-native install survives the bind
  mount — and Docker only seeds a named volume when it is empty. Rebuilding
  the image changes nothing; Vite then fails with "Failed to resolve import"
  for a package that is plainly in `package.json`.
  `docker volume rm ayeayecaptain_web_node_modules` and bring it up again.
  The API has no equivalent: its venv lives in the image, so a rebuild is
  enough.
- **Dev images carry their own tags** (`ayeayecaptain-web-dev`, `-api-dev`, …).
  Base and override build *different Dockerfiles*, and `docker compose up -d`
  reuses an existing image rather than rebuilding — so with one shared tag, a
  local production build followed by a dev `up` starts nginx where Caddy
  expects Vite. HTTP 502, every container healthy. Any service that swaps its
  Dockerfile in the override needs an `image:` line too.
- **`init.sql` runs only on an empty data directory.** Change it after the
  first boot and it is silently skipped; `docker compose down -v` first.
- **Backups must be `pg_dumpall`.** SuperTokens keeps identity in its own
  database on the same server; a `pg_dump` of the app database restores every
  task and no way to log in.
- **`GET /me` is not just a fetch.** It creates the local user row on first
  sight, and from Phase 1 it binds pending invites. The shell blocks on it
  before rendering anything, or children fire requests against a user that
  doesn't exist yet.
- **New taskiq handler modules must be imported in `tasks/__init__.py`** or the
  worker never registers them, with no error anywhere to say why.
- **`useMatch(a) ?? useMatch(b)` is a hook-order bug.** `??` short-circuits, so
  the second hook is skipped on renders where the first matches and React
  counts hooks by position. Call both, then choose. (`App.tsx` resolves the
  current organisation this way.)
- **Slugs are global and never follow a rename.** They're in URLs people have
  bookmarked, so renaming changes the label only. It also means a test that
  asserts a literal slug will drift as the database accumulates rows — see the
  per-run name in `scripts/e2e-organisations.sh`.
- **`noUnusedLocals` is on**, and shadcn sometimes generates an unused `React`
  import. One-line fix when it happens; worth keeping the check.
- **The whole app is inside an `ErrorBoundary`, and it earned its place.** A
  render error unmounts the *entire* React tree — not the component, not the
  screen — leaving a white page with no rail and nothing to click. That is
  what "the site goes to localhost and shows nothing" means when somebody
  reports it. `/__crash` is a dev-only route that throws so the boundary can
  be tested rather than assumed; `import.meta.env.DEV` is a compile-time
  constant, so it and its component vanish from a production build.
- **Base UI's `DropdownMenuLabel` must be inside a `DropdownMenuGroup`.** It
  reads a context only `Menu.Group` provides and *throws* on open otherwise.
  The organisation switcher had it as a sibling, so the first click anybody
  ever gave it blanked the product — through a hundred green browser tests,
  none of which had opened a menu.
- **The breadcrumb separator is a sibling of the item, not a child.** Both
  render `<li>`, and nesting them is invalid HTML that React logs on every
  screen with a breadcrumb.
- **`EntityPicker`'s list is a `Popover.Portal`, not a plain `absolute` div —
  and that isn't a style choice, it's the fix for a real bug.** The original
  hand-rolled version positioned its list `absolute` inside the field's own
  wrapper, which every `Card` clips: `Card`'s base classes carry
  `overflow-hidden` unconditionally (for rounding cover images to its
  corners), so any picker whose list would extend past its card's own bottom
  edge — Priority and Project on the task screen, reliably, because they
  aren't the first field in their card — had that list silently cut off.
  Status and Owner, the first field in each of their cards, mostly didn't,
  which is exactly the kind of intermittent, position-dependent symptom that
  reads as "sometimes" until someone maps it to card position. Portaling to
  `document.body` escapes that ancestor chain entirely, and
  `Popover.Positioner` is what supplies `--anchor-width` / `--available-height`
  (the same primitives `DropdownMenuContent` already uses) — for free, that
  also fixes the picker running off the bottom of the viewport on a short
  screen, which the old version never handled either.
- **Base UI's own dismissal replaced two hand-rolled `document` listeners,
  and correctly, not just more concisely.** The picker used to bind its own
  `mousedown` (click-away) and capture-phase `keydown` (Escape, stopped
  before it could also close an enclosing dialog) listeners directly on
  `document`. Once the list is portaled, that click-away check breaks in a
  new way: a click *inside* the now-elsewhere-in-the-DOM list reads as
  "outside" the field's own wrapper and would close the picker before the
  click's own handler ever registered the choice. `Popover`'s built-in
  dismissal (`useDismiss`, floating-ui's nested-floating-tree logic) already
  solves both — outside-click detection that correctly excludes its own
  portaled content, and Escape that closes only the innermost floating
  layer — which is the same "innermost thing closes first" behavior the
  hand-rolled capture-phase trick existed to fabricate. Confirmed, not
  assumed: `e2e/tests/task-ux.spec.ts`'s "Escape closes the list, not the
  dialog behind it" still passes unchanged.
- **A native `<input type="date">`'s calendar glyph is browser-drawn and
  ignores every design token.** It doesn't take `color`, doesn't take
  `fill`, and is always near-black — invisible against a dark input, on
  every `type="date"` field in the product (task due date, estimate start,
  reminders, out-of-office). `filter: invert(1)` on
  `::-webkit-calendar-picker-indicator`, scoped to `.dark`, is the only
  lever Chromium/Safari expose for it — one rule in `index.css`'s base
  layer fixes every instance at once rather than each screen needing its
  own patch. Firefox draws this control differently and isn't a target
  here; the product's own e2e suite runs Chromium.

## Running and testing

```bash
./scripts/setup.sh && docker compose up -d        # http://localhost
./scripts/diagnose.sh                             # when something is wrong
docker compose logs -f api
```

Mailpit (dev only): http://localhost:8025. API docs: `SITE_URL/api/docs` —
under `/api` rather than FastAPI's own default of the bare root, so it works
identically through Caddy in dev and in production; the bare root would have
worked only while the API's own port happens to be published (dev only) and
been a dead end on every real deployment. `docs_url`/`redoc_url`/
`openapi_url` are set explicitly in `main.py::create_app`.

```bash
cd apps/api && uv run pytest && uv run ruff check src tests
cd apps/web && pnpm typecheck
./scripts/e2e-organisations.sh          # needs the stack up
./scripts/e2e-projects.sh               # the access model, against real SQL
./scripts/e2e-tasks.sh                  # workflow, task access, the inbox
./scripts/e2e-search.sh                 # fuzziness, ranking, and permissions
./scripts/e2e-time.sh                   # timers, corrections, rollups
./scripts/e2e-comments.sh               # threads, debouncing, the socket
./scripts/e2e-attachments.sh            # the upload handshake, against real storage
./scripts/e2e-task-files.sh             # priority, task files, thumbnails, moving a task
./scripts/e2e-hidden.sh                 # the one place access is subtracted
./scripts/e2e-tags.sh                   # the vocabulary, and "off the board"
./scripts/e2e-checklists.sh             # more than one list, write-gated, read-only sees but can't touch
./scripts/e2e-sheets.sh                 # a cell's existence IS the check, idempotent, who/when recorded
./scripts/e2e-notes.sh                  # private notes: nobody else, ever
./scripts/e2e-notepad.sh                # the notepad: same rule, a list this time, org-scoped
./scripts/e2e-reminders.sh              # the sweep, run twice, sending once
./scripts/e2e-dashboard.sh              # passwords, out of office, announcements
./scripts/e2e-mcp.sh                    # access tokens, and MCP acting as a person
./scripts/e2e-planner.sh                # the pool, the buckets, and the admin override
./scripts/e2e-recurring-tasks.sh        # the generation sweep, run twice, sending once
./scripts/e2e-mfa.sh                    # TOTP, backup codes, the org toggle, not-instant-on-purpose
./scripts/e2e-exports.sh                # yours only not even an admin's, build, download, autodelete
./scripts/e2e-task-sharing.sh           # sharing one task, never the project it's filed in
./scripts/e2e-dependencies.sh           # the DAG stays a DAG, informational, never enforced
./scripts/e2e-notification-channels.sh  # email/Telegram/webhook routing, a signed delivery, /task and /org
./scripts/e2e-browser.sh                # real Chromium; also takes screenshots
```

The unit suites are infra-free by design and run in seconds. `tests/test_access_matrix.py` must stay that way —
it is the test that earns the most and it needs no database.

The end-to-end scripts cover what unit tests structurally cannot: the partial
unique indexes, the invite bind, and the 404-not-403 convention, all of which
live in SQL and HTTP rather than in Python. They create real accounts against
a dev stack and leave them behind.

**The browser suite (`e2e/`, Playwright) covers what the HTTP suites can't:
what a second person actually sees.** The API returning 404 and the screen
rendering an absent project are different claims, and only the second is what a
user experiences. It drives two real browser contexts with their own cookie
jars, and every one of the UI bugs found so far was invisible to the other
layers — copy that contradicted the access model, a stale "arrives in the next
phase" card, a breadcrumb with a missing separator.

`tests/screenshots.spec.ts` photographs every screen in both themes into
`e2e/artifacts/shots/`. That is how the UI gets reviewed when nobody is sitting
in front of it. Run it after any visual change and look at the output.

Playwright lives in its **own top-level package**, not in `apps/web`. The
production image runs `pnpm install --frozen-lockfile`, which installs
devDependencies — putting it in the frontend would ship browser tooling in the
deployed bundle.

Writing browser tests here, three things bite every time:

- **`getByLabel` matches on substring**, so "Invitation link" also matches a
  "Copy invitation link" button. Prefer `getByRole("textbox", { name })`.
- **Scope to the dialog.** A modal's "Role" or "Project" select collides with
  the ones on the page behind it.
- **The copy uses typographic apostrophes** (`&rsquo;`). An ASCII `'` in an
  assertion never matches; match around it.
- **One file now appears twice on a task** — in the Files panel and in the
  comment it was posted to. Both cards are named regions, so scope with
  `getByRole("region", { name: "Files" | "Comments" })` rather than reaching
  for `.first()`, which picks whichever happens to be earlier in the DOM.
- **A toast title and a history line often say the same thing.** "Moved" is
  both a toast and part of "… moved it to another project". Use
  `getByRole("heading", { name, exact: true })` for the toast.
- **`PriorityGlyph` is labelled "Priority: Normal"**, which a substring match
  on "Priority" also hits. `{ exact: true }` on the control's name.
- **`CardTitle` renders a `div`, not a heading.** `getByRole("heading")` finds
  toast titles (real `h2`s) and nothing else; use `getByText` for card titles.
- **Wait for the effect, not the click.** Navigating straight after an action
  can outrun its POST — the next screen then shows the old data and the failure
  looks like a logic bug. Assert on the thing the action produced first.

```bash
# after a model change
docker compose exec api uv run alembic revision --autogenerate -m "what changed"
```

Migrations are authored in dev and committed; production applies whatever is in
the repo, via the one-shot `migrate` service. A self-hoster is never asked to
run alembic.

## Naming

`ayeayecaptain` is user-visible in exactly three places, so a rename is a
three-file change:

| What | Where |
|---|---|
| Anything rendered by React | `apps/web/src/lib/brand.ts` → `BRAND.name` |
| Email subjects, `From:`, OpenAPI title, SuperTokens app name | `brand_name` in `apps/api/src/app/core/config.py` |
| The browser tab | `apps/web/index.html` `<title>` |

Storage keys are deliberately brand-free (`ui-theme`, `view-tasks`,
`view-projects`): a key with the product name in it silently resets
everyone's saved preferences the day the name changes.
