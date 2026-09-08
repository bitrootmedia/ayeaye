#!/usr/bin/env bash
#
# Instance administration: who is on this installation, and stopping abuse.
#
#   ./scripts/instance.sh stats
#   ./scripts/instance.sh users [--limit N] [--offset N] [--oldest]
#   ./scripts/instance.sh orgs  [--limit N] [--offset N] [--oldest]
#   ./scripts/instance.sh suspend <email|id> [--reason "..."]
#   ./scripts/instance.sh restore <email|id>
#
# There is deliberately no screen for this. This product has no staff tier —
# `users` has no `role` or `is_staff` column and a test fails the build if
# one appears — so instance administration is an operator capability, held
# by whoever can reach the box, exactly like scripts/reset-mfa.sh. Shell
# access is the credential, and a better one than a login: whoever has it
# already has Postgres and .env, so this grants no new power. A web
# backoffice would be the highest-value account on the instance, guarding
# data that organisation admins deliberately cannot reach.
#
# Metadata only. Counts, dates and names — never a task title, a comment, a
# private note or a file. See services/instance.py for why.
#
# `suspend` blocks sign-in and revokes every live session. It is
# non-destructive and reversible: their data is untouched and `restore`
# puts them straight back.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! docker compose ps --format '{{.Service}}' 2>/dev/null | grep -qx api; then
  echo "api isn't running — bring the stack up first (docker compose up -d)" >&2
  exit 1
fi

# Same shape as reset-mfa.sh and diagnose.sh's Storage section: exec into the
# api container and call the app's own code, rather than reimplementing any
# of it in bash. `-T` because there is no interactive prompt to keep.
docker compose exec -T -e PYTHONPATH=/app/src api \
  uv run python -m app.cli.instance "$@"
