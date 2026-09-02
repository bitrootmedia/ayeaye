"""Sparks: quick capture, cross-organisation, yours alone.

The same absence-of-a-branch discipline `services/notes.py` and
`services/personal_notes.py` already hold for private data — every
statement here filters on `user_id == the caller`, full stop. There is no
admin override and there must not be one.

Unlike the notepad, a spark carries no `organisation_id` and no title: it
exists purely to be faster to write than either of those, so the whole
record is one field.
"""

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Spark, User
from app.models.spark import MAX_BODY_LENGTH


def mine_stmt(*, user_id: uuid.UUID) -> Select:
    """Newest first — a capture tool is read back like a stack, not a log
    somebody scrolls to the bottom of."""
    return select(Spark).where(Spark.user_id == user_id).order_by(Spark.created_at.desc())


def _clean(body: str) -> str:
    body = (body or "").strip()[:MAX_BODY_LENGTH]
    if not body:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a spark needs something in it",
        )
    return body


async def create(db: AsyncSession, user: User, *, body: str) -> Spark:
    row = Spark(user_id=user.id, body=_clean(body))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_or_404(db: AsyncSession, spark_id: uuid.UUID, user: User) -> Spark:
    """Yours, or it doesn't exist — not 403. Somebody else's spark is not
    something you are being told about, the same reasoning
    `services/notes.py`'s own `get_or_404` uses."""
    row = (
        await db.execute(select(Spark).where(Spark.id == spark_id, Spark.user_id == user.id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="not found")
    return row


async def update_one(db: AsyncSession, spark: Spark, *, body: str) -> Spark:
    spark.body = _clean(body)
    await db.commit()
    await db.refresh(spark)
    return spark


async def remove(db: AsyncSession, spark: Spark) -> None:
    await db.delete(spark)
    await db.commit()
