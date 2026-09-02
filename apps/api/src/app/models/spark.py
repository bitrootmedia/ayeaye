"""Sparks: quick capture for a stray idea, link, or note-to-self.

    users ──► sparks

Deliberately not the notepad (`personal_note.py`) and not a task note
(`note.py`) — this is the list-shaped version of the same "only the author,
ever" idea, but cross-organisation rather than scoped to one: the whole
point is catching a thought in the fewest possible keystrokes, regardless of
which organisation happens to be open when it strikes. No title, unlike the
notepad — one field, because a second field to fill in is friction a capture
tool exists specifically to avoid.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MAX_BODY_LENGTH = 2000


class Spark(Base):
    __tablename__ = "sparks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    # CASCADE, the same as every other personal-record user_id in this schema.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
