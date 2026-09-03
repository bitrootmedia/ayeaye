---
name: self-host-troubleshooting
description: How ayeayecaptain's self-hosting bar is held together — setup.sh/diagnose.sh reasoning, bringing your own Postgres or S3, and real deployment incidents (compose.override.yml on a public box, DigitalOcean Spaces addressing, Postgres version, CORS gaps). Use when troubleshooting a self-hosted or production deployment of this project, not during ordinary feature work.
---

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
"UUIDv7 primary keys" in CLAUDE.md — and there's no polyfill for it. Against
an older instance the failure isn't at connection time: `migrate` connects
fine, logs its two boilerplate INFO lines, and then exits 1 the moment the
first `CREATE TABLE` tries to call a function that doesn't exist. That reads
exactly like a connection problem and isn't one. README's "Bring your own
Postgres or S3" says so now; `diagnose.sh` can't check a version it has no
client to ask for, so the `migrate exited $code` hard-failure — already
there — is the actual signal, and it points at `docker compose logs migrate`.

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

## A Caddy restart is not always a Caddy reload

`docker compose restart caddy` is not reliably enough to pick up an edited
`Caddyfile` on a real deployment — confirmed on a real one, not assumed. A
self-hoster's connector to Claude.ai/ChatGPT kept failing with "Couldn't
register with …'s sign-in service" — the exact symptom the MCP/OAuth
section's own incident writeup describes — even after the Caddyfile on disk
was confirmed correct (`docker compose exec caddy cat /etc/caddy/Caddyfile`
matched the repo byte for byte) and Caddy had already been `restart`ed. The
API itself was also confirmed innocent: hitting it directly inside its own
container (`docker compose exec api python3 -c "urllib.request.urlopen(...)"`,
bypassing Caddy entirely) returned the correct
`/.well-known/oauth-protected-resource/mcp` document every time. Only
`docker compose up -d --force-recreate caddy` — a full container recreate,
not a stop/start of the same one — actually made the public domain agree
with what the container's own filesystem already said. Prefer
`--force-recreate` over `restart` for Caddy specifically when a Caddyfile
edit doesn't seem to be taking effect; `diagnose.sh` doesn't catch this
today, because everything it can observe from outside (the file on disk, the
API's own response) looked correct the whole time — the gap was specifically
between "Caddy has the right config on disk" and "the running Caddy process
is using it."

## An orphan `mailpit` container on production is a real signal

Not noise to `--remove-orphans` away without looking. `docker compose up`
printed `Found orphan containers (mailpit-1)` on a self-hoster's production
box during the investigation above. Mailpit only exists in
`compose.override.yml` — the dev-only file — so its container having ever
run there means that file was present and active on a public deployment at
some point, which is the exact trap the "Bringing your own Postgres or S3"
section above already warns about (a published Postgres port, Vite's dev
server, RustFS/pgweb consoles, none of which belong on a public box).
Confirming `compose.override.yml` is gone now doesn't answer *when* it was
removed or what was reachable while it existed — worth an explicit look, not
an assumption, on any host where this shows up.
