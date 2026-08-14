#!/usr/bin/env bash
#
# Browser tests, in a real Chromium, against a running stack.
#
#   docker compose up -d && ./scripts/e2e-browser.sh
#   ./scripts/e2e-browser.sh screenshots     # just re-photograph the product
#   ./scripts/e2e-browser.sh --headed        # watch it happen
#
# What these cover that the bash suites can't: what a *second person* actually
# sees on screen. The API returning 404 and the UI rendering an absent project
# are different claims, and only one of them is what a user experiences.
#
# Screenshots land in e2e/artifacts/shots/ — that's how the UI gets reviewed
# without a person sitting in front of it.
#
# First run only:
#   cd e2e && pnpm install && pnpm install-browsers
set -euo pipefail

cd "$(dirname "$0")/.."

if ! curl -sf -o /dev/null http://localhost/health; then
  echo "The stack isn't up. Run: docker compose up -d" >&2
  exit 1
fi

if [ ! -d e2e/node_modules ]; then
  echo "Installing browser test dependencies (first run only)…"
  (cd e2e && pnpm install && pnpm exec playwright install chromium)
fi

cd e2e
exec pnpm exec playwright test "$@"
