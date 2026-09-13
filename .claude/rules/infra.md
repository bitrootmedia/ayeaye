---
paths:
  - "docker-compose.yml"
  - "compose.override.yml"
  - "infra/**"
  - "apps/*/Dockerfile*"
  - "apps/api/alembic/**"
  - ".env.example"
  - "scripts/setup*.sh"
  - "scripts/diagnose.sh"
---

# Compose, images, Caddy, migrations and backups

## Compose, images and the database

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
- **The API images are built from `uv.lock`, and `uv run` must carry
  `--no-sync`.** Both were wrong at once: the Dockerfiles copied
  `pyproject.toml` without the lockfile (so `uv sync` resolved fresh at build
  time — 22 packages drifted, `nh3` and `cryptography` among them), and the
  CMD's bare `uv run` re-synced at *container start*, pulling the dev
  dependencies back into an image built `--no-dev` and leaving a production
  container unable to boot without reaching PyPI. `apps/web` had always got
  this right. The `self-host-troubleshooting` skill has the detail and the
  two commands that check it hasn't come back; the short version is that
  `docker run --network none ayeayecaptain-api` must reach "Uvicorn running".
- **`init.sql` runs only on an empty data directory.** Change it after the
  first boot and it is silently skipped; `docker compose down -v` first.
- **Backups must be `pg_dumpall`.** SuperTokens keeps identity in its own
  database on the same server; a `pg_dump` of the app database restores every
  task and no way to log in.

Two more real deployment incidents — a Caddy restart that didn't actually
reload, and an orphaned dev container on a production host — are documented
in the `self-host-troubleshooting` skill rather than here, alongside the
rest of the self-hosting bar; load it when troubleshooting a self-hosted or
production deployment.
