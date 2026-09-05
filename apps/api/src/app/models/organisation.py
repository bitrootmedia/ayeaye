import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Organisation roles, most privileged last. `ROLE_RANK` is what every rule in
# services/organisations.py compares — see the pure rule functions there.
ROLE_MEMBER = "member"
ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"
ROLES = (ROLE_MEMBER, ROLE_ADMIN, ROLE_OWNER)
ROLE_RANK = {ROLE_MEMBER: 0, ROLE_ADMIN: 1, ROLE_OWNER: 2}

# A membership row is either a live membership or an invitation waiting to be
# taken up. One table for both, so binding an invite at signup is one UPDATE
# rather than a copy between tables with a window in the middle.
STATUS_INVITED = "invited"
STATUS_ACTIVE = "active"
# A suspended member — reversible, unlike removal. `context_for` only ever
# resolves an `active` membership, so a disabled row simply stops matching it:
# every organisation-scoped route 404s for that person until an admin flips it
# back, with no second check anywhere else to keep in sync.
STATUS_DISABLED = "disabled"
STATUSES = (STATUS_INVITED, STATUS_ACTIVE, STATUS_DISABLED)


class Organisation(Base):
    """The tenancy boundary. Everything else in the product hangs off one."""

    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Unique across the instance, not per-user: it's destined for URLs, and a
    # slug that means different things to different people is a bug waiting.
    slug: Mapped[str] = mapped_column(String(140), nullable=False, unique=True, index=True)

    # Who created it. RESTRICT: deleting a user must not silently orphan an
    # organisation full of other people's work — that needs a real flow.
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # Admin-set. Unions with a member's own TOTP enrollment rather than
    # replacing it — see services/mfa.py's get_mfa_requirements_for_auth
    # override, the one place this column is actually read.
    require_mfa: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
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

    members: Mapped[list["OrganisationMember"]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )


class OrganisationMember(Base):
    """Membership *and* pending invitation, in one row.

    Four shapes, and the constraints below allow exactly these:

    | status     | user_id | invited_email | meaning                              |
    |------------|---------|---------------|--------------------------------------|
    | `invited`  | NULL    | set           | invited someone with no account yet  |
    | `invited`  | set     | set           | invited someone who already has one, |
    |            |         |               | or they signed up and it bound       |
    | `active`   | set     | maybe         | a member                             |
    | `disabled` | set     | maybe         | a member, suspended                  |

    **An invite never joins anyone automatically.** It is attached to the
    account (so they see it) and stays `invited` until they accept. The
    reference project bound shares outright and listed the consequence in its
    own known-problems section: anyone who knows your email address can drop
    something into your account. Requiring one click closes that.

    The exception is the invite link — clicking it *is* the acceptance.

    **`disabled` is a pause, not a departure.** Only an active member can be
    disabled, so it always has a `user_id` already — see
    `services/organisations.py`'s `disable_member`/`enable_member` for the
    reasoning about why this doesn't reassign what they own the way removal
    does.
    """

    __tablename__ = "organisation_members"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLES!r}", name="ck_org_members_role"),
        CheckConstraint(f"status IN {STATUSES!r}", name="ck_org_members_status"),
        # An active or disabled member is a person. Without this, a bug could
        # leave a membership with nobody in it and every access query would
        # skip it silently rather than failing loudly.
        CheckConstraint(
            "status NOT IN ('active', 'disabled') OR user_id IS NOT NULL",
            name="ck_org_members_active_has_user",
        ),
        # An invitation is addressed to an email. That address is how it binds
        # at signup, so an invite without one can never be taken up.
        CheckConstraint(
            "status <> 'invited' OR invited_email IS NOT NULL",
            name="ck_org_members_invited_has_email",
        ),
        # One membership per person per organisation. Partial, because rows
        # awaiting signup have no user_id and several of those may coexist.
        Index(
            "uq_org_members_org_user",
            "organisation_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        # One *outstanding* invitation per address per organisation. Scoped to
        # `invited` so that re-inviting someone who left works, rather than
        # colliding with the historical row.
        Index(
            "uq_org_members_org_invited_email",
            "organisation_id",
            "invited_email",
            unique=True,
            postgresql_where=text("status = 'invited'"),
        ),
        # The lookup that runs on every single signup.
        Index("ix_org_members_invited_email", "invited_email"),
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

    # NULL while an invitation waits for its recipient to have an account.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )

    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default=ROLE_MEMBER)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=STATUS_INVITED)

    # Always lowercased. Kept after acceptance as a record of how someone got
    # in, which is the first question asked when access is audited.
    invited_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    # Where this organisation's notifications go, when the account's own
    # address isn't where you want them.
    #
    # **On the membership, not in a table of its own**, because a membership
    # *is* "this person, in this organisation" — which is exactly the scope
    # of the override. It leaves when they leave, with no cleanup to
    # remember. NULL means the account address, and that is the whole
    # fallback rule: there is no "inherit" state to distinguish from "unset".
    #
    # Never set on an `invited` row: there is no person yet to have a
    # preference. Nothing enforces that beyond nobody offering the field
    # until you are a member — a stray value there would simply never be
    # read, since the resolver looks up an active membership.
    notification_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # The copyable-link half of an invitation, and the reason email can stay
    # optional (PLAN.md §2.4). Cleared on acceptance so a link is single-use;
    # revoking the invitation deletes the row and with it the token.
    invite_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )

    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    organisation: Mapped[Organisation] = relationship(back_populates="members")
