"""Teams and project groups — the two bits of organisation-wide structure.

Both are **administered by organisation admins and readable by everyone in the
organisation**. That asymmetry is deliberate: a team is a grant target, so a
project owner who can't see the list of teams can't share with one, and a
members-only roster would make the access model unusable. Neither carries any
access of its own — being in a team gives you nothing until a project names
that team.
"""

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrganisationMember, ProjectGroup, Team, TeamMember, User
from app.models.organisation import STATUS_ACTIVE
from app.services import organisations as orgs_service
from app.services.organisations import OrgContext


def _require_admin(ctx: OrgContext, what: str) -> None:
    ctx.require(
        orgs_service.can_manage_members(ctx.role),
        f"only an admin or owner can {what}",
    )


def _clean(name: str, what: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"a {what} needs a name"
        )
    return name


# --- teams -------------------------------------------------------------------


async def list_teams(db: AsyncSession, org_id: uuid.UUID) -> list[tuple[Team, int]]:
    """Every team with its headcount, in one statement.

    The count is a correlated aggregate rather than a second query per team —
    the same discipline as every other list in this codebase.
    """
    headcount = (
        select(func.count())
        .select_from(TeamMember)
        .where(TeamMember.team_id == Team.id)
        .correlate(Team)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(Team, headcount.label("headcount"))
            .where(Team.organisation_id == org_id)
            .order_by(Team.name)
        )
    ).all()
    return [(team, count) for team, count in rows]


async def get_team(db: AsyncSession, org_id: uuid.UUID, team_id: uuid.UUID) -> Team:
    team = (
        await db.execute(
            select(Team).where(Team.id == team_id, Team.organisation_id == org_id)
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="team not found")
    return team


async def list_team_members(db: AsyncSession, team_id: uuid.UUID) -> list[User]:
    return list(
        (
            await db.execute(
                select(User)
                .join(TeamMember, TeamMember.user_id == User.id)
                .where(TeamMember.team_id == team_id)
                .order_by(User.display_name, User.email)
            )
        )
        .scalars()
        .all()
    )


async def create_team(db: AsyncSession, ctx: OrgContext, *, name: str) -> Team:
    _require_admin(ctx, "create teams")
    team = Team(organisation_id=ctx.organisation.id, name=_clean(name, "team"))
    db.add(team)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="a team with that name already exists",
        ) from exc
    await db.refresh(team)
    return team


async def rename_team(db: AsyncSession, ctx: OrgContext, team: Team, *, name: str) -> Team:
    _require_admin(ctx, "rename teams")
    team.name = _clean(name, "team")
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="a team with that name already exists",
        ) from exc
    await db.refresh(team)
    return team


async def delete_team(db: AsyncSession, ctx: OrgContext, team: Team) -> None:
    """Delete a team, and with it every grant made to that team.

    That cascade is the point of the warning the UI shows first: people lose
    access to projects, and nothing else in the system records that they had it.
    """
    _require_admin(ctx, "delete teams")
    await db.delete(team)
    await db.commit()


async def set_team_member(
    db: AsyncSession, ctx: OrgContext, team: Team, *, user_id: uuid.UUID, present: bool
) -> None:
    """Add or remove one person. Idempotent in both directions."""
    _require_admin(ctx, "change team membership")

    if not present:
        await db.execute(
            delete(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == user_id)
        )
        await db.commit()
        return

    # They must actually be in the organisation. Without this you could put an
    # outsider on a team and hand them project access through the side door.
    member = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.user_id == user_id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="that person is not a member of this organisation",
        )

    db.add(TeamMember(team_id=team.id, user_id=user_id))
    try:
        await db.commit()
    except IntegrityError:
        # Already on the team. Adding twice is not a mistake worth reporting.
        await db.rollback()


# --- project groups -----------------------------------------------------------


async def list_groups(db: AsyncSession, org_id: uuid.UUID) -> list[ProjectGroup]:
    return list(
        (
            await db.execute(
                select(ProjectGroup)
                .where(ProjectGroup.organisation_id == org_id)
                .order_by(ProjectGroup.name)
            )
        )
        .scalars()
        .all()
    )


async def get_group(db: AsyncSession, org_id: uuid.UUID, group_id: uuid.UUID) -> ProjectGroup:
    group = (
        await db.execute(
            select(ProjectGroup).where(
                ProjectGroup.id == group_id, ProjectGroup.organisation_id == org_id
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="group not found")
    return group


async def create_group(db: AsyncSession, ctx: OrgContext, *, name: str) -> ProjectGroup:
    _require_admin(ctx, "create project groups")
    group = ProjectGroup(organisation_id=ctx.organisation.id, name=_clean(name, "group"))
    db.add(group)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="a group with that name already exists",
        ) from exc
    await db.refresh(group)
    return group


async def rename_group(
    db: AsyncSession, ctx: OrgContext, group: ProjectGroup, *, name: str
) -> ProjectGroup:
    _require_admin(ctx, "rename project groups")
    group.name = _clean(name, "group")
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="a group with that name already exists",
        ) from exc
    await db.refresh(group)
    return group


async def delete_group(db: AsyncSession, ctx: OrgContext, group: ProjectGroup) -> None:
    """Delete the folder, keep the work.

    `projects.project_group_id` is ON DELETE SET NULL, so the projects inside
    become ungrouped rather than disappearing. Deleting a label must never
    delete what it was labelling.
    """
    _require_admin(ctx, "delete project groups")
    await db.delete(group)
    await db.commit()
