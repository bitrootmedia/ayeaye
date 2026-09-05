"""Marking the accounts that predate email verification as verified.

Runs once, at startup, and then finds nothing forever. It exists because
turning verification on retroactively would otherwise lock out every account
that already existed — see migration 0040 for why the flag is set there and
drained here rather than done in one place.

**Claimed, not read-then-written.** The same `UPDATE … WHERE … RETURNING`
shape `reminders.claim` uses, and for the same reason: uvicorn runs several
workers and they all start at once. Select-then-update would have every
worker verifying the same accounts, which is harmless but noisy; claiming
means each row is somebody's exactly once.

**Never fails startup.** A SuperTokens core that isn't up yet, an account it
has never heard of, a network blip — none of that is a reason for the API to
refuse to boot. Anything unclaimed simply stays flagged and is picked up by
the next start, which is the useful property of doing this with a flag
rather than a one-shot script somebody has to remember to run.
"""

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from supertokens_python.recipe.emailverification.asyncio import (
    create_email_verification_token,
    verify_email_using_token,
)
from supertokens_python.recipe.emailverification.interfaces import (
    CreateEmailVerificationTokenEmailAlreadyVerifiedError,
)

from app.models import User

logger = logging.getLogger("app.verification")

#: Small on purpose. This is startup work competing with the first real
#: requests, and there is no deadline — whatever is left waits for the next
#: boot, or for the loop below to come round again.
BATCH = 50


async def grandfather_existing_accounts(db: AsyncSession) -> int:
    """Mark every pre-verification account as verified. Returns how many."""
    done = 0
    while True:
        claimed = (
            await db.execute(
                update(User)
                .where(
                    User.id.in_(
                        select(User.id).where(User.grandfather_verification).limit(BATCH)
                    )
                )
                .values(grandfather_verification=False)
                .returning(User.supertokens_user_id, User.email)
            )
        ).all()
        await db.commit()
        if not claimed:
            return done

        for supertokens_user_id, email in claimed:
            if not email:
                continue
            try:
                await _mark_verified(supertokens_user_id, email)
                done += 1
            except Exception as exc:
                # Logged, not retried here. The row has already been
                # unflagged, so a permanently broken account doesn't spin
                # this loop forever — and the consequence is one person
                # seeing a "confirm your address" screen, not a lockout with
                # no way through.
                logger.warning("could not grandfather %s: %s", email, exc)
        logger.info("grandfathered %d account(s) as verified", len(claimed))


async def _mark_verified(supertokens_user_id: str, email: str) -> None:
    """Say "this address is verified" the only way the SDK offers.

    There is no set-verified call: you mint a token and immediately spend it.
    That reads oddly and is the documented approach — the token never leaves
    this process, so nothing is emailed and nothing is exposed.
    """
    token = await create_email_verification_token(
        tenant_id="public", recipe_user_id=_recipe_user_id(supertokens_user_id), email=email
    )
    if isinstance(token, CreateEmailVerificationTokenEmailAlreadyVerifiedError):
        return
    await verify_email_using_token(tenant_id="public", token=token.token)


def _recipe_user_id(supertokens_user_id: str):
    # Imported here rather than at module scope: `supertokens_python.types`
    # pulls in the SDK's recipe registry, and importing that before
    # `init()` has run is a different error entirely from anything this
    # module is about.
    from supertokens_python.types import RecipeUserId

    return RecipeUserId(supertokens_user_id)
