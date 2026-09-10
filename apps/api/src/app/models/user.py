import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """Local mirror of a SuperTokens user.

    SuperTokens owns identity and stores it in its OWN Postgres database, so a
    cross-database foreign key is impossible. Anything that needs to point at
    "a person" — an organisation member, a task owner, a time entry — points
    here instead, and this row is created lazily on the user's first
    authenticated request (see app.services.users.get_or_create).

    There is deliberately no `kind` column. This product has one audience and
    one surface; what a person may do comes entirely from their organisation
    membership and the grants they hold, never from an attribute of the account.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )

    # The link back to the auth core. Their ids are uuid-shaped today but that
    # isn't guaranteed, so it's text.
    supertokens_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )

    # Cached from the SuperTokens core at creation. Held locally because invites
    # are addressed by email, and because /me would otherwise make a network
    # call to the auth core on every request. Always stored lowercased.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)

    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # An IANA name, filled in from the browser on `GET /me` and editable on the
    # account screen. Reminders are *dates*, so "the day before" has no meaning
    # without knowing whose day — see services/reminders.py. NULL means UTC,
    # which is wrong by at most a few hours for somebody who has never opened
    # the app, and those people have no reminders.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # "Heads-down on the refit today." A short line you set for yourself,
    # shown to colleagues beside your name. Deliberately **not** the same
    # thing as an organisation announcement: this is one person's answer to
    # "what are you on with", and it has no author but you.
    status_message: Mapped[str | None] = mapped_column(String(140), nullable=True)

    # Opt-out, not opt-in: the whole point of a daily digest is that nobody
    # has to remember to go looking, so a setting nobody finds defaulting to
    # off would mean almost nobody ever sees one. See tasks/daily_summary.py.
    daily_summary_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Which local hour that digest goes out, 0-23. Per person rather than one
    # constant for the whole installation, because the only sensible value is
    # the one somebody picked: a digest is read at the start of *their* day.
    # Defaults to 6 — early enough to shape the day, and late enough that it
    # is never the 3am message a timezone-naive scheduler eventually sends
    # somebody. Read against `timezone`, so a wrong zone moves the hour with
    # it; the account screen shows both together for exactly that reason.
    daily_summary_hour: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("6")
    )
    # The claim for the digest sweep — a date, not a timestamp, because the
    # question is "did they get today's" and a date is the whole answer. Same
    # discipline as `Reminder.notified_ahead_at`: the sweep's UPDATE sets this
    # in the same statement that selects who's due, so a restart or two
    # schedulers racing sends one digest, not two.
    last_daily_summary_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Set true for every account that existed when email verification was
    # introduced, and cleared by the one-off pass in
    # `services/verification.py`. False for everything created since, which
    # is what stops it grandfathering people who should verify normally.
    grandfather_verification: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )

    # Account suspension, set only by an operator from the shell (see
    # `scripts/instance.sh` and `services/instance.py`). NULL is the normal
    # state; a timestamp means sign-in is refused and every session was
    # revoked at that moment.
    #
    # **This is deliberately not the `role`/`is_staff` column the invariant
    # test forbids, and the distinction is the whole point.** That test
    # exists because what a person may do *inside* an organisation must come
    # from their membership and grants and nowhere else. This says nothing
    # about that: it is upstream of the whole access model, the account-level
    # twin of `organisation_members.status = 'disabled'` — either the account
    # works or it doesn't, and if it does, authorization is unchanged. No
    # branch anywhere in `services/access.py` reads it.
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Why, in the operator's own words — "signed up 400 orgs in an hour".
    # For the person reviewing the list in a month, not for the account
    # holder, who never sees it.
    disabled_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        Index("ix_users_disabled", "disabled_at", postgresql_where=text("disabled_at IS NOT NULL")),
        # An hour outside the range would read as "never sent" rather than
        # failing anywhere anybody would look, so it is refused by the
        # database as well as by the API field that writes it.
        CheckConstraint("daily_summary_hour BETWEEN 0 AND 23", name="ck_users_daily_summary_hour"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
