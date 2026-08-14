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
  priority, a list view, and a full history of every change.
- **Files on tasks.** Drop one on the task or post it in a comment; either way
  it lands in the same Files panel, with thumbnails for images that open full
  size in place.
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
here. Then:

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
