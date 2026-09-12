"""Claiming a key, so a retried write repeats the answer and not the work.

Read `models/idempotency.py` for why this is a table rather than a column.
Three rules, and the second is the one that is easy to get subtly wrong.

1. **Claim before working, never after.** The claim is the `INSERT`, and it
   commits on its own before the real work starts. Recording the key
   *afterwards* would mean two concurrent retries both do the work and only
   then discover one of them was a duplicate — by which point there are two
   tasks and the constraint can only report the fact, not prevent it.

2. **A claim nobody finished is not the same as a claim in flight, and the
   only thing that tells them apart is age.** A process that dies between
   claiming and recording leaves `entity_id` NULL forever; refusing that key
   for all time would punish the caller for our crash, and honouring it
   immediately would let a genuine concurrent retry through. So a claim
   younger than `STALE_AFTER` is reported as in progress (the caller waits
   and asks again, which is what a retry already was), and an older one is
   taken over.

3. **The same key for a different tool is an error, not a match.** Answering
   `comment` with the id of a task created under the same key would be a
   confidently wrong answer, which is worse than a refusal.

Nothing here is MCP-specific; it is written for whatever else wants it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency import MAX_KEY_LENGTH, IdempotencyKey

# Long enough that a slow create isn't mistaken for a dead one, short enough
# that a crash doesn't strand a key for the rest of the day.
STALE_AFTER = timedelta(minutes=5)


class InProgress(Exception):
    """Somebody else holds this key and hasn't finished. Not an error in the
    caller's request — the honest answer is "ask again in a moment", and the
    alternative (doing the work anyway) is the duplicate this exists to
    prevent."""


class KeyReused(Exception):
    """This key was already used for a different operation."""


@dataclass
class Claim:
    """A key this caller now owns. `existing_id` is set when the work was
    already done under this key, in which case the caller should re-render
    that answer and do nothing else."""

    id: uuid.UUID
    existing_id: uuid.UUID | None


def clean_key(key: str) -> str:
    return (key or "").strip()[:MAX_KEY_LENGTH]


async def claim(db: AsyncSession, user_id: uuid.UUID, key: str, tool: str) -> Claim:
    """Take the key, or report what was done under it last time.

    Raises `InProgress` if a live claim is outstanding, `KeyReused` if the
    key belongs to a different tool.
    """
    key = clean_key(key)
    # `ON CONFLICT DO NOTHING ... RETURNING` returns a row only when the
    # insert actually landed, so this doubles as the claim and the test of
    # whether we won — the same idempotent-apply idiom `tags.apply` and
    # `sheets` already use, read for its RETURNING rather than ignored.
    stmt = (
        insert(IdempotencyKey)
        .values(user_id=user_id, key=key, tool=tool)
        .on_conflict_do_nothing(index_elements=["user_id", "key"])
        .returning(IdempotencyKey.id)
    )
    won = (await db.execute(stmt)).scalar_one_or_none()
    if won is not None:
        await db.commit()
        return Claim(id=won, existing_id=None)

    existing = (
        await db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id, IdempotencyKey.key == key
            )
        )
    ).scalar_one()
    if existing.tool != tool:
        raise KeyReused(
            f"that idempotency key was already used for {existing.tool!r}, not {tool!r}"
        )
    if existing.entity_id is not None:
        return Claim(id=existing.id, existing_id=existing.entity_id)

    # Claimed, unfinished. Old enough to be a corpse rather than a
    # neighbour? Take it over — conditionally, so two callers racing to do
    # exactly that still produce one winner.
    cutoff = datetime.now(UTC) - STALE_AFTER
    taken = (
        await db.execute(
            update(IdempotencyKey)
            .where(
                IdempotencyKey.id == existing.id,
                IdempotencyKey.entity_id.is_(None),
                IdempotencyKey.created_at < cutoff,
            )
            .values(created_at=datetime.now(UTC))
            .returning(IdempotencyKey.id)
        )
    ).scalar_one_or_none()
    if taken is None:
        await db.rollback()
        raise InProgress
    await db.commit()
    return Claim(id=taken, existing_id=None)


async def release(db: AsyncSession, held: Claim) -> None:
    """Give a claim back because the work raised and nothing was made.

    Without this, a caller who sent a bad argument, read the refusal, fixed
    it and retried with the same key would be told their own failed call was
    still running — for `STALE_AFTER`, over a request that already finished.
    Scoped to `entity_id IS NULL` so it can never delete a finished claim,
    however it gets called.
    """
    await db.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.id == held.id, IdempotencyKey.entity_id.is_(None)
        )
    )
    await db.commit()


async def record(db: AsyncSession, held: Claim, entity_id: uuid.UUID) -> None:
    """Finish a claim by naming what it produced. Called after the work has
    committed — a key pointing at a row that was rolled back would answer the
    next retry with an id that isn't there."""
    await db.execute(
        update(IdempotencyKey).where(IdempotencyKey.id == held.id).values(entity_id=entity_id)
    )
    await db.commit()


__all__ = [
    "STALE_AFTER",
    "Claim",
    "InProgress",
    "KeyReused",
    "claim",
    "clean_key",
    "record",
    "release",
]
