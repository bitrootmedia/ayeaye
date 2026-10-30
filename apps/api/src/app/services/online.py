"""Who's online: somebody with a live socket open, in any tab or app.

(`services/presence.py` is out-of-office and announcements — "presence" in
the dashboard sense. This is the green dot.)

Uvicorn runs several workers and each holds only its own sockets, so no one
process can answer "is she connected?". Redis can, if every worker says what
it holds:

* `online:<user>` is a sorted set of **worker ids**, scored by when that
  worker's claim expires. A worker adds itself when a person's first socket
  on it connects, refreshes every `HEARTBEAT` seconds while they stay, and
  removes itself when their last socket on it closes.
* Online is "any claim that hasn't expired". A worker that dies mid-session
  can't remove its claim, so the claim expires on its own `TTL` later — a
  crashed process costs a minute of a stale green dot, not a permanent one.
* `last_seen:<user>` is stamped on every heartbeat and on the way out, so an
  offline person still shows when they were last around.

**Never raises.** Like realtime itself, this is a nicety on top of work that
already happened: Redis being down shows everybody as offline, which is
wrong but harmless, and must not fail the request that asked.
"""

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger("app.online")

WORKER_ID = uuid.uuid4().hex
HEARTBEAT = 20
TTL = 60


def _online_key(user_id: str) -> str:
    return f"online:{user_id}"


def _seen_key(user_id: str) -> str:
    return f"last_seen:{user_id}"


async def _claim(client, user_ids: list[str]) -> None:
    now = time.time()
    pipe = client.pipeline()
    for uid in user_ids:
        pipe.zadd(_online_key(uid), {WORKER_ID: now + TTL})
        pipe.expire(_online_key(uid), TTL * 2)
        pipe.set(_seen_key(uid), str(now))
    await pipe.execute()


async def came_online(user_id: str) -> None:
    client = aioredis.from_url(settings.redis_url)
    try:
        await _claim(client, [user_id])
    except Exception as exc:
        logger.warning("could not mark %s online: %s", user_id, exc)
    finally:
        await client.aclose()


async def went_offline(user_id: str) -> None:
    """This worker no longer holds a socket for them. Another worker may."""
    client = aioredis.from_url(settings.redis_url)
    try:
        pipe = client.pipeline()
        pipe.zrem(_online_key(user_id), WORKER_ID)
        pipe.set(_seen_key(user_id), str(time.time()))
        await pipe.execute()
    except Exception as exc:
        logger.warning("could not mark %s offline: %s", user_id, exc)
    finally:
        await client.aclose()


async def heartbeat(manager) -> None:
    """Refresh this worker's claims for everyone it's holding. Started in the
    lifespan beside the realtime subscriber, cancelled with it."""
    while True:
        await asyncio.sleep(HEARTBEAT)
        user_ids = manager.user_ids()
        if not user_ids:
            continue
        client = aioredis.from_url(settings.redis_url)
        try:
            await _claim(client, user_ids)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("presence heartbeat failed: %s", exc)
        finally:
            await client.aclose()


async def status(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[bool, datetime | None]]:
    """`{user: (online, last_seen)}` for each of these people, in one round
    trip. Expired claims are pruned on the way, so a dead worker's entry
    stops counting the moment it lapses rather than whenever it's next
    touched."""
    if not user_ids:
        return {}
    client = aioredis.from_url(settings.redis_url)
    now = time.time()
    try:
        pipe = client.pipeline()
        for uid in user_ids:
            pipe.zremrangebyscore(_online_key(str(uid)), "-inf", now)
            pipe.zcard(_online_key(str(uid)))
            pipe.get(_seen_key(str(uid)))
        raw = await pipe.execute()
    except Exception as exc:
        logger.warning("could not read presence: %s", exc)
        return {uid: (False, None) for uid in user_ids}
    finally:
        await client.aclose()

    out: dict[uuid.UUID, tuple[bool, datetime | None]] = {}
    for i, uid in enumerate(user_ids):
        count, seen = raw[i * 3 + 1], raw[i * 3 + 2]
        last_seen = datetime.fromtimestamp(float(seen), tz=UTC) if seen else None
        out[uid] = (bool(count), last_seen)
    return out
