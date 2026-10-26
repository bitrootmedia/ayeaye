"""The embedding sweep: keeps recall's vectors in step with the text.

Every minute, because a fact written now should be findable by meaning
within the minute, and the work is a no-op when nothing changed — one
statement per kind finds nothing stale and the run ends. Also kicked straight
after a fact is written (`api/routers/facts.py`, the `remember` MCP tool), so
an assistant that writes one can usually recall it seconds later.

All the reasoning is in `services/embeddings.py`. What lives here is only the
schedule, and the decision that a failing endpoint is a log line: the sources
stay stale, the next run tries again, and recall meanwhile answers from text.
"""

import logging

from app.db import SessionLocal
from app.services import embeddings as embeddings_service
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.embeddings")


@broker.task(schedule=[{"cron": "* * * * *"}])
async def sweep_embeddings() -> None:
    async with SessionLocal() as db:
        try:
            done = await embeddings_service.sweep(db)
        except Exception:
            logger.warning("embedding sweep failed; will retry next run", exc_info=True)
            return
    if done:
        logger.info("embedding sweep indexed %d source(s)", done)
