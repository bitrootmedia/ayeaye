"""Who's away, and what the organisation is being told.

    users ──► out_of_office            (dates, visible to colleagues)
    organisations ──► announcements    (admin-authored, everyone reads)

These two are together because they answer the same question — "what do I need
to know before I ask someone for something" — and they are the whole of the
dashboard.

**Out-of-office is deliberately not private.** Its entire purpose is that
colleagues can see it; a private one would just be a diary. It is visible to
members of organisations you share, and nowhere else.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutOfOffice(Base):
    """One stretch of days somebody is away."""

    __tablename__ = "out_of_office"
    __table_args__ = (
        # A period that ends before it starts is a typo that would otherwise
        # sit in the table forever, matching nothing and explaining nothing.
        CheckConstraint("ends_on >= starts_on", name="ck_ooo_dates"),
        # The dashboard query: who is away around now.
        Index("ix_ooo_window", "ends_on", "starts_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Inclusive. "Back on the 5th" is what people say, but "away until the 4th"
    # is what they mean, and an exclusive end date gets entered wrong every
    # single time.
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )


class Announcement(Base):
    """Something an organisation's admins want everybody to see.

    Per organisation, because **this product has no global administrator** —
    there is no staff tier and no backoffice, so there is nobody who could
    write a message to every installation. That constraint comes from the
    architecture rather than from a preference.
    """

    __tablename__ = "announcements"
    __table_args__ = (
        Index("ix_announcements_org", "organisation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Sticky ones sort to the top and stay until taken down. The rest are
    # ordinary notices that age out of the way.
    sticky: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Optional. A notice with an end date is one nobody has to remember to
    # remove, which is the difference between a dashboard and a noticeboard
    # full of last year's paper.
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
