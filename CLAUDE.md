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
    │       │                #   note (private, per person), reminder,
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
    │       │                #   tags.py notes.py reminders.py presence.py
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
  has the identical shape — don't rediscover it.

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

## Tags, notes and reminders

Three small subsystems on the task, and each has exactly one rule worth
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

## The scheduler

A tenth container, `taskiq scheduler app.tasks:scheduler`, running one hourly
job. It earns its place because a reminder has to arrive whether or not anybody
has the app open: a loop inside the API dies on every reload in dev and fires
twice the day somebody runs two replicas.

It only **enqueues** — the work happens in the worker, so a slow sweep can't
delay the next tick. `LabelScheduleSource` reads the cadence off the task's own
`schedule=` label, so a job's timing lives next to the code it runs rather than
in a config file that can disagree with it.

Everything it triggers must be idempotent regardless. That is a rule about the
jobs, not about the scheduler, and it is why the reminder claim exists.

## The dashboard, and what belongs to a person

`/orgs/{id}` is the organisation's home and shows two things: what everyone has
been told, and who isn't here. The people roster moved to `/orgs/{id}/people` —
a roster is a reference screen you visit on purpose, and it was only the landing
page by accident of being built first.

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

**Changing your password verifies the current one** (`verify_credentials`, not
`sign_in` — checking a password shouldn't mint a session). A session left open
on a shared machine must not be enough to lock its owner out of their account.
SuperTokens owns the password policy and its rejection is passed straight
through; restating it here would be two rules that can disagree.

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

The selectors are SuperTokens' own `data-supertokens` hooks — the documented
styling surface, but still someone else's markup. A test asserts the hooks
still exist, because an upgrade that renames one reverts the screen to stock
rather than breaking it, and that is exactly the regression nobody notices.
The button label is literally the string "SIGN UP"; that is their copy, not a
`text-transform`, and it is not worth overriding.

## Attachments

Read `services/attachments.py`. The bytes go **browser → storage directly**
and never pass through the API — a phone video must not occupy a worker for two
minutes — and that forces the three-step shape:

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
due date, project, tags, files, grants, time entries, hide/unhide. Three
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
docstring has the three legal row shapes and the CHECK constraints that allow
exactly those.

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

## Running and testing

```bash
./scripts/setup.sh && docker compose up -d        # http://localhost
./scripts/diagnose.sh                             # when something is wrong
docker compose logs -f api
```

Mailpit (dev only): http://localhost:8025. API docs: http://localhost:8000/docs
— the API's own port, published in dev only because Caddy routes only `/api`
and `/health`.

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
./scripts/e2e-notes.sh                  # private notes: nobody else, ever
./scripts/e2e-reminders.sh              # the sweep, run twice, sending once
./scripts/e2e-dashboard.sh              # passwords, out of office, announcements
./scripts/e2e-mcp.sh                    # access tokens, and MCP acting as a person
./scripts/e2e-planner.sh                # the pool, the buckets, and the admin override
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

Storage keys are deliberately brand-free (`ui-theme`): a key with the product
name in it silently resets everyone's saved preferences the day the name
changes.
