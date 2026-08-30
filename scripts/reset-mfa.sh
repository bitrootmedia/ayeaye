#!/usr/bin/env bash
#
# Clear an account's two-factor auth from the server, bypassing the app
# entirely.
#
#   ./scripts/reset-mfa.sh someone@example.com
#
# The last-resort recovery path. An org admin can already reset a member's
# 2FA from the People roster in the app — this exists for the one case that
# can't reach: a lone owner locked out of their own account, with nobody who
# can sign in to help them.
#
# Removes every TOTP device and every backup code for the account. They'll
# be asked to set up two-factor auth again next time it's required, exactly
# like an in-app admin reset.
set -euo pipefail
cd "$(dirname "$0")/.."

EMAIL="${1:-}"
if [ -z "$EMAIL" ]; then
  echo "usage: $0 <email>" >&2
  exit 1
fi

if ! docker compose ps --format '{{.Service}}' 2>/dev/null | grep -qx api; then
  echo "api isn't running — bring the stack up first (docker compose up -d)" >&2
  exit 1
fi

# Same shape diagnose.sh's Storage section uses: exec into the api container
# and call the app's own code directly, rather than reimplementing the
# lookup in bash. Resolves the local user row by email (the same
# lower-cased column services/users.py already keys off), then reuses
# services.mfa.reset_totp — the identical function the in-app admin action
# calls — so there is exactly one reset path, not a second one that could
# drift from it. Pure database work, unlike most of diagnose.sh's checks:
# TOTP devices and backup codes are hand-rolled in this app's own tables
# (see services/mfa.py for why), not held by SuperTokens' core, so there is
# no SuperTokens call to make here at all.
docker compose exec -T -e PYTHONPATH=/app/src api uv run python -c "
import asyncio
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.services import mfa as mfa_service

email = '$EMAIL'.strip().lower()

async def main():
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            print(f'no account found for {email}', file=sys.stderr)
            raise SystemExit(1)
        await mfa_service.reset_totp(db, user)
        print(f'cleared two-factor auth for {email}')

asyncio.run(main())
"
