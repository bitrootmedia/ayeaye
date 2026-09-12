"""Idempotency keys: making a retried write safe to retry.

Agents retry. A timeout on `create_task` leaves the caller with no way to
know whether the task exists, and the move that looks safest — call it
again — is the one that files a duplicate. A client-supplied key turns that
retry into a repeat of the *answer* rather than a repeat of the *work*.

One row per (person, key). Deliberately **not** a column on `tasks` or
`messages`: a key is a fact about a request, not about the thing the request
made, and putting it on the row would mean a new nullable column and a new
partial unique index for every kind of write that ever wants one. This table
costs one lookup and covers all of them.

The key is scoped to the person, not to the installation — two people using
the same obvious string ("todays-standup") must not collide, and a key is
only ever presented by the caller who minted it.

`tool` is recorded and checked rather than just stored: reusing one key for
two different operations is a caller bug, and answering the second one with
the first one's id would be a confidently wrong answer rather than an error.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MAX_KEY_LENGTH = 200


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        # The whole mechanism. Two concurrent retries both try to insert;
        # exactly one wins, and the loser reads back what the winner did.
        UniqueConstraint("user_id", "key", name="uq_idempotency_keys_user_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(MAX_KEY_LENGTH), nullable=False)
    tool: Mapped[str] = mapped_column(String(80), nullable=False)

    # NULL means claimed but not finished: either the work is in flight right
    # now, or the process died holding the claim. `services/idempotency.py`
    # tells those apart by age and nothing else can — which is why this is
    # nullable rather than written at the same moment as the claim.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
