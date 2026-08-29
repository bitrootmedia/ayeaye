"""The notepad: free-form personal notes, scoped to an organisation.

    organisations ──► personal_notes ◄── users

**Only the author, ever — the same absence-of-a-branch discipline
`services/notes.py` documents for a private task note.** Every statement in
`services/personal_notes.py` filters on `user_id == the caller`. Not "unless
they're an admin" — there is no branch, and that absence is the whole
feature.

Unlike a task note, this is a **list**, with a title, shown timestamps and a
delete button — the exact shape `services/notes.py`'s own docstring explains
a task note deliberately avoids ("a list would grow a timestamp, an author, a
delete button... and would arrive at being a second comment thread"). The
difference is what it's attached to: a task note is about one piece of work
and stays minimal on purpose; a notepad entry is about nothing in particular,
so it needs the title and the list to be findable again later.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MAX_TITLE_LENGTH = 200


class PersonalNote(Base):
    __tablename__ = "personal_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # CASCADE: a note with no owner is a note nobody may read and nobody can
    # delete. Removing the person removes their notes with them, the same
    # reasoning task_notes already uses.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(MAX_TITLE_LENGTH), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_func.now(),
        onupdate=sa_func.now(),
    )
