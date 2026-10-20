""" "Still working on this?" — the sweep that asks, and the one that pauses.

Every minute, unlike the hourly sweeps beside it: a question is due at a
random minute and its deadline is fifteen to thirty minutes later, so an
hourly tick would turn "fifteen minutes" into "up to seventy-five". Each tick
is two indexed reads over running timers — one row per person at most — and
everything it writes is claimed first, so a slow or doubled tick is harmless.
See `services/check_ins.py`.
"""

import logging
from datetime import UTC, datetime

from app.db import SessionLocal
from app.services import check_ins as check_ins_service
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.check_ins")


@broker.task(schedule=[{"cron": "* * * * *"}])
async def sweep_timer_check_ins() -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        # Expire before asking: a timer paused this tick must not also be
        # asked a fresh question in the same breath.
        paused = await check_ins_service.expire_due(db, now=now)
        asked = await check_ins_service.ask_due(db, now=now)
    if paused or asked:
        logger.info("check-ins: asked %d, paused %d", asked, paused)
