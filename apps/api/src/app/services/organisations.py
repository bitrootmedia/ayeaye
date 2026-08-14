"""Organisations and their membership.

The rules live at the top of this module as **pure functions**, deliberately
separate from anything that touches the database. They are the part that must
be obviously correct, and they are tested without infrastructure — the same
discipline the access matrix will need in Phase 3.

Four rules, and they should not be re-derived anywhere else:

1. **Whoever creates an organisation owns it.** The creating user gets an
   `owner` membership in the same transaction; an organisation can never exist
   without one.
2. **You may only hand out a role you hold.** An admin can appoint admins and
   members, never an owner. Otherwise "admin" is just a slower route to owner.
3. **You may not act on someone ranked above you.** An admin cannot demote,
   remove or re-invite an owner.
4. **The last owner cannot be removed or demoted.** Not by themselves either.
   An organisation with no owner is one nobody can administer, and there is no
   support desk to call.

Beyond those, an **org admin can do anything** inside their organisation. That
is the escape hatch that keeps a self-hosted product operable, and it is a
membership role — not an account attribute and not a policy engine.
"""

import re
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Organisation, OrganisationMember, User
from app.models.organisation import (
    ROLE_ADMIN,
    ROLE_OWNER,
    ROLE_RANK,
    ROLES,
    STATUS_ACTIVE,
    STATUS_INVITED,
)

# --- pure rules. no database, no request. -----------------------------------


def slugify(name: str) -> str:
    """A URL-safe stem for an organisation name.

    Never returns an empty string: a name of nothing but punctuation or
    non-Latin script would otherwise produce a slug of "", and the uniqueness
    suffix would then be the entire identifier.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:100] or "org"


def role_at_least(role: str, minimum: str) -> bool:
    return ROLE_RANK.get(role, -1) >= ROLE_RANK[minimum]


def can_manage_members(role: str) -> bool:
    """Invite, remove, and change roles."""
    return role_at_least(role, ROLE_ADMIN)


def can_grant_role(actor_role: str, new_role: str) -> bool:
    """Rule 2. You cannot appoint someone above yourself.

    Self-contained on purpose: it re-checks that the actor can manage members
    at all, so a plain member grants *nothing* rather than "nothing above
    member". Every caller happens to check that first today, and this is the
    rule that would silently fail open the day one of them stops.
    """
    if new_role not in ROLES or not can_manage_members(actor_role):
        return False
    return ROLE_RANK[new_role] <= ROLE_RANK[actor_role]


def can_act_on_member(actor_role: str, subject_role: str) -> bool:
    """Rule 3. Equal rank is allowed — two admins can manage each other, which
    is what makes "admin can do anything" true in practice."""
    return ROLE_RANK.get(actor_role, -1) >= ROLE_RANK.get(subject_role, 99)


def can_rename_organisation(role: str) -> bool:
    return role_at_least(role, ROLE_ADMIN)


def can_delete_organisation(role: str) -> bool:
    """Owners only. Deleting an organisation destroys everyone's work in it,
    which is more than "anything an admin can do"."""
    return role == ROLE_OWNER


# --- the organisation, plus the caller's place in it ------------------------


@dataclass(frozen=True)
class OrgContext:
    """What every organisation-scoped route needs, resolved once.

    Carrying the membership rather than just the role means a route never has
    to ask the database a second time to find out who the caller is.
    """

    organisation: Organisation
    membership: OrganisationMember

    @property
    def role(self) -> str:
        return self.membership.role

    def require(self, allowed: bool, detail: str) -> None:
        """403, not 404. The caller can see this organisation — they just
        can't do this to it. Absence of access is a 404 and is raised long
        before we get here; see `context_for`."""
        if not allowed:
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=detail)


async def context_for(db: AsyncSession, org_id: uuid.UUID, user: User) -> OrgContext:
    """Resolve an organisation and the caller's active membership of it.

    **404 when they are not a member**, never 403 — an organisation you have no
    part in should not be distinguishable from one that doesn't exist. A
    pending invitation is not membership: it doesn't grant access until it's
    accepted, so it reads as 404 here too.
    """
    row = (
        await db.execute(
            select(Organisation, OrganisationMember)
            .join(
                OrganisationMember,
                OrganisationMember.organisation_id == Organisation.id,
            )
            .where(
                Organisation.id == org_id,
                OrganisationMember.user_id == user.id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="organisation not found"
        )
    return OrgContext(organisation=row[0], membership=row[1])


# --- reads -------------------------------------------------------------------


async def unique_slug(db: AsyncSession, name: str) -> str:
    """`acme`, then `acme-2`, `acme-3`… Racy in principle; the unique index is
    the real guarantee and a collision is a retry, not corruption."""
    base = slugify(name)
    taken = set(
        (
            await db.execute(
                select(Organisation.slug).where(Organisation.slug.like(f"{base}%"))
            )
        )
        .scalars()
        .all()
    )
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


async def list_for_user(db: AsyncSession, user: User) -> list[tuple[Organisation, str]]:
    """Every organisation the caller is an active member of, with their role.

    One statement, ordered by name — the same discipline every list endpoint
    follows once access gets interesting.
    """
    rows = (
        await db.execute(
            select(Organisation, OrganisationMember.role)
            .join(
                OrganisationMember,
                OrganisationMember.organisation_id == Organisation.id,
            )
            .where(
                OrganisationMember.user_id == user.id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
            .order_by(Organisation.name)
        )
    ).all()
    return [(org, role) for org, role in rows]


async def list_members(
    db: AsyncSession, org_id: uuid.UUID
) -> list[tuple[OrganisationMember, User | None, User | None]]:
    """Members and outstanding invitations together, because in the UI they are
    one list — "who is in this organisation" includes people on their way in.

    Returns `(membership, the person, whoever invited them)`. Both joins are
    outer: an invitation to someone with no account yet has no user row, and a
    founder was invited by nobody.

    One statement, including the inviter. Resolving "invited by" per row in the
    router would be a query per member — the exact pattern every list endpoint
    in this codebase is forbidden from having.
    """
    inviter = aliased(User)
    rows = (
        await db.execute(
            select(OrganisationMember, User, inviter)
            .outerjoin(User, User.id == OrganisationMember.user_id)
            .outerjoin(inviter, inviter.id == OrganisationMember.invited_by_user_id)
            .where(OrganisationMember.organisation_id == org_id)
            # Active first, then invitations; oldest first within each. UUIDv7
            # is time-ordered, so `id` is a creation-order sort for free.
            .order_by(OrganisationMember.status.desc(), OrganisationMember.id)
        )
    ).all()
    return [(member, user, invited_by) for member, user, invited_by in rows]


async def count_active_owners(db: AsyncSession, org_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(OrganisationMember)
            .where(
                OrganisationMember.organisation_id == org_id,
                OrganisationMember.role == ROLE_OWNER,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalar_one()


async def get_member(
    db: AsyncSession, org_id: uuid.UUID, member_id: uuid.UUID
) -> OrganisationMember:
    member = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.id == member_id,
                OrganisationMember.organisation_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="member not found")
    return member


# --- writes ------------------------------------------------------------------


async def create(db: AsyncSession, *, user: User, name: str) -> tuple[Organisation, str]:
    """Create an organisation and make the creator its owner.

    One transaction, on purpose (rule 1). An organisation that exists for even
    a moment with no owner is one that a crash could leave permanently
    unadministrable.
    """
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="an organisation needs a name",
        )

    org = Organisation(name=name, slug=await unique_slug(db, name), created_by_user_id=user.id)
    db.add(org)
    await db.flush()  # populate org.id without ending the transaction

    db.add(
        OrganisationMember(
            organisation_id=org.id,
            user_id=user.id,
            role=ROLE_OWNER,
            status=STATUS_ACTIVE,
            invited_email=user.email,
            accepted_at=func.now(),
        )
    )
    await db.commit()
    await db.refresh(org)
    return org, ROLE_OWNER


async def rename(db: AsyncSession, ctx: OrgContext, name: str) -> Organisation:
    ctx.require(can_rename_organisation(ctx.role), "only an admin or owner can rename this")
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="an organisation needs a name",
        )
    # The slug deliberately does NOT follow the name. It is in URLs people have
    # bookmarked and shared; renaming is a label change, not a move.
    ctx.organisation.name = name
    await db.commit()
    await db.refresh(ctx.organisation)
    return ctx.organisation


async def delete(db: AsyncSession, ctx: OrgContext) -> None:
    ctx.require(can_delete_organisation(ctx.role), "only an owner can delete an organisation")
    await db.delete(ctx.organisation)
    await db.commit()


async def change_role(
    db: AsyncSession, ctx: OrgContext, member: OrganisationMember, new_role: str
) -> OrganisationMember:
    ctx.require(can_manage_members(ctx.role), "only an admin or owner can change roles")
    ctx.require(
        can_act_on_member(ctx.role, member.role),
        "you cannot change the role of someone above you",
    )
    ctx.require(can_grant_role(ctx.role, new_role), f"you cannot grant the {new_role} role")

    if member.role == new_role:
        return member

    # Rule 4, checked on the way *out* of owner — including on yourself. An
    # owner demoting themselves when they're the only one is the commonest way
    # to lock an organisation, and it always feels deliberate at the time.
    if member.role == ROLE_OWNER and await count_active_owners(db, ctx.organisation.id) <= 1:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="this is the last owner — appoint another owner first",
        )

    member.role = new_role
    await db.commit()
    await db.refresh(member)
    return member


async def remove_member(
    db: AsyncSession, ctx: OrgContext, member: OrganisationMember
) -> None:
    """Remove a member, revoke an invitation, or leave.

    Leaving is the same operation as being removed, so a plain member can do it
    to themselves and to nobody else.
    """
    is_self = member.user_id is not None and member.user_id == ctx.membership.user_id
    if not is_self:
        ctx.require(can_manage_members(ctx.role), "only an admin or owner can remove people")
        ctx.require(
            can_act_on_member(ctx.role, member.role),
            "you cannot remove someone above you",
        )

    if (
        member.role == ROLE_OWNER
        and member.status == STATUS_ACTIVE
        and await count_active_owners(db, ctx.organisation.id) <= 1
    ):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                "this is the last owner — appoint another owner before leaving"
                if is_self
                else "this is the last owner — appoint another owner first"
            ),
        )

    # Anything they own has to go somewhere first. `projects.owner_user_id` and
    # `tasks.owner_user_id` are both RESTRICT — a thing with no owner is a thing
    # nobody can administer — so without this the DELETE below fails with a raw
    # foreign-key error that no admin could act on.
    #
    # PLAN.md §5 asked: block the removal, or reassign? **Reassign.** Blocking
    # makes offboarding a puzzle — you would have to find every task a departing
    # colleague owns before you could remove them, with no screen that lists
    # them. Reassigning to the organisation's first owner is visible, reversible
    # and recorded: every task gets a `task_events` row saying why it moved.
    if member.user_id is not None and member.status == STATUS_ACTIVE:
        await _reassign_everything_owned_by(db, ctx, member.user_id)

    # Hard delete rather than a `revoked` status: the partial unique index on
    # (organisation, invited_email) is scoped to `invited`, so removing the row
    # is what makes re-inviting the same person work.
    await db.delete(member)
    await db.commit()


async def _reassign_everything_owned_by(
    db: AsyncSession, ctx: OrgContext, leaving_user_id: uuid.UUID
) -> None:
    """Hand this person's projects and tasks to an owner who is staying."""
    # Imported here: services.tasks imports services.access, which has no
    # business being pulled in by every module that touches a membership row.
    from app.models import Project
    from app.services import tasks as tasks_service

    successor = (
        await db.execute(
            select(OrganisationMember.user_id)
            .where(
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.status == STATUS_ACTIVE,
                OrganisationMember.role == ROLE_OWNER,
                OrganisationMember.user_id != leaving_user_id,
            )
            .order_by(OrganisationMember.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if successor is None:
        # The last-owner rule above guarantees one exists whenever the person
        # leaving is an owner. This is the belt-and-braces case: refuse rather
        # than orphan.
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="this organisation needs an owner to hand their work to",
        )

    projects = (
        (
            await db.execute(
                select(Project).where(
                    Project.organisation_id == ctx.organisation.id,
                    Project.owner_user_id == leaving_user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    for project in projects:
        project.owner_user_id = successor

    await tasks_service.reassign_owned_tasks(
        db,
        org_id=ctx.organisation.id,
        from_user_id=leaving_user_id,
        to_user_id=successor,
    )


async def accept(db: AsyncSession, member: OrganisationMember, user: User) -> OrganisationMember:
    """Take up an invitation. Idempotent — accepting twice is a no-op, not an
    error, because a double-clicked link is not a mistake worth reporting."""
    if member.status == STATUS_ACTIVE:
        return member
    member.user_id = user.id
    member.status = STATUS_ACTIVE
    member.accepted_at = func.now()
    # Single-use: the link stops working the moment it has been used.
    member.invite_token = None
    await db.commit()
    await db.refresh(member)
    return member


async def decline(db: AsyncSession, member: OrganisationMember) -> None:
    if member.status != STATUS_INVITED:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="that invitation has already been accepted",
        )
    await db.delete(member)
    await db.commit()
