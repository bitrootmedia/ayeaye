"""Organisations, their members, and inviting people into them.

Thin: every rule lives in `services/organisations.py` and
`services/invites.py`. These handlers translate HTTP to those calls and shape
the response, nothing more.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.core import mailer
from app.models import OrganisationMember, User
from app.models.organisation import STATUS_INVITED
from app.schemas.organisations import (
    InviteCreate,
    InviteCreated,
    MemberOut,
    MemberRoleUpdate,
    OrganisationCreate,
    OrganisationOut,
    OrganisationUpdate,
)
from app.services import invites as invites_service
from app.services import organisations as orgs_service
from app.tasks.invites import send_invite_email

router = APIRouter(prefix="/organisations", tags=["organisations"])


def _org_out(org, role: str) -> OrganisationOut:
    return OrganisationOut(
        id=str(org.id), name=org.name, slug=org.slug, role=role, created_at=org.created_at
    )


def _member_out(
    member: OrganisationMember,
    user: User | None,
    invited_by: User | None,
    *,
    show_invite_url: bool,
) -> MemberOut:
    return MemberOut(
        id=str(member.id),
        role=member.role,
        status=member.status,
        user_id=str(member.user_id) if member.user_id else None,
        # Fall back to the invited address: someone who hasn't registered has
        # no user row, and a row in the members list with no name at all reads
        # as a bug rather than as a pending invitation.
        email=(user.email if user else None) or member.invited_email,
        display_name=user.display_name if user else None,
        invited_by=(invited_by.display_name or invited_by.email) if invited_by else None,
        accepted_at=member.accepted_at,
        created_at=member.created_at,
        # Only for people who could re-issue it anyway. A link is an entry
        # ticket, so it is not something every member gets to read off the
        # members list.
        invite_url=(
            invites_service.invite_url(member.invite_token)
            if show_invite_url and member.invite_token
            else None
        ),
    )


@router.post("", response_model=OrganisationOut, status_code=status.HTTP_201_CREATED)
async def create_organisation(body: OrganisationCreate, user: CurrentUser, db: DbSession):
    """Create one. You become its owner — see rule 1 in services/organisations."""
    org, role = await orgs_service.create(db, user=user, name=body.name)
    return _org_out(org, role)


@router.get("", response_model=list[OrganisationOut])
async def list_organisations(user: CurrentUser, db: DbSession):
    """Every organisation you're actually in. Pending invitations are not
    membership and appear at `GET /me/invites` instead."""
    return [_org_out(org, role) for org, role in await orgs_service.list_for_user(db, user)]


@router.get("/{org_id}", response_model=OrganisationOut)
async def get_organisation(ctx: CurrentOrg):
    return _org_out(ctx.organisation, ctx.role)


@router.patch("/{org_id}", response_model=OrganisationOut)
async def rename_organisation(body: OrganisationUpdate, ctx: CurrentOrg, db: DbSession):
    """Rename. The slug deliberately doesn't follow — it's in URLs people have
    already shared."""
    org = await orgs_service.rename(db, ctx, body.name)
    return _org_out(org, ctx.role)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organisation(ctx: CurrentOrg, db: DbSession):
    await orgs_service.delete(db, ctx)


@router.get("/{org_id}/members", response_model=list[MemberOut])
async def list_members(ctx: CurrentOrg, db: DbSession):
    """Members and outstanding invitations, in one list.

    **Everyone in the organisation can see who else is in it.** Once projects
    are private by default (Phase 3), the members list is the only place that
    answers "who could I share this with", so hiding it would make the access
    model unusable rather than more private.
    """
    can_manage = orgs_service.can_manage_members(ctx.role)
    return [
        _member_out(member, user, invited_by, show_invite_url=can_manage)
        for member, user, invited_by in await orgs_service.list_members(db, ctx.organisation.id)
    ]


@router.post(
    "/{org_id}/invites", response_model=InviteCreated, status_code=status.HTTP_201_CREATED
)
async def invite(body: InviteCreate, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Invite by email — and always return a copyable link.

    The link is returned whether or not mail is configured, and the response
    says which happened. That is the whole of PLAN.md §2.4: a deployment with
    no SMTP is not a degraded one, it just means the inviter pastes the link
    into chat themselves.
    """
    member = await invites_service.create(
        db, ctx, email=str(body.email), role=body.role, inviter=user
    )

    emailed = mailer.is_configured()
    if emailed:
        # Queued, not sent here: an SMTP handshake on a request thread would
        # hold the inviter's browser for the server's full timeout.
        await send_invite_email.kiq(str(member.id))

    return InviteCreated(
        member=_member_out(member, None, user, show_invite_url=True),
        invite_url=invites_service.invite_url(member.invite_token or ""),
        emailed=emailed,
    )


@router.patch("/{org_id}/members/{member_id}", response_model=MemberOut)
async def change_member_role(
    member_id: uuid.UUID, body: MemberRoleUpdate, ctx: CurrentOrg, db: DbSession
):
    member = await orgs_service.get_member(db, ctx.organisation.id, member_id)
    updated = await orgs_service.change_role(db, ctx, member, body.role)
    return _member_out(updated, None, None, show_invite_url=False)


@router.delete("/{org_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(member_id: uuid.UUID, ctx: CurrentOrg, db: DbSession):
    """Remove someone, revoke an invitation, or leave.

    All three are this one call, because they are the same row going away.
    Revoking kills the invite link with it — the token lives on the row.
    """
    member = await orgs_service.get_member(db, ctx.organisation.id, member_id)
    await orgs_service.remove_member(db, ctx, member)


@router.post("/{org_id}/members/{member_id}/invite-link", response_model=MemberOut)
async def reissue_invite_link(member_id: uuid.UUID, ctx: CurrentOrg, db: DbSession):
    """Mint a fresh link for an outstanding invitation, invalidating the old one.

    Needed because a link is a credential that gets pasted into chat rooms:
    when it lands somewhere it shouldn't, replacing it must not mean deleting
    and re-creating the invitation.
    """
    ctx.require(
        orgs_service.can_manage_members(ctx.role),
        "only an admin or owner can manage invitations",
    )
    member = await orgs_service.get_member(db, ctx.organisation.id, member_id)
    if member.status != STATUS_INVITED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="that person has already joined"
        )
    member.invite_token = invites_service.new_token()
    await db.commit()
    await db.refresh(member)
    return _member_out(member, None, None, show_invite_url=True)
