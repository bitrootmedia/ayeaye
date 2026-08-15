"""Startup/shutdown wiring for the API process.

Everything that needs a connection is started here rather than at import time,
so importing the app is side-effect free and testable without Postgres or Redis
running.
"""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.mcp.server import mcp
from app.realtime.connections import manager
from app.realtime.events import realtime_subscriber
from app.storage import s3
from app.tasks import broker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await broker.startup()  # connect so `.kiq()` can enqueue from a request
    # Storage being down is a reason attachments don't work, not a reason the
    # API refuses to boot — ensure_bucket logs and carries on.
    await s3.ensure_bucket()
    # Every uvicorn worker holds only its own sockets, so each one subscribes
    # and forwards to whichever browsers it happens to be holding.
    subscriber = asyncio.create_task(realtime_subscriber(manager))
    try:
        # The MCP transport runs its own task group, and it has to be entered
        # here rather than per request: a session manager started inside a
        # handler dies with that handler's task.
        async with mcp.session_manager.run():
            yield
    finally:
        subscriber.cancel()
        # Let it observe the cancellation before the broker goes away.
        with contextlib.suppress(asyncio.CancelledError):
            await subscriber
        await broker.shutdown()
