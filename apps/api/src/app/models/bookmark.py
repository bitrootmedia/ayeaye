"""Bookmarks: the organisation's own shelf of links.

    organisations ──► bookmarks ◄── users (whoever added it)

**Shared, and that is the one thing here unlike `sparks` or
`personal_notes`.** Those two are lists only their author ever reads; this is
the organisation's reference shelf — the staging URL, the shared drive, the
supplier's portal — and everybody in the organisation reads the same rows in
the same order. Which is also what makes an order worth storing at all: a
list nobody else sees needs no agreed one.

**`created_by_user_id` is SET NULL, deliberately, and that is why offboarding
needed no change.** `projects.owner_user_id` and `tasks.owner_user_id` are
RESTRICT because a thing with no owner is a thing nobody can administer, so
`organisations._reassign_everything_owned_by` has to find them a new one. A
bookmark has no owner — only somebody who happened to type it in — and it
stays administrable by the organisation's admins regardless, so removing that
person leaves the link exactly where it was.

**`pinned` is the only column with a rule of its own**: an organisation
`owner` sets it and nobody else, not even an admin — see
`services/bookmarks.py`. Pinned rows sort ahead of every unpinned one, so
pinning is what puts a link at the top of *everyone's* list rather than a
decoration on one row.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Generous rather than tidy: a real URL carrying a signed query string runs
# well past anything that looks reasonable, and truncating one silently
# produces a link that goes somewhere else.
MAX_URL_LENGTH = 2000
MAX_DESCRIPTION_LENGTH = 300


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (
        # A bookmark with no URL is not a bookmark. Enforced here as well as
        # in the service because the service is not the only writer a schema
        # ever gets.
        CheckConstraint("length(btrim(url)) > 0", name="ck_bookmarks_url"),
        # The one query this table has: one organisation's list, pinned first
        # then by position.
        Index("ix_bookmarks_org_order", "organisation_id", "pinned", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SET NULL, and nullable — see the module docstring. "Added by" is a fact
    # about the past, not a claim on the row.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    url: Mapped[str] = mapped_column(String(MAX_URL_LENGTH), nullable=False)
    # What the link is *for*, and the text the list renders. Never NULL:
    # blank and absent are the same intention, and one state is easier to
    # render than two — see `services/notification_channels.py`'s own
    # reasoning for treating a blank override as no override.
    description: Mapped[str] = mapped_column(
        String(MAX_DESCRIPTION_LENGTH), nullable=False, server_default=""
    )
    # A plain integer the client computes the midpoint of, exactly like
    # `Task.position` and `planner_entries.position`. Nothing ever renumbers
    # a list.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_func.now(),
        onupdate=sa_func.now(),
    )
