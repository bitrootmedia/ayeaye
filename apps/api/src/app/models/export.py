"""Data export: a ZIP of everything a person can see, built in the worker.

    organisations ──► exports ◄── users (requested_by)
    projects (nullable) ──► exports

**Privacy: no branch that grants anybody else access, not even an admin.**
The zip's contents reflect the *requester's own* visibility at build time —
`access.visible_tasks_stmt` resolved for them, not "everything in the
organisation" — so letting a different member, even an org admin, download
someone else's export would leak tasks that member couldn't otherwise see.
`services/exports.py` filters every read on `requested_by_user_id ==
caller`, the identical absence-of-a-branch discipline `services/notes.py`
and `services/personal_notes.py` already hold for their own private data.

**Autodelete after a confirmed download.** The server can't observe the
actual browser → storage transfer (same as every other download in this
product), so "confirmed" means the one honest signal available: the person
asked for the file. `downloaded_at` is stamped the first time
`GET .../download` is called; `sweep_expired_exports`
(`tasks/exports.py`) deletes the object and flips `status` to `expired`
once either that stamp or `created_at` (for one nobody ever downloaded) is
old enough. `storage_key` is cleared at the same time — an expired row is
history, not a live pointer into a bucket that no longer has anything at
that key.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"
STATUSES = (STATUS_PENDING, STATUS_READY, STATUS_FAILED, STATUS_EXPIRED)


class Export(Base):
    __tablename__ = "exports"
    __table_args__ = (
        CheckConstraint(f"status IN {STATUSES!r}", name="ck_exports_status"),
        # Every read is "my exports in this organisation" — see the module
        # docstring's privacy rule.
        Index("ix_exports_org_user", "organisation_id", "requested_by_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    # NULL means the whole organisation. Never a sentinel UUID — the same
    # "absence is the signal" convention `Task.project_id` already uses for
    # a loose task.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=STATUS_PENDING)
    storage_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stamped once, by the first GET .../download — see the module docstring.
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
