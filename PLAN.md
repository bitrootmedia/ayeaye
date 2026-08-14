# ayeayecaptain — build plan

Project and task management, self-hosted first. A single free public instance
will run at **ayeayecaptain.io**; everyone else runs it themselves.

This document is the brief for a fresh start. It carries the decisions and the
reasoning behind them, because the reasoning is the part that stops them being
undone six weeks later.

**Reference implementation:** `/Users/q/Projects/tuts/modern` (the `prohandl`
repo). Same stack, different domain. Where this plan says *copy*, copy from
there. Do **not** copy the repo wholesale — the domain overlap is near zero and
you'd spend longer deleting than writing.

---

## 1. The product, in one pass

- Users sign up, log in, reset a password. SuperTokens.
- A user creates **organisations** and can belong to several.
- They invite people **by email**; if the address has no account yet the invite
  waits and binds on signup.
- Inside an organisation: **teams**, **project groups**, **projects**.
- **Tasks** live in exactly one project, or in none (loose, at org level).
- Task visibility is **inherited from the project, or granted per user**.
- Each task has an **owner** (can do anything; the only one who may close it) and
  at most one **action-required user** (gets notified the moment they're set).
- **Time tracking** per task, with a history of work rolled up by task and
  project.
- **Message threads** on tasks and projects, with **voice notes**.
- **Notifications** in-app and by email.

No backoffice. No landing page. No billing.

---

## 2. Decisions made up front

### 2.1 Drop Casbin

**Don't carry it over.** In the reference project Casbin ended up doing almost
nothing: a handful of coarse staff permissions (`catalog/manage`,
`credits/manage`), while every interesting authorization question lived in
hand-written SQL in `services/access.py`. The reason is structural — the Casbin
model there is plain RBAC with exact string matching, so it can neither express
"user U may read task 47" nor answer "list every task U can see", and that second
question is what every list endpoint needs.

ayeayecaptain is *entirely* per-resource and dynamic, and has no staff tier at
all. Casbin would carry zero load while adding a policy store, a sync problem
(its adapter is synchronous psycopg2) and a second place to look when something
is denied.

**Instead:** one `services/access.py`, the same shape as the reference — a
membership/grant table plus SQL builders that resolve visibility in a single
statement. Org-level roles (`owner` / `admin` / `member`) are a column on the
membership row, not a policy engine.

Revisit only if you grow genuinely policy-shaped rules ("no one in Contractors
may see Finance projects on weekdays"). You won't for a long time.

### 2.2 One React app, no `packages/ui`

The reference has four apps and therefore a shared package, which forces
`@import "tailwindcss" source(none)` plus a per-app `@source` declaration, a
repo-root Docker build context, and a workspace-aware install. All of that
exists to solve a problem you won't have.

**One app, standard Tailwind, app-scoped Docker context.** Copy the shadcn
components straight into `apps/web/src/components/ui/`. If a second frontend ever
appears, extract the package then.

### 2.3 One compose file

The reference has `docker-compose.yml` (dev) and `compose.prod.yml`, and that
split caused a real production incident: `docker compose up -d --build` silently
brought up the dev stack on the server, with no reverse proxy, and the site was
dark while every container looked healthy.

For something strangers self-host, that failure mode is unacceptable.

**Ship one `docker-compose.yml` that is production-shaped**, with a
`compose.override.yml` for development. Compose auto-loads the override when
present, and a self-hoster never has it. `docker compose up -d` is then correct
in both places, and there is no flag to forget.

### 2.4 Email is optional

Invites go by email, which makes SMTP the single biggest blocker to a five-minute
self-host. So: **every invite also produces a copyable link in the UI.** With
`SMTP_HOST` unset the app logs what it would have sent and the inviter pastes the
link into Slack. Password reset degrades the same way — surface the link to an
org owner rather than dead-ending.

This is the difference between "works after you set up Mailgun" and "works".

### 2.5 Keep

Realtime (Redis pub/sub + WebSocket), Taskiq, Postgres, RustFS, SuperTokens,
FastAPI, React + the shadcn/Base UI component set and design tokens.

---

## 3. Data model

Single UUIDv7 primary key everywhere, `server_default=text("uuidv7()")`, exposed
as `id`. Postgres 18. (Same convention as the reference — see its `CLAUDE.md`.)

```
users ──┬── organisation_members ──► organisations
        │        (role: owner|admin|member)
        │
        └── team_members ──► teams ──► organisations

organisations ──► project_groups ──► projects ──┐
              └────────────────────► projects ──┴──► tasks
                                                       │
tasks (project_id NULLABLE — a loose task belongs to the org)
   ├── task_grants        (principal = user XOR team; level = read|write)
   ├── task_events        (append-only history)
   ├── time_entries
   └── conversations ──► messages ──► message_attachments
```

**`organisations`** — name, slug, created_by. The tenancy boundary; everything
else hangs off it.

**`organisation_members`** — (org, user) unique, `role`, `status`
(`invited` | `active`), `invited_email`, `invited_by`. One table for membership
*and* pending invites, so binding at signup is one update. Copy the pending-bind
trick from `services/users.get_or_create` in the reference.

**`teams`** / **`team_members`** — a named set of users inside an org. Teams
exist to be the target of a grant, so a grant's principal is a user **or** a
team, enforced with `CHECK (num_nonnulls(user_id, team_id) = 1)` — the same
shape as the reference's `shares` table.

**`project_groups`** — flat, inside an org. Resist making them a tree; you can
add nesting later, and a `parent_id` you never use still complicates every query.

**`projects`** — org, optional group, name, status, archived_at.

**`project_members`** — grants on a project (user XOR team, level). Project
membership is what task visibility inherits from.

**`tasks`** — org, nullable project, title, description, status, `owner_user_id`,
`action_required_user_id` (nullable, at most one by column), due date, position.

**`task_grants`** — bespoke per-task access, additive to whatever the project
grants.

**`task_events`** — append-only: created, status changed, owner set, action
required set, closed, time logged, comment posted. This *is* the "history of
work"; don't build it twice.

**`time_entries`** — task, user, `started_at`, `ended_at` (NULL = running),
`note`. Add a partial unique index so a user can only have one timer running:
`CREATE UNIQUE INDEX ... ON time_entries (user_id) WHERE ended_at IS NULL`.
Manual entries arrive with both timestamps set.

**`conversations` / `messages` / `message_attachments`** — copy nearly verbatim
from the reference, changing the anchor from "accepted offer" to "task or
project". Voice notes come free with them.

**`notifications`** — copy the reference's table and inbox wholesale; change the
`kind` CHECK values.

---

## 4. The access model — write this first, it is the whole system

Copy the *approach* from `services/access.py`, not the code. Four rules, and they
should be in the module docstring:

1. **Access flows down.** Org → project group → project → task. A grant on a
   project covers its tasks.
2. **Most-permissive-wins.** Effective level is the MAX over the resource and
   its ancestors, across both direct user grants and the user's team grants.
   Consequence to state out loud: you cannot carve an exception out of a broader
   grant. That needs deny rules; don't add them.
3. **No access reads as 404, never 403.** 403 only means "you can see this, but
   not at that level."
4. **Every list endpoint resolves access in ONE statement.** Build
   `visible_projects_stmt(user, org)` / `visible_tasks_stmt(...)` returning a
   `Select`. Never a per-row check inside a loop.

Decisions to make before writing it:

- **Loose tasks (no project).** Recommendation: visible to the creator, the
  owner, the action-required user, explicit grantees, and org admins — *not* the
  whole org. Least surprising, and it makes "no project" a deliberate choice
  rather than a leak.
- **Does access flow up?** Recommendation: yes, read-only, exactly as the
  reference does — given a task you can see its project's name for breadcrumbs,
  but not its sibling tasks, and it doesn't join your project list.
- **Org admins.** Recommendation: `owner`/`admin` see everything in the org.
  Simple, expected, and it stops "the only person who could see it left".

Test this with a pure, infra-free matrix, the way the reference does — its
access tests need no database and run in about a second.

---

## 5. Task workflow

Owner and action-required are different things and should stay different:

- **Owner** — responsible, can do anything, **the only one who may close**.
  Required; default to the creator.
- **Action required** — at most one, nullable. Setting it notifies that person
  immediately. Clearing it is not a close.

Rules worth pinning in tests:

- Setting action-required to the same user twice must not re-notify (debounce on
  transition, not on write — the reference does the same for chat messages).
- Only the owner closes. If a non-owner tries: 403, not 404 — they can see it.
- Changing owner is an event, and the new owner is notified.
- If the owner is removed from the org, the task needs a new one. Decide:
  reassign to org owner, or block removal. Recommendation: **reassign and record
  an event** — blocking removal makes offboarding a puzzle.

Every one of these writes a `task_events` row.

---

## 6. What to copy, file by file

From `/Users/q/Projects/tuts/modern`:

**Copy nearly as-is**
- `apps/api/src/app/core/` — config, logging, lifespan, mailer
- `apps/api/src/app/db/` — base (no engine), session
- `apps/api/src/app/realtime/` — ConnectionManager + Redis pub/sub. Keep
  `dispatch_to_users()`; drop the watcher concept, nothing here needs it.
- `apps/api/src/app/storage/s3.py` — including the two-endpoint comment; that
  distinction is load-bearing
- `apps/api/src/app/tasks/` — broker + the "import handlers here" pattern
- `apps/api/src/app/security/authn.py` and `security/email.py` — SuperTokens
  setup and the custom password-reset delivery
- `apps/api/src/app/services/users.py` — the local-user mirror and pending-bind
- `apps/api/src/app/services/notifications.py` + `models/notification.py` +
  the notification router and `packages/ui` inbox components
- `apps/api/src/app/services/media.py` + `models/media.py` — the presigned
  three-step upload handshake
- `services/conversations.py`, `models/conversation.py`, and the whole
  `chat-*.tsx` component set including `lib/audio.ts` and `lib/storage.ts`
- `infra/nginx/spa.conf`, the `migrate` one-shot compose service, `DEPLOY.md`
  and `infra/diagnose.sh` as starting points

**Copy the thinking, write fresh**
- `services/access.py` — different hierarchy, same four rules and same
  single-statement discipline
- `api/deps.py` — you need `CurrentUser` and a new `CurrentOrgMember`

**Do not copy**
- Anything under `services/` for assets, projects (theirs), catalog, offers,
  shares, credits, leads, providers, ingest, pricing
- Casbin: `security/authz.py`, `authz/model.conf`
- The landing and backoffice apps, and the whole `packages/ui` workspace
  arrangement

**Two traps that will cost you a day if you rediscover them**

1. `packages/ui/src/lib/storage.ts` captures `window.XMLHttpRequest` **at module
   load, before `SuperTokens.init()` runs**. SuperTokens patches both `fetch` and
   `XMLHttpRequest` and injects `st-auth-mode` into requests it doesn't own;
   RustFS answers `Allow-Headers: *` with `Allow-Credentials: true`, which
   browsers refuse to treat as a wildcard, and RustFS has no way to configure
   allowed headers. Copy that file with its comment intact. It breaks if a caller
   is ever behind `React.lazy`.
2. Voice notes must send the **bare** content type (`audio/webm`, never
   `audio/webm;codecs=opus`) because the presigned signature covers Content-Type
   byte for byte. Chrome/Firefox produce webm, Safari mp4. There's a unit test
   for this; copy it.

Also: `redis` is pinned `<6` because taskiq-redis 1.2.x's blocking listen loop
crashes on redis-py ≥6.

---

## 7. Build order

Each phase ends somewhere demonstrable, with tests green.

**Phase 0 — skeleton and auth.** Repo, one compose file + dev override, FastAPI
with `/health`, Postgres, Redis, SuperTokens, Mailpit, one Vite app with the
design tokens. Login, register, forgot password working end to end, including a
reset email landing in Mailpit. Local `users` table mirroring SuperTokens.
*This is exactly what you asked to start with — stop and use it before going on.*

**Phase 1 — organisations.** Create, list, switch. Membership with roles.
Invite by email with pending-bind, **and a copyable invite link**. Org switcher
in the shell.

**Phase 2 — structure.** Teams, project groups, projects. CRUD and listing, no
permissions yet beyond org membership.

**Phase 3 — access.** `services/access.py`, grants on projects and tasks, the
visibility builders, and the pure test matrix. Retrofit every list endpoint.
Slowest phase; everything after it is easy.

**Phase 4 — tasks and workflow.** Tasks with owner and action-required,
`task_events`, close rules, notifications on assignment. Board and list views.

**Phase 5 — time.** Timer start/stop, manual entries, one-running-timer
constraint, rollups by task, project and person, plus the work history view.

**Phase 6 — messages.** Conversations on tasks and projects, attachments, voice
notes, realtime delivery, notification debouncing.

**Phase 7 — self-host polish.** One-command bring-up, generated secrets, the
`migrate` service, Caddy with a single hostname, a README a stranger can follow,
and `diagnose.sh`.

---

## 8. Self-hosting bar

The thing to protect. A stranger should manage:

```bash
git clone … && cd ayeayecaptain
cp .env.example .env      # edit SITE_HOST and one email address
docker compose up -d
```

To hold that line:

- **One hostname.** No second host for anything — that's why there's no
  backoffice.
- **Generate secrets on first boot** where possible rather than making people
  run `openssl rand` six times. Anything that must be set should abort with a
  clear message: use `${VAR:?...}` in compose, which turns a missing value into
  an explanatory error instead of ten healthy containers and a dark site.
- **Works on localhost with zero edits**, so people can try it before buying a
  domain. Caddy serves `http://localhost` without certificates.
- **Sensible defaults for RAM.** The reference idles at ~920 MB across eleven
  containers, most of it the SuperTokens JVM and Python. Expect similar and say
  so in the README: 2 GB minimum, 4 GB to build on the box.
- **Migrations apply themselves** via the one-shot `migrate` service that the API
  waits on. Never ask a self-hoster to run alembic.
- **Back up in one command**, documented. `pg_dumpall`, not `pg_dump` —
  SuperTokens keeps identity in its own database on the same server, and a dump
  without it is not a backup.

---

## 9. Open questions to settle early

1. **Task statuses** — fixed set, or per-project workflow? Fixed is far simpler
   and can be widened; per-project workflow is a product in itself. Recommend
   fixed (`todo` / `in_progress` / `blocked` / `done`) for v1.
2. **Do projects need per-project roles**, or is a grant level (`read` / `write`)
   enough? Recommend the latter; "who can close" is already answered by task
   owner.
3. **Loose tasks** — confirm the visibility rule in §4.
4. **Time entries editable after the fact?** Recommend yes with an event trail,
   because people forget to stop timers.
5. **Public instance data policy** — ayeayecaptain.io is free and public.
   Decide retention and abuse limits before launch, not after.
