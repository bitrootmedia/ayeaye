import uuid
from datetime import datetime

from sqlalchemy import (
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
STATUSES = (STATUS_INVITED, STATUS_ACTIVE)


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

    Three shapes, and the constraints below allow exactly these:

    | status    | user_id | invited_email | meaning                              |
    |-----------|---------|---------------|--------------------------------------|
    | `invited` | NULL    | set           | invited someone with no account yet  |
    | `invited` | set     | set           | invited someone who already has one, |
    |           |         |               | or they signed up and it bound       |
    | `active`  | set     | maybe         | a member                             |

    **An invite never joins anyone automatically.** It is attached to the
    account (so they see it) and stays `invited` until they accept. The
    reference project bound shares outright and listed the consequence in its
    own known-problems section: anyone who knows your email address can drop
    something into your account. Requiring one click closes that.

    The exception is the invite link — clicking it *is* the acceptance.
    """

    __tablename__ = "organisation_members"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLES!r}", name="ck_org_members_role"),
        CheckConstraint(f"status IN {STATUSES!r}", name="ck_org_members_status"),
        # An active member is a person. Without this, a bug could leave a
        # membership with nobody in it and every access query would skip it
        # silently rather than failing loudly.
        CheckConstraint(
            "status <> 'active' OR user_id IS NOT NULL",
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
