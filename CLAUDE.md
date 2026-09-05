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

Verified by 303 infra-free unit tests, 555 end-to-end checks over HTTP
(`./scripts/e2e-*.sh`) and 130 browser tests in a real Chromium
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
    │       │                #   working_hours (a weekly grid, informational),
    │       │                #   spark (quick capture, cross-organisation),
    │       │                #   token (personal access tokens),
    │       │                #   oauth (clients, grants, codes, tokens —
    │       │                #     Dynamic Client Registration for MCP),
    │       │                #   knowledge_base (book, book_member, article,
    │       │                #     article_revision — a book's access model
    │       │                #     is a project's, unchanged),
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
    │       │                #   reminders.py presence.py working_hours.py sparks.py
    │       │                #   tokens.py — personal access tokens
    │       │                #   oauth.py — DCR, PKCE, rotating refresh tokens
    │       │                #   books.py — near-mechanical copy of projects.py
    │       │                #   articles.py — privacy, editing sessions, revisions
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

**The board can also group by who's action-required, and that column is
nullable where status and priority never are.** `?group=action_required`
partitions on `Task.action_required_user_id` directly — Postgres treats
`NULL` as one ordinary partition value for a window function, so every task
asking nothing of anyone lands in a real column together, not dropped. The
router turns that partition's key into the JSON-safe string `"none"` (a
UUID string can never collide with the four letters "none"), and the
frontend renders it as a plain "Nobody" heading, sorted last — named
columns sort by display name, the identical convention people and projects
sort by elsewhere in this product, read off each column's own first task
since a column only exists with at least one. Status and priority stay
driven by their fixed enum (`TASK_STATUSES`/`TASK_PRIORITIES`) so an empty
column stays on screen; action-required has no such enum — the columns
that exist are exactly the people (plus "Nobody") the server actually
found, because there is no fixed roster of "everyone who might ever be
action-required" worth hardcoding. Each card's own action-required badge
(`TaskMeta`'s `hideActionRequired`) is suppressed in this one arrangement
for the same reason `StatusBadge` is suppressed when grouped by status —
the column already says it.

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

**Markdown is a second way in, not a second storage shape.** `richtext.py`'s
`from_markdown()` converts markdown to HTML and hands it back — it does not
sanitise, because markdown is just another way to *arrive* at HTML, not a
second trust boundary; every caller still runs the result through
`sanitise()` exactly as it would for hand-typed HTML. This exists because
the browser editor was never the only writer: a curl script or an MCP client
would rather send `**bold**` than build `<strong>` tags, and before this,
that text rendered completely literally — asterisks and all — via the
plain-text fallback below. Two things about the conversion are specific to
this product's own allow-list, not markdown in general:

- **A markdown `#` is promoted to `##`, and anything past `###` folds down
  to `###`.** The editor's own toolbar only ever produces `h2`/`h3`
  (`heading: { levels: [2, 3] }`), and `sanitise()` would otherwise silently
  unwrap `h1` or `h4`–`h6` into plain text — a heading disappearing is a
  worse outcome than one clamped to the size this product actually has.
- **An image reference (`![alt](url)`) renders as nothing.** The "image is
  an attachment, not a URL" rule above doesn't bend for markdown either —
  there's no way to put a `data-attachment-id` on a markdown image, so
  `sanitise()`'s orphan-`<img>` strip removes it, same as a hand-typed
  `<img src="...">` in the HTML editor. The picture has to be attached
  separately (`attach_file`/`attach_article_file` over MCP, or the Files
  panel).

Reached via an explicit `description_format`/`body_format: "html" |
"markdown"` field on the REST write endpoints (`POST/PATCH /tasks`,
`PATCH /kb/revisions/{id}`), defaulting to `"html"` — the browser's Tiptap
editor keeps sending real HTML exactly as before, so this is zero-risk for
every existing caller including the frontend itself. MCP's `create_task`
and `edit_article` tools take the more opinionated path and treat their
`description`/`body` as markdown unconditionally, no flag to set: that's
what a language model actually writes, and a plain sentence with no markdown
syntax converts to itself wrapped in one `<p>`, never a worse outcome than
the old literal-text rendering. `fenced_code` is the one markdown extension
enabled — a triple-backtick block is how anyone writing markdown expects a
code block, and it happens to emit `class="language-python"` already, the
exact shape `_LANGUAGE_CLASS` expects, with no remapping needed the way
headings need. `tests/test_richtext.py` pins the conversion against
`sanitise()` together, because a case that looks right before sanitising
and wrong after it is the only kind of bug that actually matters here.

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

**Mermaid diagrams needed no backend change at all.** A fenced ` ```mermaid `
block already survives `sanitise()` untouched — `mermaid` matches
`_LANGUAGE_CLASS`'s `language-[a-z0-9+#-]{1,20}` pattern, the identical
allow-list a syntax-highlighted `language-python` block already relies on —
so a diagram written or sent via markdown (including through the
`create_task`/`edit_article` MCP tools) stores correctly today with zero
schema work. The only thing missing was rendering it, which is entirely a
`components/rich-text.tsx` concern:

- **`RichText` splits sanitised HTML on `<pre><code class="language-mermaid">`
  blocks** and swaps each one for a `MermaidDiagram` component instead of
  the usual single `dangerouslySetInnerHTML`. The common case — no diagram
  in the description — stays exactly the one-`div` shape it always was;
  splitting only happens when a mermaid block is actually present.
- **`mermaid` is dynamically imported**, never bundled into the main chunk —
  it's a few hundred KB and the overwhelming majority of descriptions never
  use it, so the common case shouldn't pay for a library it never loads.
- **`securityLevel: "strict"` is not optional.** Mermaid's own DSL supports
  `click` directives that can run arbitrary JS or navigate on click, and a
  diagram's source text is exactly as untrusted as anything else that
  arrived through `sanitise()` — "the client is never trusted" applies to
  the diagram's own syntax, not just the HTML around it.
- **A rendered diagram doesn't hear about a theme toggle on its own.**
  `useTheme` (`lib/theme.ts`) owns the toggle button's own `useState`, which
  a diagram component mounted elsewhere has no way to read — so a diagram
  rendered before a dark-mode click would otherwise freeze in whatever
  theme was current at mount, sitting as a bright box on a suddenly-dark
  page. `MermaidDiagram`'s own `useIsDarkMode` hook instead observes the
  `.dark` class mutation `useTheme` makes on `<html>` directly
  (`MutationObserver`, `attributeFilter: ["class"]`), so an open diagram
  redraws the moment the surrounding page does.
- **The editor shows raw DSL text, never a live-rendered diagram.** Tiptap's
  code block already syntax-highlights as you type via lowlight; mermaid
  isn't a highlighting language lowlight knows, so a `language-mermaid`
  block just sits in plain monospace while editing (added to `LANGUAGES`
  purely so it's selectable from the code-block dropdown, with a comment
  explaining it isn't for highlighting). This is also why editable
  descriptions — `TaskDetail.tsx`'s `Details`, `ArticleDetail.tsx`'s
  `Editor` — both grew a small **Write/Preview toggle**: the task or
  article's own owner is exactly the person who wrote the diagram, and
  without a way to see it rendered without leaving edit mode, the one
  person actually drawing a diagram would never see it themselves. Preview
  renders the current draft through the identical `RichText` the read-only
  view uses — one rendering path, not two.

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

## MCP — somebody's own assistant

Read `app/mcp/server.py`. **Every tool resolves through `services/access.py`,
as the token's owner** — there is deliberately not a single `select()` in that
module. A query written there would be a second access path, and the moment
there are two, one of them is wrong and nobody knows which. `scripts/e2e-mcp.sh`
proves the refusals: a stranger's token, an org admin against a hidden task,
and a read-only token against every write.

**Two credential shapes, not the session cookie either way.** A personal
access token from the account screen (`Authorization: Bearer ayc_…`) — shown
once, SHA-256 at rest, scoped `read`/`write`, revocable from the screen that
made it — or an OAuth access token from the flow at `/oauth/authorize`, see
the "OAuth" section below. An MCP client is not a browser, so neither path
uses the cookie. `require_write` is the single place a read-only credential
is turned away, and it doesn't care which shape produced it — see
`_Principal` in `app/mcp/server.py`.

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

**Knowledge-base tools reuse `services/books.py`/`services/articles.py`
exactly like every other tool reuses its service** — `list_books`,
`list_articles`, `read_article`, `create_book`, `create_article`,
`edit_article`, `publish_article`, `unpublish_article`,
`attach_article_file`. `edit_article` is the one with a real wrinkle:
`autosave_revision` has no partial-update shape (unlike, say, `update_task`),
so passing only `body` still has to resend the *current* `title` — the tool
calls `start_editing_session` first specifically to have that value on hand,
the identical reason the frontend's own autosave keeps a `titleRef` rather
than trusting a stale closure (see "The knowledge base" section). No
`share_book` tool: sharing has no MCP tool for tasks or projects either, so
there was nothing to match parity with. `attach_article_file` is `attach_file`
with one extra step — `start_editing_session` first, to land on the article's
current revision, since attachments anchor to a revision, not the article.

**`update_task` only exposed a quarter of what `create_task` did, for no
reason beyond having been written first — found auditing MCP against the
REST API for parity, not by anyone hitting the gap while using it.**
`create_task` took title, description, project, owner, action-required,
priority and due date; `update_task` exposed only `status`/`priority`/
`due_on`/`action_required_email` — meaning a task fully specified at
creation had no MCP path to rename, move, re-describe or reassign
afterward, despite the REST `TaskUpdate` schema supporting all of it. Now
carries `title`, `description` (markdown, matching `create_task`),
`project_id` and `owner_email` too. Two of those needed a clearing
convention `create_task` never had to think about, because create has
nothing yet to clear: `project_id=""` makes the task loose again
(`tasks_service.update` already treats an explicit `None` as "make it
loose," so the tool only has to turn `""` into that `None`) — but
`owner_email` is never sent as an explicit `None`, because a task always
has an owner and `tasks_service.update` raises if asked to clear one, so
`if owner_email:` (not `is not None`) is what keeps an omitted field from
being confused with a clearing attempt that isn't a real operation here.

**Closing was missing entirely, and it's one of the most ordinary things
someone would ask an assistant to do.** `close_task`/`reopen_task` both
call `tasks_service.set_open()` — the identical owner-or-admin rule,
identical 403-not-404 for anyone else, `set_open`'s own — and are separate
tools rather than a `closed: bool` parameter on `update_task`, matching
this file's own `tag_task`/`untag_task` precedent for a boolean-shaped
action written as two verbs instead of one flag.

**`mine_only` on `list_tasks` and `activity` said "tasks you own **or have
been asked to act on**" and passed only `owner_user_id`** — so being asked
to act on something was not enough for it to appear in "what needs doing",
which is most of the point of being asked. Fixed with a third person filter
on `access.visible_tasks_stmt`: `mine_user_id`, which **ORs** owner against
action-required where the existing `owner_user_id`/`action_required_user_id`
each narrow to one route and AND together. Both shapes are wanted — the task
list's two separate Owner and Action-required filters are the AND ones, and
this is the same OR `my_priority_tasks_stmt` already writes out for the
dashboard's escalation cards. There is deliberately no equivalent in the web
task list: "mine, either way" is a dashboard question, and the list offers
the two filters separately instead.

**Reminders and time tracking were read-only or entirely absent.**
`create_reminder` covers both of `services/reminders.py`'s two create
paths — task-anchored (`task_id` given) or standalone (`title` given
instead) — behind one tool rather than two, since the only difference is
which one argument was supplied; `update_reminder` mirrors the REST
`PATCH`'s field-presence shape (`done` maps to the same `done_at` stamp).
`start_timer`/`stop_timer`/`log_time` call `time_tracking.start`/`stop`/
`log_manual` directly with no extra access check in the tool itself —
those service functions already resolve the task through
`_readable_task()` internally, the identical reason `set_open` needed no
separate `context_for` call either.

**`task_versions` is read-only, and restoring is deliberately not a tool.**
It reports the earlier versions of a task's title and description (see the
Task versions section above), stripped to prose with `richtext.to_plain_text`
the same way `task` reads `description_text` rather than stored HTML — there
is no generated column on a revision, so the converter does that job on
demand. What it won't do is put one back: a restore silently replaces text
somebody may be working on, and a person asking "what did this say before"
is better served by the words in front of them than by an assistant picking
a version on their behalf. If they genuinely want it back, the text is right
there to pass to `update_task`.

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
- **claude.ai's and ChatGPT's own "Add custom connector" flows now work —
  this used to be flatly untrue, and the fix wasn't OAuth, at first.** The
  original symptom ("Couldn't register with ayeaye's sign-in service…")
  looked like this server needed to run an authorisation server, but the
  actual bug was a Caddy misconfiguration: every `/.well-known/oauth-*`
  path fell through the SPA catch-all and answered `200` with the app's own
  HTML instead of `404`. An OAuth-aware client reads that `200` as "this
  server publishes protected-resource metadata," tries to parse the HTML as
  JSON, fails, and falls back to Dynamic Client Registration against an
  authorisation server that doesn't exist —
  [anthropics/claude-ai-mcp#457](https://github.com/anthropics/claude-ai-mcp/issues/457)
  traced the identical symptom on a different server to exactly this, fixed
  with a plain 404, no OAuth involved. See `infra/caddy/Caddyfile`'s
  `@openid_discovery`/`@oauth_metadata` matchers. **Separately, and worth
  keeping distinct**: this server *now also* runs real OAuth 2.1 with
  Dynamic Client Registration (see the section below), because ChatGPT's
  connector has no bearer-token fallback at all and mandates it — the Caddy
  fix alone was necessary but not sufficient for that client.
- **A `Denied` refusal's own message doesn't reach the client — found adding
  the knowledge-base tools, not caused by them.** `_handle_call_tool` in the
  installed SDK wraps any exception as `ToolError(f"Error executing tool
  {name}: {e}")`, which *should* carry `str(e)` — but the live server
  answers a read-only-token refusal with the bare `"Error executing tool
  create_task"`, no colon, no message, confirmed identically for a
  pre-existing tool (`create_task`) and a new one (`create_book`) via a raw
  `curl` with `Content-Length` checked byte for byte, so it isn't truncation
  either. `isError: true` still comes through correctly — only the detail
  is gone. `scripts/e2e-mcp.sh`'s own `grep -ci "read-only"` assertions for
  this appear to pass, but they're the exact silently-vacuous trap this
  file already warns about below: the script's shared `/tmp/mcp-req.json`
  scratch file races between nested `$(...)` substitutions once several
  tool calls are in flight, and the comparison ends up between two
  independently-mangled values. Not chased further — it's an installed
  dependency's behaviour, unrelated to anything built for this feature, and
  every write refusal still refuses.

**A warning about testing it from a shell.** `e2e-mcp.sh` builds every payload
with `python3 -c json.dumps`, never with escaped quotes inside a shell string.
The inline form silently mangled the request for the calls with the most
arguments — the shell passed a fragment, the server correctly answered
"Parse error", and the harness's own helper swallowed it. It looked exactly
like MCP was losing writes, and it cost an hour of hunting a bug that was
never in the product.

## OAuth 2.1, for Claude.ai and ChatGPT's own connectors

Read `services/oauth.py`. Dynamic Client Registration (RFC 7591), PKCE-only
authorization codes, and rotating refresh tokens — what lets Claude.ai and
ChatGPT add this server as a custom connector with nobody pasting a
personal access token, which their own "connect an MCP server" flows both
expect and (for ChatGPT) mandate outright.

**Hand-rolled, the identical call already made for MFA.** SuperTokens'
`OAuth2Provider` recipe is a paid add-on on the self-hosted core — a
license key, a minimum $100/month, activated against SuperTokens' own
license servers — and even paid for, its "create a client" operation is an
*admin*-authenticated API call, not the public self-registration these
connectors actually need at connect time. Same shape of decision this
codebase already made for `services/mfa.py` (`pyotp`, after SuperTokens'
MFA recipe returned a 402): pay for infrastructure this project's whole
self-hosting philosophy is built around not needing, or hand-roll the
piece that's actually missing.

**No new dependency, because `mcp` already ships one.** The MCP Python SDK
— already a mandatory dependency of `app/mcp/server.py` — carries a
complete, async-native OAuth toolkit: RFC-correct Pydantic wire models
(`mcp.shared.auth`: `OAuthClientMetadata`, `OAuthMetadata`,
`ProtectedResourceMetadata`, `OAuthToken`) and the resource-server
verification primitive (`mcp.server.auth.provider.TokenVerifier`). Every
one of these was confirmed against the actually-installed package before
being relied on, not assumed from documentation. Client registration,
PKCE, and code/token issuance are still plain `async def`s against
SQLAlchemy — the identical idiom `services/tokens.py` already uses for
personal access tokens.

**A missing or bad token needs a real 401 — this codebase almost got it
wrong regardless of OAuth.** `_caller()` used to raise `Denied` *inside* a
tool call, which the MCP protocol turns into an ordinary `200 OK`
JSON-RPC result with an error string in the body — never an HTTP 401. An
OAuth-aware client never sees that as "go start OAuth"; it needs
`WWW-Authenticate` on its very first touch of `/mcp`. Fixing this needed
transport-layer middleware composed by hand around the bare `_mcp_asgi` in
`main.py` — `mcp.streamable_http_app()`'s own return value (a Starlette app
with its own auth routes) is discarded and never mounted, for the `/mcp`
vs `/mcp/` reason `MCPPath` already documents, so its own wiring never ran
either way. `RequireAuthMiddleware` → `AuthContextMiddleware` →
`AuthenticationMiddleware(backend=BearerAuthBackend(token_verifier))`,
wrapped around `_mcp_asgi` before `MCPPath`. `_caller()` now just resolves
the already-verified principal (`get_access_token()`) to a `User` row; a
`_Principal` shim carrying only `.scope` is what lets `_require_write()`
stay unchanged regardless of which credential shape verified the call.

**Four rules**, mirroring `services/tokens.py`'s own three almost exactly:

1. **A client is public unless it proves otherwise.** DCR has no admin
   step, so `client_secret_hash` is NULL for most clients — PKCE is the
   whole proof of possession, OAuth 2.1's own preferred shape.
2. **Every code and refresh token is claimed, not read then trusted.**
   `redeem_code`/`redeem_refresh_token` both use the identical
   `UPDATE … WHERE … RETURNING` shape `reminders.claim` and
   `exports.claim_expired` already use — select-then-update would leave a
   window where two racing requests both succeed, which for a refresh
   token is exactly the reuse this exists to catch.
3. **A rotated refresh token presented again is treated as theft.**
   `replaced_at` is set, not the row deleted, specifically so reuse is
   recognisable — and the whole grant is revoked defensively when it
   happens, not just the one request refused.
4. **A grant's scope is a ceiling, not a promise.** `OAuthClient.scope` is
   what a client may ever be granted; the person consenting narrows it
   further at `/oauth/authorize`, and whatever they chose is copied onto
   each token *at issuance* — a later re-consent never reaches back into a
   token already handed out.

**The consent screen is a real React page, not server-rendered HTML** —
this codebase's firm "browser-facing = React, API = JSON" boundary (the
same reasoning that moved interactive docs under `/api/docs` rather than
breaking it). `views/OAuthAuthorize.tsx` is modelled on `AcceptInvite.tsx`
exactly: outside the signed-in shell, an unauthenticated preview (a
client's name and scope ceiling are public metadata), "sign in, then come
straight back" via `redirectToPath` carrying every original query param,
Allow/Deny once signed in. `POST /api/oauth/authorize/decision`
re-validates everything server-side — nothing the SPA merely echoed back
is ever trusted outright.

**Only the two spec-fixed `.well-known` documents live at the bare
root** (`api/routers/wellknown.py`, mounted in `main.py` like `/health`):
RFC 8414's authorization-server metadata and RFC 9728's protected-resource
metadata (both the bare form and the path-inserted
`/.well-known/oauth-protected-resource/mcp`, the exact request an
OAuth-aware connector makes). Everything else — `/register`, the
`/authorize/preview`+`/decision` pair, `/token`, `/revoke` — lives under
`/api/oauth/*` like the rest of the JSON API, even though the *browser*
lands on the bare `/oauth/authorize` page first; the metadata document is
free to point at whichever URL shape each endpoint actually needs.
`openid-configuration` stays 404 forever (see `infra/caddy/Caddyfile`) —
this is an OAuth 2.1 authorization server issuing scoped API access
tokens, not an OIDC identity provider, and a 200 there would claim a
capability that doesn't exist.

**The Account screen's "Connected apps" card is the revocation surface**,
structurally copied from the Access Tokens card beside it — same
`role="region"`, same row shape, same ghost Revoke button. It's a
different list from Access Tokens on purpose: a personal access token is
something *you* minted; a connected app is a client that registered
itself and went through consent.

## Self-hosting

The bar from PLAN.md §8 — `setup.sh`/`diagnose.sh` reasoning, bringing your
own Postgres or S3, and the real deployment incidents that shaped both — is
documented in the `self-host-troubleshooting` skill rather than here. Load
it when troubleshooting a self-hosted or production deployment of this
project; it isn't needed for ordinary feature work.

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
- **Chromium reports `Infinity` for a played-back note's `duration`, and it
  rendered as the literal string "Infinity:NaN".** A MediaRecorder-produced
  webm never carries a real duration in its container header, so `<audio>`'s
  `loadedmetadata` fires with `duration === Infinity` until something forces
  a seek to the actual end of the stream. `Infinity || 0` doesn't catch it —
  `Infinity` is truthy — so it flowed straight into `clock()`, where
  `Infinity - position` is still `Infinity`, `Math.floor(Infinity / 60)` is
  `Infinity`, and `Infinity % 60` is `NaN`. Playback itself was never
  affected: `onTimeUpdate` reports real positions off the raw stream
  regardless of what `duration` says. Fixed two ways — `clock()`
  (`lib/audio.ts`) now guards `Number.isFinite()` before formatting anything,
  so no future caller can reproduce this by another path; and
  `VoiceNotePlayer`'s `onLoadedMetadata` (`components/voice-note.tsx`) runs
  the standard workaround when it sees `Infinity` — seek to a huge timestamp
  (`1e101`), which makes Chromium scan to the stream's real end and fire
  `durationchange` with the true value, then seek back to `0` before anyone
  sees the jump. `onTimeUpdate` ignores position updates while that probe is
  in flight (`probingDuration` ref), or the seek itself would flash the
  progress bar to 100% and back.

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

## Sparks

Read `services/sparks.py`. Quick capture — an idea, a link, anything not
worth a task yet — reachable from any screen with ⌘J (Ctrl+J), typed into a
dialog, saved, and you're straight back to whatever you were doing. Review
and edit what piles up on `/sparks`.

**Deliberately not the notepad, and not a task note.** The notepad's own
docstring already explains why a task note stays a single field with no
title, no list, no delete — a spark is that same shape *as* a list, one
step further than the notepad in the other direction: no title either, one
field, because a second field to fill in is friction a capture tool exists
specifically to avoid.

**Cross-organisation, unlike the notepad.** The whole point is catching a
thought regardless of which organisation happens to be open when it
strikes — `services/sparks.py` carries no `organisation_id` at all, and
`GET/POST /sparks` sit at the bare root next to the inbox and reminders,
not under `/organisations/{id}`. The ⌘J hotkey and its header button are
bound at the shell level with no `railOrg` guard, unlike search and "New
task" beside them — pressing it on the bare "Your organisations" screen
with zero organisations yet still works.

**Only you, ever — no sharing, no admin override.** The identical
absence-of-a-branch discipline `services/notes.py` and
`services/personal_notes.py` already hold for their own private data:
every statement filters on `user_id == the caller`, full stop, and
`get_or_404` (edit, delete) 404s on somebody else's spark rather than 403 —
its existence is not something you're being told about.

**The filter box on `/sparks` is client-side**, the identical call the
Projects list already makes for its own name filter — this was never a
paged fetch to begin with, so narrowing what's on screen doesn't earn a
round trip. This was also the resolved answer to "should search work with
these": a personal capture list search stays local to its own screen
rather than joining the org-scoped ⌘K palette, which has no cross-
organisation case to handle for anything else it searches.

**Bare URLs are linked, not sanitised.** A spark's body is plain text, not
the sanitised HTML a task description is — there's no rich editor and
nothing here is ever rendered with `dangerouslySetInnerHTML`. `Linkified`
(`views/Sparks.tsx`) splits on a URL-shaped regex and turns only the
matched segments into real `<a>` elements; every other segment is still a
plain React text node, escaped the same as the whole string would have
been. Safe by construction, not by an allow-list — there is no markup to
sanitise because none is ever parsed as markup.

**Editing a card is a click, not a second screen.** No dialog, no
autosave-with-a-debounce like the notepad's own editor — a spark is short
enough that click-to-edit, then blur or ⌘Enter to commit, Escape to
cancel, is the whole interaction. `SparkCard`'s local `body` state resets
from `spark.body` whenever a fresh row lands (a save from elsewhere, or the
initial load), the same "the prop changed under us, not what we're
mid-typing" reasoning the notepad's own editor documents for its `note.id`
dependency, just keyed on the value here since there's no id-per-dialog
instance to key on instead.

## The knowledge base

Read `services/books.py` and `services/articles.py`. Book → article, with
every edit kept as history — a runbook or a policy is durable reference
material, the thing this product had no place for before it existed.

**A book's access model is a project's, unchanged.** `models/knowledge_base.py`'s
`Book`/`BookMember` are near-mechanical copies of `Project`/`ProjectMember` —
owner + grants to a person or a team at `read`/`write`, org admins see
everything, private until shared. `services/access.py`'s `book_level_expression`
and `visible_books_stmt` are the identical copies, and `AccessPanel` (already
generalized to a `basePath` prop for tasks) is reused for books with zero
changes — the third resource to prove that generalization was worth doing.

**`is_private` is both the draft flag and the privacy flag — one boolean, not
two independent dimensions.** An article is born private, and only its owner
can publish it (`can_make_private`, the article-level twin of `can_hide`).
Turning it back on un-publishes it. `effective_article_level` short-circuits
on `is_private` **ahead of** the whole book-access expression, line for line
the same shape `effective_task_level` uses for `is_hidden` — which means
**organisation admins can't see a private article either**, the identical
deliberate hole hidden tasks already carry. `article_level_expression` is the
SQL mirror, proved to agree with the Python function through Postgres by
`scripts/e2e-kb.sh` exactly the way `test_access_matrix.py`'s own docstring
explains for tasks.

**A revision is a whole editing session, not a keystroke — this is the one
place the design had to go further than what was literally asked, to make
"attachments attach to a revision" buildable at all.** `start_editing_session`
resolves the latest revision (`id DESC LIMIT 1`, UUIDv7 sorting chronologically
for free — no `position` column, the same convention checklists and sheets
already use) and either hands it back **mutable** (same person, within
`SESSION_IDLE_WINDOW`) or seeds a fresh row from its title/body and freezes
the old one into history. Every autosave (`autosave_revision`) updates that
one row in place; the endpoint 409s if it's been superseded, the same
"you're editing a stale copy" signal a real conflict would eventually need.
`_latest_revisions` (`services/articles.py`) batches this per page with the
identical `ROW_NUMBER() OVER (PARTITION BY …)` + `aliased(Entity, subquery)`
shape `access.board_stmt` already uses to bound a board column — manually
reconstructing an ORM row from raw subquery columns was tried first and
abandoned before it shipped, because it can't handle a `Computed` column
like `body_text` correctly.

**Rendering a body resolves `data-attachment-id` by attachment id and the
*article's* access, not by exact revision match.** A session's body is
copied forward from the previous one, so a later revision can still
reference an image an earlier revision technically owns —
`attachments_service.image_urls_for_article` scopes the lookup to "any
revision of this article," not just the one being rendered, which is what
makes reopening an old entry in History still show its pictures.
`services/richtext.py` needed zero changes: it already resolves by id and
tolerates one that doesn't come back, the identical graceful-degradation a
task description gets for a deleted attachment.

**Attachments anchor to a specific `ArticleRevision`, a third anchor on the
one `attachments` table** (`ck_attachments_one_anchor` widened to
`num_nonnulls(task_id, conversation_id, article_revision_id) = 1`). The
Files panel is scoped to the revision being *viewed* — a fresh session
starts with none, and an old revision in history shows exactly what was
attached to it at the time — a deliberately narrower promise than inline
images get, and the honest reading of "attached to revision" for a panel
that isn't dealing with copied-forward content. Confirming an upload reuses
the **one shared** `POST /organisations/{id}/attachments/{id}/confirm`
route in `conversations.py` rather than a second confirm endpoint: `_anchor_of`
grew one more branch (resolve the revision, then `articles_service.context_for`
on its article), the same generic-dispatch shape it already had for a task
versus a conversation.

**`components/task-files.tsx` became `components/files-panel.tsx`, and
`FilesPanel` takes a `basePath` prop instead of a `taskId`** — the identical
one-prop generalization `AccessPanel` went through, for the identical
reason: a second real caller. `RichTextEditor` got the same treatment
(`taskId` → `basePath`, plus an optional `noun` for its hint copy) so a
pasted screenshot in the article editor stages to
`${basePath}/files` regardless of which resource that is. `TaskFile` (the
type) is now `FileItem` with `from_comment` made optional, since an article
revision has no comment thread to have arrived from.

**Generalising a component is not a licence to generalise its copy, and
this one cost six browser tests to learn.** The first version of
`FilesPanel` dropped the noun out of the two user-facing strings that had
one — `aria-label="File to add to this task"` became `"File to add"`, and
the drop overlay's "Drop to attach to this task" became "Drop to attach" —
on the reasoning that the panel no longer knows it's a task. Both are
worse copy on their own terms: an accessible name of "File to add" tells a
screen reader nothing about what it attaches to, which is the one thing
that label exists to say. They also broke `task-ux.spec.ts` (×3),
`realtime-task.spec.ts` and `drag-drop.spec.ts` (×2), every one of which
addresses those controls by exactly that wording — and none of it showed
up until the browser suite was next run, several commits later, because
neither `pnpm typecheck` nor any HTTP suite can see a string. `FilesPanel`
now takes the same `noun` prop `RichTextEditor` already had, defaulting to
`"task"`, so the task screen's strings are byte-identical to what they
always were and `ArticleDetail` passes `noun="article"`. **When a shared
component swallows a caller-specific word, give it a prop, not a
shrug** — and run `./scripts/e2e-browser.sh` after any refactor that
touches copy, because it is the only suite that reads it.

**A nav item can break a test three screens away.** Adding "Knowledge base"
to the rail made `tags.spec.ts`'s `getByText("Knowledge base")` — asserting
a tag chip had been created — match two elements and fail on strict mode.
The product was right and the locator was loose; it now asserts on the
chip's own `Remove tag Knowledge base` button, which can only ever be the
one thing meant. Same family as the toast-title-versus-history-line trap
below: any bare `getByText` for a word that could plausibly become a nav
item, a heading or a button label somewhere else is a test waiting to fail
for a reason that has nothing to do with what it's testing.

**No locking: silent last-write-wins**, same as everything else in this
product that isn't explicitly collaborative — two people editing the same
article is not a case this design tries to prevent.

**Search matches only the current revision's text**, the same "search the
live content, not history" rule a task description already follows.
`search.articles_stmt` joins to the latest revision per article through a
correlated scalar subquery (`ORDER BY id DESC LIMIT 1`, the identical
shape `_inherited_project_rank` demonstrates elsewhere) and reuses
`article_level_expression` for the WHERE clause — the vanish-from-contents
behaviour and search agree by construction, not by a second, separately
maintained check. `body_text` is `article_revisions`' own generated column,
mirroring `tasks.description_text` stripped-HTML-for-search contract
exactly, down to the same `regexp_replace` DDL from migration 0015.

**`book_shared` is one more notification kind, wired the way `task_shared`
actually works — not the way `project_shared` turned out to.** Sharing a
project fires no notification at all today; `KIND_PROJECT_SHARED` is a
constant in the closed set with no `notify()` call anywhere behind it. That
looks like a plan that was never finished rather than a design decision, so
`services/books.py::grant` was wired to notify a directly-granted user, the
same shape `tasks_service.grant` already uses (never on a team grant, never
when granting to yourself) — matching what a "book_shared" notification
should plainly do, not perpetuating a gap it happened to inherit by naming
convention. No notification for publishing or privatising an article: the
owner's own action on their own thing, the same "no notification on
generation" reasoning recurring tasks already document.

**A real bug found only by curl-testing the routes, not by reading them:**
the router's own `prefix="/organisations/{org_id}/kb"` combined with six
routes each additionally hardcoding a leading `/kb/articles/...` or
`/kb/revisions/...` — doubling the segment to `.../kb/kb/articles/...`,
404ing every one of them. Ruff, mypy and the unit suite all passed; nothing
short of an actual HTTP request against the live path would have caught it,
which is why Phase 3 of this feature's build order was "curl-test before
moving on" rather than "trust the code review."

**`ArticleOut` shipped once without an `access` field, and the frontend had
no way to decide whether to render the editor or a read-only view without
it** — `BookOut` already carried `access: str`, and the article schema's
own author (also this session) simply forgot the identical field on its
sibling. `_article_out()` already threaded a `level` parameter through
every one of its four call sites for the `can_make_private` computation;
the fix was one more field on the response, not a second lookup.

**The frontend autosave cannot reuse the notepad's own "send only the
changed field" shape**, and copying it verbatim would have shipped a bug:
`services/personal_notes.py`'s `PATCH` is a genuine partial update, but
`autosave_revision` always overwrites both `title` and `body` unconditionally.
Sending only the just-changed field — the notepad's own pattern — would
silently blank out whichever field a stale closure over React state hadn't
just touched. The fix is a `titleRef`/`bodyRef` pair updated synchronously
inside `queueSave`, so a debounced `save()` always sends the *current* value
of both fields regardless of which one triggered it, not a value captured
when the callback was created.

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

**A long, unbroken duplicate-task title could push the whole dialog wider
than its own `max-w-sm` — two separate `min-width: auto` floors stacked on
top of each other, not one bug.** `NewTaskDialog`'s "Similar tasks already
exist" box renders each match as `<a className="flex ...">` wrapping a
`<span className="truncate">`; a flex *item* defaults to `min-width: auto`,
which floors it at its own content's natural width regardless of
`truncate` — the ellipsis CSS never gets the chance to apply, because the
box refuses to shrink small enough to need it. That alone was fixed with
`min-w-0` on both the `<a>` and the inner `<span>`. But `DialogContent`
itself is `display: grid` (Base UI's own markup), and its direct child —
the plain `<div className="space-y-4">` wrapping the entire dialog body —
is *itself* a grid item with the identical default floor. Fixing only the
inner flex left the outer grid item overflowing the dialog's box by
hundreds of pixels regardless, invisible without checking a computed style
because `max-width` still clamped the dialog's own rendered box — the
overflow was the *content* silently spilling past it, not the dialog
itself growing. `min-w-0` was needed at both levels; a single flex or grid
item without it anywhere on the path from a long string up to a
width-constrained ancestor is enough to defeat every `truncate` below it.

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
- **A detail screen must be keyed to the thing it shows, or going straight
  from one to another carries the last one's state along.** Reported as
  "jump to a task from ⌘K while already on a task and the title stays from
  the previous one" — and it was exactly that: both tasks match
  `orgs/:orgId/tasks/:taskId`, so React Router keeps the same component
  instance, and `Details`' `useState(task.title)` only ever runs on mount.
  Everything fed straight from props (the heading, the pickers, the
  breadcrumb) updated around it, which is what made it look like only
  *some* fields were stale — the title and the description were the two
  held in local state. The same `useState(x.name)` shape sat unnoticed in
  `ProjectDetail` and `BookDetail`; the task screen also carried its
  collapsed-panel state, a half-typed delete confirmation and a
  half-written comment across. `Keyed` in `main.tsx` wraps all four detail
  routes and keys them on their id param, so a different thing is a
  different screen. **Fix the class, not the field:** syncing each field
  with an effect works until the next field is added, and the remount
  costs nothing here — everything on these screens already refetches on
  the id, and `use-realtime`'s 250ms linger exists precisely so
  subscription churn drops nothing. Pinned by "the editable fields belong
  to the task you arrived at" in `task-ux.spec.ts`, which fails on the
  title without the key.
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
- **A dialog taller than the viewport used to grow off the top *and* the
  bottom of it at once, with nothing anywhere allowed to scroll.**
  `DialogContent` is `fixed top-1/2 left-1/2 -translate-y-1/2` — centred,
  so overflow is symmetrical — and it carried no `max-height` and no
  `overflow`. Reported against the new-task dialog, where `Textarea`'s
  default `field-sizing-content` (the same auto-growing behaviour the
  notepad's own editor documents) means the description field grows with
  every line typed until the Title field is above the screen and Create is
  below it, both unreachable, no scrollbar in sight. Latent in *every*
  dialog, not that one. Fixed in two places, deliberately:
  `DialogContent`'s base classes gained `max-h-[calc(100dvh-2rem)]
  overflow-y-auto` as a **safety net** — `dvh` so a phone's collapsing
  browser chrome can't hide the footer — so the worst any dialog can now
  do is scroll as a whole. That is a hand edit inside
  `components/ui/`, which is generated: re-adding `dialog` to update it
  drops the fix silently, and every dialog in the product goes back to
  being able to grow off-screen. And a dialog that would rather pin its header
  and footer says so itself with `flex flex-col` plus a `min-h-0 flex-1
  overflow-y-auto` body, which `NewTaskDialog` now does and the notepad's
  editor already did (`cn`'s tailwind-merge lets that `flex` replace the
  base `grid`). Two things about the fix are load-bearing: **`min-h-0` on
  the scrolling body** — a flex child's default `min-height: auto` floors
  it at its content's height, so `flex-1` alone lets it push the footer
  out of the dialog instead of scrolling, the exact vertical twin of the
  `min-w-0` trap the duplicate-title box on the same dialog already
  documents — and **`overflow-hidden` on any popup that scrolls
  internally**, or the base `overflow-y-auto` leaves it a second scroll
  container nested around the first. Nothing floating was clipped by the
  new overflow because `EntityPicker` and every menu already portal to
  `document.body`; the search palette was already `overflow-hidden` for
  its own results list. Pinned by `e2e/tests/task-ux.spec.ts`'s "a long
  description leaves the title and Create reachable", which asserts on
  **geometry, not `toBeVisible`** — every control stayed rendered and
  "visible" all along, which is exactly why nothing caught this earlier;
  the test reads the popup's own bounding box (it sat at `y = -501.5`
  before the fix) and calls `scrollIntoViewIfNeeded`, which has nothing to
  scroll on a `fixed` popup with no scroll container inside it.

Two more real deployment incidents — a Caddy restart that didn't actually
reload, and an orphaned dev container on a production host — are documented
in the `self-host-troubleshooting` skill rather than here, alongside the
rest of the self-hosting bar; load it when troubleshooting a self-hosted or
production deployment.

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
./scripts/e2e-oauth.sh                  # DCR, PKCE, rotating refresh tokens, a real 401
./scripts/e2e-planner.sh                # the pool, the buckets, and the admin override
./scripts/e2e-recurring-tasks.sh        # the generation sweep, run twice, sending once
./scripts/e2e-mfa.sh                    # TOTP, backup codes, the org toggle, not-instant-on-purpose
./scripts/e2e-exports.sh                # yours only not even an admin's, build, download, autodelete
./scripts/e2e-task-sharing.sh           # sharing one task, never the project it's filed in
./scripts/e2e-dependencies.sh           # the DAG stays a DAG, informational, never enforced
./scripts/e2e-task-revisions.sh         # what a save replaced, one row per save, restoring is write
./scripts/e2e-notification-channels.sh  # email/Telegram/webhook routing, a signed delivery, /task and /org
./scripts/e2e-working-hours.sh          # idempotent, bounded, visible to a shared org and nobody else
./scripts/e2e-sparks.sh                 # quick capture, cross-organisation, nobody else ever
./scripts/e2e-kb.sh                     # book access, private-article vanish, revision sessions, search
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
- **`getByRole("dialog")` also matches every toast on screen.** Base UI's
  toast is `role="dialog" aria-modal="false"`, so an assertion scoped to
  "the dialog" starts failing on strict mode the moment a test asserts a
  toast and then opens a popup — which is the ordinary shape of "save,
  then check the result". Scope with
  `page.locator('[data-slot="dialog-content"]')` when a toast could still
  be alive. Cost real time on the Versions dialog, where it looked like
  the dialog hadn't opened.
- **A test organisation named after the feature will collide with the
  feature's own controls.** An org called `Versions 1788…` gave the
  organisation switcher the accessible name "Versions 1788…", so
  `getByRole("button", { name: "Versions" })` opened the org menu instead
  of the dialog, and the failure screenshot showed a wide-open switcher
  with no explanation. Name test orgs after nothing in particular, and use
  `{ exact: true }` on button names that are also common words.
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
