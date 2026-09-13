# ayeayecaptain

Project and task management, self-hosted first. One FastAPI backend, one React
app, one Postgres, one hostname.

[PLAN.md](PLAN.md) is the brief and the reasoning behind the decisions. This
file is the state of the code and the rules that hold it together. Where the
two disagree, PLAN.md is the intent and this file is what actually exists.

**Reference implementation:** `/Users/q/Projects/tuts/modern` (the `prohandl`
repo) — same stack, different domain. Copy from it deliberately, never
wholesale: the domain overlap is close to zero.

**Per-feature detail lives in `.claude/rules/`**, scoped by path so a rule
loads when you open the files it is about. The index is at the bottom of this
file. This file holds only what is true everywhere.

## Where we are

**The plan is complete — phases 0 through 9, all verified.** Organisations,
teams, projects and the access model; tasks, workflow and the notification
inbox; time tracking; comments, realtime, attachments and voice notes;
self-host polish; the task screen; and the things people asked for once
they'd used it. Since then: the knowledge base, MCP and OAuth, notification
channels, the planner, the calendar, instance administration, and a run of
smaller features. Read the git log for what landed when.

**One deviation from PLAN.md worth knowing:** it sequences access as Phase 3,
after structure. It was built with Phase 2 instead, because the product
decision is that projects are private by default — shipping "every member
sees every project" first and inverting it later is exactly the kind of
default that survives by accident.

Verified by the unit suites, the `./scripts/e2e-*.sh` HTTP suites and
`./scripts/e2e-browser.sh` in a real Chromium, which also photographs every
screen in both themes into `e2e/artifacts/shots/`.

What's left is judgement calls, not phases: the open questions in PLAN.md §9
that are genuinely product decisions, and whatever using it surfaces.

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

**`instance_admins` is not a counter-example**, and its being a table rather
than a column on `users` is why. It answers a different question — does this
installation let you see the operator panel — and confers no access inside any
organisation whatsoever; `services/access.py` never learns it exists, and a
test asserts that by reading the module's source. Same side of the same line
as `users.disabled_at`. See "Instance administration".

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

`apps/api` (FastAPI) and `apps/web` (React) are the two applications; `infra/`
holds the Caddyfile and Postgres init; `scripts/` holds the end-to-end suites;
`e2e/` is Playwright in **its own top-level package**, deliberately not in
`apps/web` — the production image runs `pnpm install --frozen-lockfile`, so
putting it there would ship browser tooling in the deployed bundle.

Read the tree for the rest. Four things about it are not derivable by looking:

- **`main.py` is `create_app()`: middleware and router mounting, nothing
  else**, so it doesn't grow as the API does.
- **`api/routers/` is HTTP only; `services/` holds the logic.** Start at
  `services/access.py` — it decides who can see what, and everything else
  composes it.
- **`tasks/` is the taskiq worker.** A handler module not imported in
  `tasks/__init__.py` is silently never registered.
- **`db/base.py` holds no engine.** Sessions come from `db/session.py`.

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

## Self-hosting

The bar from PLAN.md §8 — `setup.sh`/`diagnose.sh` reasoning, bringing your
own Postgres or S3, and the real deployment incidents that shaped both — is
documented in the `self-host-troubleshooting` skill rather than here. Load
it when troubleshooting a self-hosted or production deployment of this
project; it isn't needed for ordinary feature work.

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
./scripts/e2e-triage.sh                 # the unassigned queue, and it stays access-scoped
./scripts/e2e-search.sh                 # fuzziness, ranking, and permissions
./scripts/e2e-time.sh                   # timers, corrections, rollups
./scripts/e2e-comments.sh               # threads, debouncing, mentions, the socket
./scripts/e2e-attachments.sh            # the upload handshake, against real storage
./scripts/e2e-task-files.sh             # priority, task files, thumbnails, moving a task
./scripts/e2e-hidden.sh                 # the one place access is subtracted
./scripts/e2e-tags.sh                   # the vocabulary, and "off the board"
./scripts/e2e-checklists.sh             # more than one list, write-gated, read-only sees but can't touch
./scripts/e2e-sheets.sh                 # a cell's existence IS the check, idempotent, who/when recorded
./scripts/e2e-notes.sh                  # private notes: nobody else, ever
./scripts/e2e-notepad.sh                # the notepad: same rule, a list this time, org-scoped
./scripts/e2e-bookmarks.sh              # the shared shelf: three different bars, and only an owner pins
./scripts/e2e-changelog.sh              # the dated log, and ⌘K agreeing with the screen it links to
./scripts/e2e-reminders.sh              # the sweep, run twice, sending once
./scripts/e2e-dashboard.sh              # passwords, out of office, announcements, digest hour
./scripts/e2e-mcp.sh                    # access tokens, and MCP acting as a person
./scripts/e2e-oauth.sh                  # DCR, PKCE, rotating refresh tokens, a real 401
./scripts/e2e-planner.sh                # the pool, the buckets, and the admin override
./scripts/e2e-agent-queue.sh            # a planner somebody else arranged, worked down over MCP
./scripts/e2e-recurring-tasks.sh        # the generation sweep, run twice, sending once
./scripts/e2e-mfa.sh                    # TOTP, backup codes, the org toggle, not-instant-on-purpose
./scripts/e2e-instance.sh               # the panel is 404 until the shell says otherwise; suspension, both kinds
./scripts/e2e-exports.sh                # yours only not even an admin's, build, download, autodelete
./scripts/e2e-task-sharing.sh           # sharing one task, never the project it's filed in
./scripts/e2e-dependencies.sh           # the DAG stays a DAG, informational, never enforced
./scripts/e2e-task-revisions.sh         # what a save replaced, one row per save, restoring is write
./scripts/e2e-notification-channels.sh  # email/Telegram/webhook routing, a signed delivery, /task and /org
./scripts/e2e-notification-emails.sh    # per-organisation address, confirmed first, proved against Mailpit
./scripts/e2e-email-verification.sh     # the enforced path; restarts the API to turn it on, and back
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

**There is no tagline, and the landing page's heading is not in the bundle
at all** — it is `instance_settings.landing_headline`, the operator's to
write from the Instance panel or `scripts/instance.sh headline`, falling
back to `BRAND.name`. A sentence compiled into the frontend is a sentence
every self-hosted installation is stuck with, which is what "Just another
take on the to-do app" was. The favicon (`apps/web/public/favicon.svg`)
carries the anchor and no name, so a rename does not touch it.

## Where the rest of this documentation lives

Per-feature detail is in `.claude/rules/`, each file scoped with a `paths:`
front-matter block so it loads when you open the code it describes. You can
also read one directly when you need it before touching a file.

| Rule | Covers |
|---|---|
| `tasks.md` | tasks, the board, triage, task versions |
| `task-content.md` | tags, private notes, reminders, pins, checklists, sheets |
| `scheduler.md` | the scheduler container, recurring tasks, the worker |
| `dashboard.md` | the dashboard, out-of-office, working hours |
| `projects.md` | projects, teams, the projects list |
| `richtext.md` | sanitised HTML descriptions, markdown, mermaid |
| `mcp.md` | the MCP surface and OAuth 2.1 |
| `instance-admin.md` | the operator panel and `scripts/instance.sh` |
| `auth.md` | SuperTokens, MFA, email verification, login history |
| `attachments.md` | the upload handshake, voice notes, data export |
| `comments-realtime.md` | the conversation thread, mentions, the socket |
| `notifications.md` | the inbox, channels, Telegram, webhooks |
| `planner-calendar.md` | the day planner and the calendar |
| `personal-lists.md` | the notepad, sparks, bookmarks, the changelog |
| `knowledge-base.md` | books, articles, revisions |
| `time-tracking.md` | timers, corrections, rollups |
| `search.md` | why Postgres and not a search engine |
| `organisations.md` | membership, invites, organisation settings |
| `web-ui.md` | routing, Base UI, dialogs, pickers, the shell |
| `browser-tests.md` | writing Playwright tests here |
| `infra.md` | compose, images, Caddy, migrations, backups |

One procedure is a skill rather than a rule, because it is multi-step and
only wanted when you are actually doing it:

- **`self-host-troubleshooting`** — the self-hosting bar, `setup.sh` /
  `diagnose.sh` reasoning, bringing your own Postgres or S3, and the real
  deployment incidents that shaped both. Load it when troubleshooting a
  deployment, not during ordinary feature work.

**When you learn something new, put it where it will be read again.** A fact
about one feature belongs in that feature's rule, not here — this file is for
what is true everywhere. If a rule grows past roughly 400 lines, split it the
way `tasks.md` and `task-content.md` are split, by the files it is about.
