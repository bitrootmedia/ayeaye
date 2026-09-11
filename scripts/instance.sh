#!/usr/bin/env bash
#
# Instance administration: who is on this installation, and stopping abuse.
#
#   ./scripts/instance.sh stats
#   ./scripts/instance.sh users [--limit N] [--offset N] [--oldest]
#   ./scripts/instance.sh orgs  [--limit N] [--offset N] [--oldest]
#   ./scripts/instance.sh suspend <email|id> [--reason "..."]
#   ./scripts/instance.sh restore <email|id>
#   ./scripts/instance.sh suspend-org <slug|id> [--reason "..."]
#   ./scripts/instance.sh restore-org <slug|id>
#   ./scripts/instance.sh admins
#   ./scripts/instance.sh grant-admin <email|id> [--note "..."]
#   ./scripts/instance.sh revoke-admin <email|id>
#
# There is a screen for this now — /instance in the web app, for anybody
# holding an instance_admins row — and this shell tool is the other front
# door onto the same code. What stayed shell-only is the part that matters:
# GRANTING THE ROW. A panel that could appoint its own successors would turn
# one stolen session into a permanent foothold, so grant-admin needs access
# to this box, which is a credential the web cannot phish.
#
# This product still has no staff tier: `users` has no `role` or `is_staff`
# column and a test fails the build if one appears. An instance admin has no
# extra power inside any organisation either — services/access.py never
# learns the table exists, so a hidden task stays hidden from them and a
# private note stays private.
#
# Metadata only. Counts, dates and names — never a task title, a comment, a
# private note or a file. See services/instance.py for why.
#
# `suspend` blocks sign-in and revokes every live session. `suspend-org`
# locks an organisation for everybody in it. Both are non-destructive and
# reversible: no data is touched and `restore`/`restore-org` put things
# straight back.
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
