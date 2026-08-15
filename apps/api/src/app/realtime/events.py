"""The Redis pub/sub hop between API processes.

One channel for everything realtime, not one per feature: every API process
already holds a subscriber, and a second connection per event type buys
nothing but another thing to reconnect. Consumers branch on `type`.

Uvicorn runs several workers in production and each holds only its own
sockets, so a message posted on worker 1 has to reach a browser connected to
worker 3. Redis is the only thing the processes share at runtime.

**Events carry no content — just "conversation X moved".** The client refetches
over HTTP. That keeps exactly one authorisation path for message bodies
instead of two, and means nothing sensitive travels through a channel that has
no idea who may read it. When attachments arrive, it also means their
presigned URLs are minted fresh at read time rather than going stale in
transit.
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.core.config import settings
from app.realtime.connections import ConnectionManager

logger = logging.getLogger("app.realtime")

EVENTS_CHANNEL = "realtime_events"


async def publish_message(
    *, conversation_id: str, message_id: str, user_ids: list[str], anchor: dict
) -> None:
    """Announce that a conversation has moved.

    `user_ids` includes the sender, so their own other tabs update too — and
    it is an explicit list rather than "everyone who can see the anchor",
    because resolving that in reverse is expensive and this is a notification
    hint, not the access check.
    """
    client = aioredis.from_url(settings.redis_url)
    try:
        await client.publish(
            EVENTS_CHANNEL,
            json.dumps(
                {
                    "type": "message",
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "user_ids": user_ids,
                    "anchor": anchor,
                    # What a client must be watching to receive this even
                    # without a stake in it.
                    "watch": f"{anchor['kind']}:{anchor['id']}",
                }
            ),
        )
    except Exception as exc:
        # Realtime is a nicety layered on top of a message that is already
        # committed. Losing the ping costs a refresh, not the comment.
        logger.warning("could not publish a chat event: %s", exc)
    finally:
        await client.aclose()


async def publish_task_changed(*, task_id: str, organisation_id: str, change: str) -> None:
    """Announce that a task moved — a status, a file, a date, anything.

    **The audience is whoever has it on screen**, not whoever has a stake in
    it. Those are the two registries in `connections.py`, and conflating them
    was a bug once already: a read-only colleague looking at the task has
    nothing worth *notifying* them about, but their screen must still update.
    So `user_ids` is deliberately empty here and the watch key does the work.

    Like every other event on this channel it carries **no content** — only
    which task, and what kind of change for the log. The client refetches, so
    a viewer whose access was revoked a moment ago gets a 404 from that
    refetch rather than a payload they should never have seen. That is also
    what makes "the owner hid this task" arrive correctly: the watcher's
    refetch 404s and their screen says so.
    """
    client = aioredis.from_url(settings.redis_url)
    try:
        await client.publish(
            EVENTS_CHANNEL,
            json.dumps(
                {
                    "type": "task",
                    "task_id": task_id,
                    "organisation_id": organisation_id,
                    "change": change,
                    "user_ids": [],
                    # Two audiences: the task's own screen, and any board in
                    # that organisation the task might be sitting on.
                    "watch": [f"task:{task_id}", f"org:{organisation_id}"],
                }
            ),
        )
    except Exception as exc:
        # The change is already committed. Losing the ping costs a refresh.
        logger.warning("could not publish a task event: %s", exc)
    finally:
        await client.aclose()


async def realtime_subscriber(manager: ConnectionManager) -> None:
    """Forward events from Redis to this process's sockets.

    Started in the lifespan and cancelled on shutdown. Reconnects on its own:
    a Redis blip must not silently leave every browser on this worker with a
    dead feed for the rest of the process's life.
    """
    while True:
        client = aioredis.from_url(settings.redis_url)
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(EVENTS_CHANNEL)
            logger.info("subscribed to %s", EVENTS_CHANNEL)
            async for raw in pubsub.listen():
                if raw.get("type") != "message":
                    continue
                try:
                    event = json.loads(raw["data"])
                except (TypeError, ValueError):
                    continue
                await manager.dispatch(
                    event,
                    user_ids=event.get("user_ids", []),
                    watch_keys=event.get("watch"),
                )
        except asyncio.CancelledError:
            await client.aclose()
            raise
        except Exception as exc:
            logger.warning("realtime subscriber dropped (%s), reconnecting", exc)
            await client.aclose()
            await asyncio.sleep(2)
