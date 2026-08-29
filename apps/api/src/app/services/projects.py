"""Projects, and who can see them.

Every read here goes through `services/access.py`. Nothing in this module
decides for itself whether someone may see a project — it asks, gets a level
back, and turns "no level" into 404 and "not enough level" into 403.
"""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    OrganisationMember,
    Project,
    ProjectGroup,
    ProjectMember,
    Team,
    User,
)
from app.models.organisation import STATUS_ACTIVE
from app.models.structure import GRANT_LEVELS
from app.services import access
from app.services.organisations import OrgContext


@dataclass(frozen=True)
class ProjectContext:
    """A project plus the caller's resolved level on it."""

    project: Project
    level: str

    def require(self, allowed: bool, detail: str) -> None:
        """403. Reaching this point means they can already see the project;
        absence of access became a 404 in `context_for`."""
        if not allowed:
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=detail)


async def context_for(
    db: AsyncSession, ctx: OrgContext, project_id: uuid.UUID, user_id: uuid.UUID
) -> ProjectContext:
    """One project, or 404.

    Rule 3: a project you have no route to is indistinguishable from one that
    doesn't exist. Note this is the *same* 404 whether the project is missing,
    belongs to another organisation, or is simply not shared with you.
    """
    row = (
        await db.execute(
            access.visible_project_stmt(
                user_id=user_id,
                org_id=ctx.organisation.id,
                org_role=ctx.role,
                project_id=project_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="project not found")
    project, rank = row
    return ProjectContext(project=project, level=access.level_name(rank) or "")


async def list_visible(
    db: AsyncSession, ctx: OrgContext, user_id: uuid.UUID, *, include_archived: bool = False
) -> list[tuple[Project, str]]:
    """Rule 4: one statement, no per-row checks, no filtering in Python."""
    rows = (
        await db.execute(
            access.visible_projects_stmt(
                user_id=user_id,
                org_id=ctx.organisation.id,
                org_role=ctx.role,
                include_archived=include_archived,
            )
        )
    ).all()
    return [(project, access.level_name(rank) or "") for project, rank in rows]


async def task_stats(
    db: AsyncSession, ctx: OrgContext, user_id: uuid.UUID
) -> dict[uuid.UUID, tuple[int, int]]:
    """`{project_id: (open_count, important_count)}` for the whole org, one
    query. A project with no rows here has zero of both — the caller treats a
    missing key as `(0, 0)` rather than this returning every project."""
    rows = (
        await db.execute(
            access.project_task_stats_stmt(
                user_id=user_id, org_id=ctx.organisation.id, org_role=ctx.role
            )
        )
    ).all()
    return {pid: (open_count, important_count) for pid, open_count, important_count in rows}


async def _validate_group(
    db: AsyncSession, ctx: OrgContext, group_id: uuid.UUID | None
) -> uuid.UUID | None:
    """A project can only be filed under a group in its own organisation."""
    if group_id is None:
        return None
    exists = (
        await db.execute(
            select(ProjectGroup.id).where(
                ProjectGroup.id == group_id,
                ProjectGroup.organisation_id == ctx.organisation.id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="group not found")
    return group_id


async def create(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    name: str,
    description: str | None,
    group_id: uuid.UUID | None,
    user: User,
) -> ProjectContext:
    """Create a project. **You own it, and by default only you can see it.**

    Any member of the organisation may create one — that is what makes the
    private default workable rather than restrictive. Nobody has to ask an
    admin for a place to put their work.
    """
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a project needs a name"
        )

    project = Project(
        organisation_id=ctx.organisation.id,
        project_group_id=await _validate_group(db, ctx, group_id),
        name=name,
        description=(description or "").strip() or None,
        owner_user_id=user.id,
        created_by_user_id=user.id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    # No grant row for the owner: ownership is a column, so a row saying the
    # same thing is a second answer that can drift out of step with it.
    return ProjectContext(project=project, level=access.LEVEL_OWNER)


async def update(
    db: AsyncSession,
    pctx: ProjectContext,
    ctx: OrgContext,
    *,
    name: str | None = None,
    description: str | None = None,
    group_id: uuid.UUID | None = None,
    group_id_set: bool = False,
    archived: bool | None = None,
) -> Project:
    """Edit the project itself. Needs `write`; archiving needs `owner`."""
    project = pctx.project
    pctx.require(access.can_write(pctx.level), "you have read-only access to this project")

    if name is not None:
        name = name.strip()
        if not name:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="a project needs a name",
            )
        project.name = name
    if description is not None:
        project.description = description.strip() or None
    if group_id_set:
        project.project_group_id = await _validate_group(db, ctx, group_id)
    if archived is not None:
        # Archiving hides a project from everyone's list at once, so it sits
        # with the person responsible for it rather than with any editor.
        pctx.require(
            access.can_administer(pctx.level), "only the project owner can archive this"
        )
        project.archived_at = func.now() if archived else None

    await db.commit()
    await db.refresh(project)
    return project


async def transfer(
    db: AsyncSession, pctx: ProjectContext, ctx: OrgContext, *, new_owner_id: uuid.UUID
) -> Project:
    """Hand the project to someone else.

    Owner or organisation admin only — the same rule tasks will follow. The new
    owner must be an active member, or the project ends up owned by someone who
    can't reach the organisation it lives in.
    """
    pctx.require(
        access.can_administer(pctx.level), "only the project owner can hand it over"
    )
    member = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.user_id == new_owner_id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="that person is not a member of this organisation",
        )
    pctx.project.owner_user_id = new_owner_id
    await db.commit()
    await db.refresh(pctx.project)
    return pctx.project


async def delete(db: AsyncSession, pctx: ProjectContext) -> None:
    pctx.require(access.can_administer(pctx.level), "only the project owner can delete this")
    await db.delete(pctx.project)
    await db.commit()


# --- access, and stating it plainly ------------------------------------------


async def list_grants(
    db: AsyncSession, project_id: uuid.UUID
) -> list[tuple[ProjectMember, User | None, Team | None]]:
    """Every explicit grant on this project, with its principal resolved.

    One statement with two outer joins — a grant names a user or a team, never
    both, so exactly one side of each row is populated.
    """
    rows = (
        await db.execute(
            select(ProjectMember, User, Team)
            .outerjoin(User, User.id == ProjectMember.user_id)
            .outerjoin(Team, Team.id == ProjectMember.team_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.id)
        )
    ).all()
    return [(grant, user, team) for grant, user, team in rows]


async def list_implicit_viewers(
    db: AsyncSession, org_id: uuid.UUID, owner_id: uuid.UUID
) -> list[User]:
    """Everyone who can see this project *without* a grant: the organisation's
    owners and admins.

    Surfaced rather than assumed. "Who can see this" has to be answerable by
    looking at one screen, and an admin tier that is real but invisible makes
    that screen a lie — which is the whole point of stating access explicitly.
    The project's own owner is listed separately, so they're excluded here.
    """
    member = aliased(OrganisationMember)
    return list(
        (
            await db.execute(
                select(User)
                .join(member, member.user_id == User.id)
                .where(
                    member.organisation_id == org_id,
                    member.status == STATUS_ACTIVE,
                    member.role.in_(("admin", "owner")),
                    User.id != owner_id,
                )
                .order_by(User.display_name, User.email)
            )
        )
        .scalars()
        .all()
    )


async def grant(
    db: AsyncSession,
    pctx: ProjectContext,
    ctx: OrgContext,
    *,
    user_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
    level: str,
    granted_by: User,
) -> ProjectMember:
    """Share the project with one person or one team."""
    pctx.require(
        access.can_administer(pctx.level),
        "only the project owner can change who has access",
    )
    if (user_id is None) == (team_id is None):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="grant to exactly one of a person or a team",
        )
    if level not in GRANT_LEVELS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"level must be one of {', '.join(GRANT_LEVELS)}",
        )

    if user_id is not None:
        if user_id == pctx.project.owner_user_id:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="they already own this project",
            )
        present = (
            await db.execute(
                select(OrganisationMember.id).where(
                    OrganisationMember.organisation_id == ctx.organisation.id,
                    OrganisationMember.user_id == user_id,
                    OrganisationMember.status == STATUS_ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if present is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="that person is not a member of this organisation",
            )
    else:
        present = (
            await db.execute(
                select(Team.id).where(
                    Team.id == team_id, Team.organisation_id == ctx.organisation.id
                )
            )
        ).scalar_one_or_none()
        if present is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="team not found"
            )

    row = ProjectMember(
        project_id=pctx.project.id,
        user_id=user_id,
        team_id=team_id,
        level=level,
        granted_by_user_id=granted_by.id,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="they already have access — change the level instead",
        ) from exc
    await db.refresh(row)
    return row


async def get_grant(db: AsyncSession, project_id: uuid.UUID, grant_id: uuid.UUID) -> ProjectMember:
    row = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.id == grant_id, ProjectMember.project_id == project_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="grant not found")
    return row


async def change_grant(
    db: AsyncSession, pctx: ProjectContext, row: ProjectMember, *, level: str
) -> ProjectMember:
    pctx.require(
        access.can_administer(pctx.level),
        "only the project owner can change who has access",
    )
    if level not in GRANT_LEVELS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"level must be one of {', '.join(GRANT_LEVELS)}",
        )
    row.level = level
    await db.commit()
    await db.refresh(row)
    return row


async def revoke(db: AsyncSession, pctx: ProjectContext, row: ProjectMember) -> None:
    pctx.require(
        access.can_administer(pctx.level),
        "only the project owner can change who has access",
    )
    await db.delete(row)
    await db.commit()
