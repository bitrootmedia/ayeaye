"""The instance operator's panel — who is on this installation, and stopping
abuse.

Thin, like every router here: everything below calls `services/instance.py`,
which is also what `scripts/instance.sh` calls. One implementation, two front
doors — there is deliberately no second set of queries for the screen.

Three things about this surface are load-bearing rather than stylistic, and
all three are the price of having it on the web at all (see that service's
docstring for what changed and why):

* **404, not 403, for anybody without an `instance_admins` row.** A 403
  confirms the route exists and that some session would reach it, which is a
  map of where to aim. `deps.CurrentInstanceAdmin` is the single gate.
* **Nothing here appoints an instance admin.** Granting is
  `scripts/instance.sh grant-admin`, which needs shell access to the box —
  so one stolen session cannot become a permanent foothold, and cannot widen
  past itself.
* **Metadata only.** Counts, dates and names. No route here reads a task
  title, a comment, a note or a file, because this product makes promises
  (a hidden task, a private note, an export) that a browsing backoffice
  would quietly void.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentInstanceAdmin, DbSession
from app.models import Organisation, User
from app.services import instance as instance_service

router = APIRouter(prefix="/instance", tags=["instance"])

#: The panel's own cap. Unlike the task list there *is* one, because unlike a
#: task list this is unbounded by anything a person curated — an installation
#: with 200k accounts should not be one request away from serialising all of
#: them. `X-Total-Count` still says what the page is a page of, so nobody is
#: misled about having everything.
MAX_LIMIT = 200


class TotalsOut(BaseModel):
    users: int
    disabled_users: int
    organisations: int
    suspended_organisations: int
    tasks: int
    users_last_24h: int
    organisations_last_24h: int
    #: A signup rate well ahead of the organisations-created rate is the
    #: shape spam takes here — accounts are cheap to make, and creating an
    #: organisation is the first thing a real person does next. Resolved
    #: server-side so the CLI and the panel can't disagree about it.
    signups_outpacing_organisations: bool


class InstanceUserOut(BaseModel):
    id: str
    email: str
    display_name: str | None
    created_at: datetime
    #: Derived from what they have actually done, never stamped — so
    #: somebody who only ever reads looks idle. See `services/instance.py`.
    last_active_at: datetime | None
    organisations: int
    tasks: int
    disabled_at: datetime | None
    disabled_reason: str | None
    #: Shown so the panel can mark its own operators, and so a lone admin can
    #: see they are the lone admin. Granting is still shell-only.
    is_instance_admin: bool


class InstanceOrganisationOut(BaseModel):
    id: str
    name: str
    slug: str
    created_at: datetime
    last_active_at: datetime | None
    owner_email: str | None
    members: int
    tasks: int
    suspended_at: datetime | None
    suspended_reason: str | None


class SuspendIn(BaseModel):
    suspended: bool
    reason: str | None = Field(default=None, max_length=200)


@router.get("/overview", response_model=TotalsOut)
async def overview(_: CurrentInstanceAdmin, db: DbSession):
    """The headline numbers, in one round trip rather than six."""
    t = await instance_service.totals(db)
    return TotalsOut(
        users=t.users,
        disabled_users=t.disabled_users,
        organisations=t.organisations,
        suspended_organisations=t.suspended_organisations,
        tasks=t.tasks,
        users_last_24h=t.users_last_24h,
        organisations_last_24h=t.organisations_last_24h,
        signups_outpacing_organisations=(
            t.users_last_24h > 20 and t.users_last_24h > t.organisations_last_24h * 3
        ),
    )


@router.get("/users", response_model=list[InstanceUserOut])
async def list_users(
    response: Response,
    _: CurrentInstanceAdmin,
    db: DbSession,
    limit: int = 50,
    offset: int = 0,
    q: str = "",
    oldest: bool = False,
):
    """One page of accounts, newest first by default.

    `q` is a plain substring match on the address or the display name, not
    the fuzzy one ⌘K uses: an operator has the address in front of them off a
    support ticket, and typo tolerance is wrong for a lookup that ends in
    suspending somebody.
    """
    rows, total = await instance_service.list_users(
        db,
        limit=max(1, min(limit, MAX_LIMIT)),
        offset=max(0, offset),
        newest_first=not oldest,
        q=q,
    )
    response.headers["X-Total-Count"] = str(total)
    return [
        InstanceUserOut(
            id=str(r.id),
            email=r.email,
            display_name=r.display_name,
            created_at=r.created_at,
            last_active_at=r.last_active_at,
            organisations=r.organisations,
            tasks=r.tasks,
            disabled_at=r.disabled_at,
            disabled_reason=r.disabled_reason,
            is_instance_admin=r.is_instance_admin,
        )
        for r in rows
    ]


@router.get("/organisations", response_model=list[InstanceOrganisationOut])
async def list_organisations(
    response: Response,
    _: CurrentInstanceAdmin,
    db: DbSession,
    limit: int = 50,
    offset: int = 0,
    q: str = "",
    oldest: bool = False,
):
    """One page of organisations, newest first by default.

    The name is the one piece of content on this surface, and it is here
    because a name is what a spam organisation is recognised by.
    """
    rows, total = await instance_service.list_organisations(
        db,
        limit=max(1, min(limit, MAX_LIMIT)),
        offset=max(0, offset),
        newest_first=not oldest,
        q=q,
    )
    response.headers["X-Total-Count"] = str(total)
    return [
        InstanceOrganisationOut(
            id=str(r.id),
            name=r.name,
            slug=r.slug,
            created_at=r.created_at,
            last_active_at=r.last_active_at,
            owner_email=r.owner_email,
            members=r.members,
            tasks=r.tasks,
            suspended_at=r.suspended_at,
            suspended_reason=r.suspended_reason,
        )
        for r in rows
    ]


@router.post("/users/{user_id}/suspended", status_code=status.HTTP_204_NO_CONTENT)
async def set_user_suspended(
    user_id: uuid.UUID, body: SuspendIn, admin: CurrentInstanceAdmin, db: DbSession
):
    """Stop an account signing in, or let it back.

    **You cannot suspend yourself**, and that is the one guard here. Every
    other refusal in this module is about who may reach the surface at all;
    this one is about the specific footgun of locking yourself out of the
    panel you are standing in — recoverable only from the shell, which an
    operator might not have to hand. Suspending a *different* instance admin
    is allowed: that is a real thing an operator may need to do, and the
    shell is the backstop either way.

    Suspension revokes every live session, so the order matters: the flag is
    committed first (in the service), or a revoked session just sends them to
    the sign-in screen and straight back in.

    204 with no body, like `POST .../owner`: the row the caller would want
    back is the *list* row, with its counts, and recomputing that here to
    return one of it would be a second shape of the same answer.
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "you can't suspend your own account from here — "
                "use scripts/instance.sh if you really mean to"
            ),
        )
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such account")
    changed = await instance_service.set_disabled(
        db, target, disabled=body.suspended, reason=body.reason
    )
    if changed and body.suspended:
        # SuperTokens owns sessions, so this is its call rather than a row we
        # could clear. Never fatal: the suspension already landed, and an
        # unreachable core must not leave the operator thinking nothing
        # happened when the important half did — `deps.get_current_user`
        # turns the open tab away on its next request regardless.
        await instance_service.revoke_sessions(target.supertokens_user_id)


@router.post("/organisations/{org_id}/suspended", status_code=status.HTTP_204_NO_CONTENT)
async def set_organisation_suspended(
    org_id: uuid.UUID, body: SuspendIn, _: CurrentInstanceAdmin, db: DbSession
):
    """Lock an organisation, or unlock it.

    Non-destructive: nothing is deleted, `organisations.context_for` refuses
    while the flag is set, and clearing it puts every member back exactly
    where they were. No sessions are revoked, unlike an account suspension —
    the people in it may be perfectly legitimate members of other
    organisations, and signing them out of the product entirely would be
    punishing them for it.
    """
    organisation = await db.get(Organisation, org_id)
    if organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such organisation")
    await instance_service.set_organisation_suspended(
        db, organisation, suspended=body.suspended, reason=body.reason
    )
