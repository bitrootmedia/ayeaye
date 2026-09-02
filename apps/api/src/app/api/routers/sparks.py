"""Sparks — quick capture, cross-organisation like the inbox and reminders.

Thin: the one rule ("only the author, ever") lives in `services/sparks.py`.
There is no organisation dependency here at all — `CurrentUser` is the only
gate, because there is no sharing and nothing else to check.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.models.spark import MAX_BODY_LENGTH
from app.services import sparks as sparks_service

router = APIRouter(prefix="/sparks", tags=["sparks"])


class SparkIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)


class SparkOut(BaseModel):
    id: str
    body: str
    created_at: datetime
    updated_at: datetime


def _out(spark) -> SparkOut:
    return SparkOut(
        id=str(spark.id),
        body=spark.body,
        created_at=spark.created_at,
        updated_at=spark.updated_at,
    )


@router.get("", response_model=list[SparkOut])
async def list_sparks(user: CurrentUser, db: DbSession):
    """Yours alone, newest first. Unpaged, like the notepad — a personal
    capture list was never fetched a page at a time to begin with."""
    rows = (await db.execute(sparks_service.mine_stmt(user_id=user.id))).scalars().all()
    return [_out(s) for s in rows]


@router.post("", response_model=SparkOut, status_code=status.HTTP_201_CREATED)
async def create_spark(body: SparkIn, user: CurrentUser, db: DbSession):
    spark = await sparks_service.create(db, user, body=body.body)
    return _out(spark)


@router.patch("/{spark_id}", response_model=SparkOut)
async def update_spark(spark_id: uuid.UUID, body: SparkIn, user: CurrentUser, db: DbSession):
    spark = await sparks_service.get_or_404(db, spark_id, user)
    spark = await sparks_service.update_one(db, spark, body=body.body)
    return _out(spark)


@router.delete("/{spark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spark(spark_id: uuid.UUID, user: CurrentUser, db: DbSession):
    spark = await sparks_service.get_or_404(db, spark_id, user)
    await sparks_service.remove(db, spark)
