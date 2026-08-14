"""The Redis pub/sub hop between API processes.

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

CHAT_CHANNEL = "chat_events"


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
            CHAT_CHANNEL,
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


async def chat_subscriber(manager: ConnectionManager) -> None:
    """Forward chat events from Redis to this process's sockets.

    Started in the lifespan and cancelled on shutdown. Reconnects on its own:
    a Redis blip must not silently leave every browser on this worker with a
    dead feed for the rest of the process's life.
    """
    while True:
        client = aioredis.from_url(settings.redis_url)
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(CHAT_CHANNEL)
            logger.info("subscribed to %s", CHAT_CHANNEL)
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
                    watch_key=event.get("watch"),
                )
        except asyncio.CancelledError:
            await client.aclose()
            raise
        except Exception as exc:
            logger.warning("chat subscriber dropped (%s), reconnecting", exc)
            await client.aclose()
            await asyncio.sleep(2)
