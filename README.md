# ayeayecaptain

Project and task management you run yourself.

One container stack, one hostname, two commands. A free public instance runs at
**ayeayecaptain.io**; everyone else runs their own.

## What it does

- **Organisations** with owners, admins and members. Invite by email — or by a
  copyable link, so it works with no mail server at all.
- **Projects, private by default.** Not to the organisation — to the person who
  created them. Sharing is explicit, to a named person or a named team, and
  every project lists exactly who can see it, organisation admins included.
- **Tasks** with an owner and one action-required person, five statuses, six
  priorities, and open/closed as a separate field — so "closed while still
  blocked" is something you can say. A board that groups by status or by
  priority, a sortable table with filters on every column, and a full history
  of every change. Anything that happens to a task — a comment, a file, an
  hour logged — counts as activity, so "what moved this week" is one click on
  a column heading.
- **Descriptions with formatting.** Headings, lists, quotes, links, and code
  blocks with syntax colouring. Paste or drop a picture straight in — it
  becomes a file on the task, so it's in the Files panel too.
- **Files on tasks.** Drag one onto the task or onto a comment — or use the
  button — and either way it lands in the same Files panel, with thumbnails
  for images that open full size in place.
- **Tags**, shared across the organisation. Mark one *off the board* and its
  tasks stop queueing for attention — that's how a knowledge-base article
  lives alongside the work without cluttering it, while staying searchable.
- **Private notes.** A scratchpad on any task that nobody else can read —
  not the task's owner, not an administrator — and that only you can search.
- **Hidden tasks.** The owner can make one visible to themselves alone,
  overriding every other permission. Sharing stays set up and resumes when
  they un-hide it.
- **Reminders.** A date and a note on any task. You're told the day before and
  again on the day, and anything that has come due sits in a red badge until
  you deal with it.
- **A dashboard per organisation** — announcements from its admins, and who's
  away in the next fortnight — plus an account screen for your password, your
  status line and your own out-of-office days.
- **Time tracking.** One timer, wherever you are. Type "1h30" for work already
  done. Rollups by person, project and task.
- **Comments** on tasks and projects, live over a WebSocket, with file
  attachments and in-browser voice notes.
- **No dropdown you can only scroll.** Anywhere you pick a project or a
  person, the list opens with a filter already focused.
- **Connect your own assistant.** An MCP endpoint at `/mcp` lets Claude — or
  any MCP client — read your work and, if you let it, create tasks and comment
  as you. It acts as *you*: it reaches exactly what you can reach. See
  [Your own assistant](#your-own-assistant).
- **Search everywhere.** ⌘K on any screen, typo-tolerant, as you type. It only
  ever finds what you have access to — the permission check runs in the same
  query as the text match, so there is no index to fall out of date.

Not here, deliberately: no billing, no landing page, no admin backoffice, no
second hostname.

## What you need

- Docker with Compose v2 (`docker compose version` ≥ 2.20).
- **2 GB of RAM** to run it, **4 GB** if you build the images on the same box.
  Measured idle: about 850 MB across ten containers in production (the
  development stack adds a Vite server and Mailpit, taking it to ~1.3 GB). The
  SuperTokens core is a JVM and is the single largest piece; the scheduler,
  which fires reminders, is the smallest.
- Disk for whatever people attach to tasks and comments. It lives in its own
  Docker volume — see [Back it up](#back-it-up), which covers the database *and*
  the files, because you need both.
- A domain and a DNS A record — only if you want it on the internet. It works
  on a laptop without one.

## Run it

```bash
git clone https://github.com/you/ayeayecaptain && cd ayeayecaptain
./scripts/setup.sh
docker compose up -d
```

`setup.sh` writes a `.env` with **generated** secrets. It won't overwrite one
that already exists, and it needs no arguments for a local install.

Open **http://localhost**, create an account, then create an organisation —
you'll be its owner. Invite people from its People screen. There is no separate
admin bootstrap; the first sign-up is an ordinary account.

That is the whole thing. There is no second compose file, no `--build` flag to
remember and no migration step: a one-shot `migrate` service applies the schema
before the API starts, every time, and the API refuses to start if it fails.

In development, mail goes to a **Mailpit** container instead of the internet —
read it at **http://localhost:8025**. That is where the password-reset email
lands.

## Put it on a domain

Point an A record at the machine **first** — Caddy asks Let's Encrypt for a
certificate on startup, and it can't get one for a name that doesn't resolve
here. If you got here by cloning this repo onto the server, **remove the dev
override before you bring the stack up**:

```bash
rm compose.override.yml
```

`compose.override.yml` is committed — that's what makes local development a
plain `git clone` — but Compose auto-loads it whenever it's present, and it
runs the Vite dev server instead of the built app, publishes Postgres's own
port to the internet, and turns on the RustFS/pgweb dev consoles. Left in
place on a real domain, the symptom isn't a blank page: it's the Vite dev
server itself refusing the request — `Blocked request. This host ("…") is not
allowed` — because its dev-only host checks have no reason to trust a domain
they've never heard of. That is Vite doing its job, not a bug to route around;
delete the file rather than adding the domain to `vite.config.ts`.

Then:

```bash
./scripts/setup.sh --site https://tasks.example.com --email you@example.com
docker compose up -d
```

On a machine that's already running, edit `SITE_URL` and `ACME_EMAIL` in `.env`
instead and `docker compose up -d` — regenerating `.env` would change the
database password and lock you out of your own data.

Caddy obtains and renews the certificate automatically. `SITE_URL` carries the
scheme on purpose: `http://` serves plain HTTP with no certificate, which is
what makes localhost work with zero edits, and `https://` turns on automatic
HTTPS. It is also the only place the hostname is written down — the frontend
bundle contains no domain at all, so the same image runs anywhere.

**Everything lives on that one hostname.** The app, the API and the auth routes
share an origin, which is why the session cookie is first-party, why there is no
CORS to configure, and why you need exactly one DNS record and one certificate.

## Bring your own Postgres or S3

The default runs both in this stack. If you already have a managed database or
an S3-compatible bucket, answer a few questions instead of hand-editing `.env`:

```bash
./scripts/setup-interactive.sh
docker compose up -d
```

It's the one place this project asks you anything at a prompt —
`scripts/setup.sh` stays script-friendly for everyone else. Say yes to
"managed Postgres" or "managed storage" for either piece and it writes the
right `DATABASE_URL` / `S3_ENDPOINT` and drops that piece from
`COMPOSE_PROFILES`, so `docker compose up -d` simply never starts a `postgres`
or `rustfs` container it doesn't need — one command either way, nothing to
remember to pass.

Three things it can't do for you, because they happen on the other side:

- **A managed Postgres instance has to be version 18 or later.** Every table's
  primary key is generated with `uuidv7()`, a Postgres 18 builtin — not an
  extension, not something the app can polyfill. Against an older instance,
  `docker compose up -d` runs `migrate` and it exits 1 the first time it tries
  to create a table; the log says so, but it's easy to mistake for a
  connection problem when everything else about the setup looks right. Check
  your provider's version before pointing `DATABASE_URL` at it.
- **SuperTokens needs its own database on the same server**, never the app's.
  The prompt tells you the one line to run once: `CREATE DATABASE supertokens;`.
- **A managed bucket is a different origin from your site**, so uploads are no
  longer same-origin the way the bundled RustFS is. Add a CORS rule on the
  bucket allowing `PUT`/`GET` from `SITE_URL`, **and allow the `content-type`
  header** (or wildcard Allowed Headers to `*`) — Content-Type is only a
  CORS "simple" header for a couple of specific values, so a real image or
  PDF still triggers a preflight, and Allowed Origins by itself lets that
  preflight fail with nothing in the browser console pointing at CORS at
  all. This is the half of the CORS rule people forget, because provider UIs
  usually put Allowed Origins and Methods front and centre and Allowed
  Headers as an afterthought.
- **`S3_ADDRESSING_STYLE` defaults to `path`**, right for most providers and
  for real AWS S3 in any region opened before September 2020. **DigitalOcean
  Spaces is the confirmed exception**: set it to `virtual`, and separately set
  `S3_REGION=us-east-1` literally, regardless of where the Space actually is —
  the real region only ever goes in `S3_ENDPOINT`. Get either wrong against
  DigitalOcean and the failure is a plain upload error with nothing in it to
  say why. `scripts/setup-interactive.sh` sets both for you automatically when
  it recognises a `digitaloceanspaces.com` endpoint.

If uploads aren't working, `./scripts/diagnose.sh` checks your actual
credentials, endpoint, bucket and (for DigitalOcean specifically) region and
addressing style the same way the app does, checks the bucket's CORS
separately from that, and — for a managed bucket — actually **uploads a real
file, reads it back, and deletes it again**, because a bucket policy that
allows listing but not writing looks completely healthy right up until
someone tries to attach a file. That's the one thing this script does that
isn't read-only, and it's the only way to answer "do uploads work" instead of
"does everything upstream of uploads look fine."

## Email is optional

With `SMTP_HOST` empty the app logs what it would have sent and carries on. That
is a supported way to run this, not a broken one:

- **every invitation also shows a copyable link**, whether or not an email went
  out. Paste it into chat and the person joins by clicking it — they don't need
  an account first. The screen says which happened, so nobody is left wondering
  whether mail was sent;
- a password-reset link appears in `docker compose logs api`.

Set the `SMTP_*` variables when you want real mail. `MAIL_FROM` has to be on a
domain your provider has verified or every message is rejected at submission.

## Telegram — notifications, and creating tasks from chat — is optional too

Leave `TELEGRAM_BOT_TOKEN` / `TELEGRAM_BOT_USERNAME` empty and the feature is
fully inert — nobody can link a Telegram chat, and "Link Telegram" on the
Account screen tells them why rather than offering a dead link. To turn it on:

1. **Make a bot.** Message [@BotFather](https://t.me/BotFather) on Telegram,
   `/newbot`, and copy the token it gives you into `TELEGRAM_BOT_TOKEN`. Put
   the bot's username (no leading `@`) into `TELEGRAM_BOT_USERNAME` — that's
   what builds the `t.me/<username>?start=...` link people tap to link.
2. **Point Telegram at your server**, once, from a terminal that can reach the
   internet:
   ```
   curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<SITE_URL>/api/telegram/webhook"
   ```
   This needs a real `https://` `SITE_URL` — Telegram's own servers have to be
   able to reach it, so it doesn't work against `http://localhost`.
3. Restart the stack (`docker compose up -d`) so `api` and `worker` pick up
   the new variables. From Account → Notification channels, "Link Telegram"
   now opens a real deep link.

Once linked, send the bot `/help` for the full list. The short version:
`/task <title>` creates a task (a second line onward becomes its
description), `/org <name>` picks which organisation new tasks go into if
you're in more than one — a plain message, without either command, creates
nothing.

A generic webhook needs no configuration at all — anyone can add one from the
same screen, with the signing secret shown once at creation.

## Your own assistant

Anyone with an account can connect an MCP client. Nothing to configure on the
server: the endpoint is on the same hostname as everything else.

**1. Make a token.** Account → Access tokens. Give it a name you'll recognise
later, and start with **read only** — you can make a write one when you
actually want the assistant changing things.

The secret is shown **once**. Only a hash is stored, so there is no screen
that could show it to you again, and a database backup is not a list of live
credentials.

**2. Point your client at it — with the Claude Code CLI, not the claude.ai
website or desktop app's "Add custom connector."** That UI only knows how to
add a server through OAuth, and this one deliberately has no OAuth server to
add — see below. The token screen has a copy button for this exact line:

```bash
claude mcp add --transport http ayeayecaptain https://tasks.example.com/mcp \
  --header "Authorization: Bearer ayc_…"
```

Then ask for things in words:

> *What's on my plate this week?*
> *What did we get done in the last seven days?*
> *Create a task for Ada to chase the yard about the travel lift, urgent.*

**What it can do.** `organisations`, `list_tasks`, `search`, `task`,
`activity`, `my_reminders` with a read token; `create_task`, `update_task` and
`comment` need a write one.

**What it can't.** A token is a person, not an integration: every call resolves
through the same permission rules as the web app, as you. It cannot see a
project nobody shared with you, cannot read anybody's private notes, cannot see
a task somebody hid, and cannot invite people. Revoking a token from the same
screen takes effect on the next call.

**"Couldn't register with ayeaye's sign-in service"?** That's the claude.ai
website or desktop app's connector UI, not the CLI — it only knows how to add
a server via OAuth, and offers "add an OAuth Client ID" as the fix. There is
no client ID to add: this server has no authorisation server at all, by
design, so a person can connect their own assistant to their own self-hosted
install without also standing up an OAuth provider. Use `claude mcp add`
above instead — it authenticates with the static Bearer token directly and
never attempts OAuth discovery.

## Back it up

**Two things, and you need both.** The database holds the work; the files
people attached live in a separate volume. A database backup alone restores
every task and comment with every attachment broken.

**1. The database — use `pg_dumpall`, not `pg_dump`.** SuperTokens keeps
identity in its own database on the same server, so a dump of the application
database alone restores every task and no way to log in.

```bash
docker compose exec -T postgres pg_dumpall -U app | gzip > db-$(date +%F).sql.gz
```

**2. The attachments**, straight out of the storage volume:

```bash
docker run --rm \
  -v ayeayecaptain_rustfs_data:/data:ro -v "$PWD:/backup" \
  alpine tar czf /backup/media-$(date +%F).tar.gz -C /data .
```

To restore into an empty stack — database first, then the files, then start:

```bash
docker compose up -d postgres
gunzip -c db-2026-08-14.sql.gz | docker compose exec -T postgres psql -U app postgres
docker run --rm \
  -v ayeayecaptain_rustfs_data:/data -v "$PWD:/backup" \
  alpine tar xzf /backup/media-2026-08-14.tar.gz -C /data
docker compose up -d
```

The volume name comes from the compose project name (`ayeayecaptain`), so it is
stable across machines.

## Update

```bash
git pull && docker compose up -d --build
```

Migrations apply themselves. A failed migration stops the rollout rather than
letting the API come up against a half-migrated schema.

**If it aborts with "missing .env", a release has added a variable your `.env`
predates.** Diff it against `.env.example` and add what's new:

```bash
diff <(grep -o '^[A-Z_]*' .env | sort) <(grep -o '^[A-Z_]*' .env.example | sort)
```

That abort is deliberate. The alternative is a container starting with an empty
value and failing somewhere much less obvious.

## When something is wrong

```bash
./scripts/diagnose.sh
```

It checks the things that have actually caused outages here — a `.env` missing
a variable a release added, the one-shot `migrate` container having failed, the
`supertokens` database not existing because `init.sql` was skipped on a
non-empty volume, `/media/*` being answered by the app instead of storage — and
prints what to do about each. It only reads; it changes nothing.

```bash
docker compose ps          # who is unhealthy
docker compose logs -f api
```

- **The site is dark but containers look healthy.** Check `docker compose logs
  caddy`. If `SITE_URL` is https and DNS doesn't yet point here, certificate
  issuance fails and Caddy serves nothing.
- **Everything aborts with "missing .env".** You skipped `cp .env.example .env`.
  That message is deliberate: the alternative is eight healthy containers
  arranged around an empty configuration.
- **`supertokens` dies once on a cold start** with a Hikari
  `PoolInitializationException`. It raced Postgres' post-init restart. Running
  `docker compose up -d` again is enough.
- **You changed `infra/postgres/init.sql` and it had no effect.** It only runs
  on an empty data directory. `docker compose down -v` first — that deletes
  your data.
- **`git pull` refuses with a conflict on `compose.override.yml`.** It's
  committed for local dev and meant to be absent on a real server (see [Put it
  on a domain](#put-it-on-a-domain)) — if you deleted it here, a later release
  that also touches that file collides with your deletion. Delete it again
  after the pull and carry on; it was never meant to exist on this machine.

## Developing

`compose.override.yml` is loaded automatically in a checkout and absent on a
server, so `docker compose up -d` is correct in both places. In dev it
bind-mounts the source, reloads Python and React on save, and adds Mailpit.

The Vite dev server sits behind Caddy on `http://localhost` exactly as nginx
does in production, so cookies, redirects and CORS behave identically in both
and there is no class of bug that only appears after a deploy.

```bash
# API tests and lint — no containers needed
cd apps/api && uv sync && uv run pytest && uv run ruff check src tests

# Frontend typecheck
cd apps/web && pnpm install && pnpm typecheck

# End-to-end, against a running stack. Creates throwaway accounts.
./scripts/e2e-organisations.sh
./scripts/e2e-projects.sh
./scripts/e2e-tasks.sh
./scripts/e2e-search.sh
./scripts/e2e-time.sh
./scripts/e2e-comments.sh
./scripts/e2e-attachments.sh
./scripts/e2e-task-files.sh
./scripts/e2e-hidden.sh
./scripts/e2e-tags.sh
./scripts/e2e-notes.sh
./scripts/e2e-reminders.sh
./scripts/e2e-dashboard.sh
./scripts/e2e-mcp.sh

# Browser tests in a real Chromium (first run: cd e2e && pnpm install && pnpm install-browsers)
./scripts/e2e-browser.sh

# After changing a model
docker compose exec api uv run alembic revision --autogenerate -m "what changed"
```

`./scripts/setup.sh --force` regenerates `.env` from scratch. It changes the
database password, so pair it with `docker compose down -v` or you'll have a
volume the new password can't open.

Interactive API docs are at **http://localhost:8000/docs** — the API's own port,
published in dev only. Use the app itself through `http://localhost`.
