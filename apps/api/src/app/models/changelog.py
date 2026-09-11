"""The organisation's changelog: what happened, when, and who recorded it.

    organisations ──► changelog_entries ◄── users (whoever recorded it)

A dated log of things worth remembering having happened — "BingAds version
lift", "switched the feed to the new endpoint" — kept per organisation and
read by everyone in it.

**Two dates, and conflating them would be the whole bug.** `happened_on` is
the date being recorded; `created_at` is when somebody typed it in. Tuesday's
version lift routinely gets written down on Thursday, and a log that can only
say Thursday is a log of when people remembered rather than of what happened.
`happened_on` is a `Date` with no time on it, exactly as asked — the same
"a date has no timezone" fact `services/reminders.py` documents, which is why
a row created without one takes today in the *caller's* zone rather than the
server's.

**No `position` column, unlike `bookmarks`.** A shelf of links has no
inherent order, so one is worth storing; a log's order is its dates, and
letting somebody drag an entry above one that happened after it would let the
list lie. Nothing here pins either, for the same reason.

**`created_by_user_id` is SET NULL, deliberately** — the same call
`models/bookmark.py` makes, and it is why `organisations.
_reassign_everything_owned_by` needed no changelog branch. An entry has no
owner, only somebody who happened to record it; "who added this" is a fact
about the past rather than a claim on the row, and an entry whose author has
since left the installation is still the organisation's own history.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Text, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Generous: an entry is free prose and a paragraph explaining a version lift
# is an ordinary thing to write. Long enough not to be in anybody's way, and
# bounded so one paste of a log file can't become a row nothing renders.
MAX_DESCRIPTION_LENGTH = 2000


class ChangelogEntry(Base):
    __tablename__ = "changelog_entries"
    __table_args__ = (
        # An entry with no description is not an entry — it would render as a
        # date with nothing beside it. Enforced here as well as in the
        # service, because the service is not the only writer a schema ever
        # gets.
        CheckConstraint("length(btrim(description)) > 0", name="ck_changelog_entries_description"),
        # The one query this table has: one organisation's log, newest first.
        # Ascending is enough — Postgres scans an index backwards for a DESC
        # order just as happily, so there is no second index worth carrying.
        Index("ix_changelog_entries_org_when", "organisation_id", "happened_on"),
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
    # SET NULL, and nullable — see the module docstring.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: The date being recorded, not the date it was recorded. See above.
    happened_on: Mapped[date] = mapped_column(Date, nullable=False)
    #: Plain text, never HTML — nothing renders this with
    #: `dangerouslySetInnerHTML`, so there is no markup to sanitise because
    #: none is ever parsed as markup, the same safe-by-construction shape
    #: `views/Sparks.tsx`'s own `Linkified` has.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_func.now(),
        onupdate=sa_func.now(),
    )
