"""Recording who signed in, from where.

One rule: **this must never fail a sign-in.** A login event is a side effect
of something that already succeeded — SuperTokens has already issued the
session by the time `record()` runs — so a database hiccup here must not
turn a working sign-in into a 500. Same reasoning as `notifications.notify()`
never raising.

No UI reads this yet. It exists so the data is there when one is built,
rather than starting the clock on that screen the day someone finally asks
for it.
"""

import logging

from app.db import SessionLocal
from app.models import LoginEvent

logger = logging.getLogger("app.services.login_history")


async def record(
    *, supertokens_user_id: str, ip_address: str | None, user_agent: str | None
) -> None:
    try:
        async with SessionLocal() as db:
            db.add(
                LoginEvent(
                    supertokens_user_id=supertokens_user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )
            await db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("could not record login for %s: %s", supertokens_user_id, exc)


__all__ = ["record"]
