"""Teams, project groups and projects — all scoped to one organisation.

Everything here hangs off `/organisations/{org_id}/...` so `CurrentOrg` asks
"are you even in here" exactly once, and answers 404 rather than 403.
"""

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models import Project, ProjectGroup, ProjectMember, Team, User
from app.schemas.structure import (
    GrantIn,
    GrantLevelIn,
    GrantOut,
    NameIn,
    PersonOut,
    ProjectAccessOut,
    ProjectCreate,
    ProjectGroupOut,
    ProjectOut,
    ProjectUpdate,
    TeamDetailOut,
    TeamMemberIn,
    TeamOut,
    TransferIn,
)
from app.services import access as access_service
from app.services import projects as projects_service
from app.services import teams as teams_service

router = APIRouter(prefix="/organisations/{org_id}", tags=["structure"])


def _person(user: User | None) -> PersonOut | None:
    if user is None:
        return None
    return PersonOut(id=str(user.id), email=user.email, display_name=user.display_name)


def _team_out(team: Team, count: int) -> TeamOut:
    return TeamOut(
        id=str(team.id), name=team.name, member_count=count, created_at=team.created_at
    )


def _project_out(
    project: Project,
    level: str,
    *,
    group_name: str | None,
    owner: User | None,
    stats: dict[uuid.UUID, tuple[int, int]] | None = None,
) -> ProjectOut:
    open_count, important_count = (stats or {}).get(project.id, (0, 0))
    return ProjectOut(
        id=str(project.id),
        name=project.name,
        description=project.description,
        project_group_id=str(project.project_group_id) if project.project_group_id else None,
        project_group_name=group_name,
        owner=_person(owner),
        archived=project.archived_at is not None,
        created_at=project.created_at,
        access=level,
        open_task_count=open_count,
        important_task_count=important_count,
    )


# --- teams -------------------------------------------------------------------


@router.get("/teams", response_model=list[TeamOut])
async def list_teams(ctx: CurrentOrg, db: DbSession):
    """Readable by every member.

    A team is a grant target, so a project owner who cannot see the list of
    teams cannot share with one. Membership of a team confers nothing on its
    own — only a project naming that team does.
    """
    return [
        _team_out(team, count)
        for team, count in await teams_service.list_teams(db, ctx.organisation.id)
    ]


@router.post("/teams", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(body: NameIn, ctx: CurrentOrg, db: DbSession):
    return _team_out(await teams_service.create_team(db, ctx, name=body.name), 0)


@router.get("/teams/{team_id}", response_model=TeamDetailOut)
async def get_team(team_id: uuid.UUID, ctx: CurrentOrg, db: DbSession):
    team = await teams_service.get_team(db, ctx.organisation.id, team_id)
    members = await teams_service.list_team_members(db, team.id)
    return TeamDetailOut(
        id=str(team.id),
        name=team.name,
        member_count=len(members),
        created_at=team.created_at,
        members=[p for p in (_person(u) for u in members) if p],
    )


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def rename_team(team_id: uuid.UUID, body: NameIn, ctx: CurrentOrg, db: DbSession):
    team = await teams_service.get_team(db, ctx.organisation.id, team_id)
    updated = await teams_service.rename_team(db, ctx, team, name=body.name)
    members = await teams_service.list_team_members(db, updated.id)
    return _team_out(updated, len(members))


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: uuid.UUID, ctx: CurrentOrg, db: DbSession):
    """Deleting a team revokes every grant made to it. People lose access to
    projects, and nothing else records that they had it."""
    team = await teams_service.get_team(db, ctx.organisation.id, team_id)
    await teams_service.delete_team(db, ctx, team)


@router.post("/teams/{team_id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def add_team_member(
    team_id: uuid.UUID, body: TeamMemberIn, ctx: CurrentOrg, db: DbSession
):
    team = await teams_service.get_team(db, ctx.organisation.id, team_id)
    await teams_service.set_team_member(
        db, ctx, team, user_id=uuid.UUID(body.user_id), present=True
    )


@router.delete("/teams/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(
    team_id: uuid.UUID, user_id: uuid.UUID, ctx: CurrentOrg, db: DbSession
):
    team = await teams_service.get_team(db, ctx.organisation.id, team_id)
    await teams_service.set_team_member(db, ctx, team, user_id=user_id, present=False)


# --- project groups -----------------------------------------------------------


@router.get("/project-groups", response_model=list[ProjectGroupOut])
async def list_groups(ctx: CurrentOrg, db: DbSession):
    return [
        ProjectGroupOut(id=str(g.id), name=g.name, created_at=g.created_at)
        for g in await teams_service.list_groups(db, ctx.organisation.id)
    ]


@router.post(
    "/project-groups", response_model=ProjectGroupOut, status_code=status.HTTP_201_CREATED
)
async def create_group(body: NameIn, ctx: CurrentOrg, db: DbSession):
    g = await teams_service.create_group(db, ctx, name=body.name)
    return ProjectGroupOut(id=str(g.id), name=g.name, created_at=g.created_at)


@router.patch("/project-groups/{group_id}", response_model=ProjectGroupOut)
async def rename_group(group_id: uuid.UUID, body: NameIn, ctx: CurrentOrg, db: DbSession):
    group = await teams_service.get_group(db, ctx.organisation.id, group_id)
    g = await teams_service.rename_group(db, ctx, group, name=body.name)
    return ProjectGroupOut(id=str(g.id), name=g.name, created_at=g.created_at)


@router.delete("/project-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: uuid.UUID, ctx: CurrentOrg, db: DbSession):
    """Deletes the folder, not the work — its projects become ungrouped."""
    group = await teams_service.get_group(db, ctx.organisation.id, group_id)
    await teams_service.delete_group(db, ctx, group)


# --- projects ------------------------------------------------------------------


async def _group_names(db: DbSession, org_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """One lookup for the whole page rather than a join per row."""
    rows = (
        await db.execute(
            select(ProjectGroup.id, ProjectGroup.name).where(
                ProjectGroup.organisation_id == org_id
            )
        )
    ).all()
    return {gid: name for gid, name in rows}


async def _owners(db: DbSession, projects: list[Project]) -> dict[uuid.UUID, User]:
    ids = {p.owner_user_id for p in projects}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    ctx: CurrentOrg, user: CurrentUser, db: DbSession, include_archived: bool = False
):
    """Only what you can see.

    **A project is private to its owner until it is shared** — being in the
    organisation is not access to its work. What comes back is you own it,
    someone named you, someone named a team you're in, or you administer the
    organisation. See services/access.py.
    """
    visible = await projects_service.list_visible(
        db, ctx, user.id, include_archived=include_archived
    )
    groups = await _group_names(db, ctx.organisation.id)
    owners = await _owners(db, [p for p, _ in visible])
    stats = await projects_service.task_stats(db, ctx, user.id)
    return [
        _project_out(
            project,
            level,
            group_name=groups.get(project.project_group_id) if project.project_group_id else None,
            owner=owners.get(project.owner_user_id),
            stats=stats,
        )
        for project, level in visible
    ]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Any member may create one, and owns what they create."""
    pctx = await projects_service.create(
        db,
        ctx,
        name=body.name,
        description=body.description,
        group_id=uuid.UUID(body.project_group_id) if body.project_group_id else None,
        user=user,
    )
    groups = await _group_names(db, ctx.organisation.id)
    return _project_out(
        pctx.project,
        pctx.level,
        group_name=groups.get(pctx.project.project_group_id)
        if pctx.project.project_group_id
        else None,
        owner=user,
    )


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    pctx = await projects_service.context_for(db, ctx, project_id, user.id)
    groups = await _group_names(db, ctx.organisation.id)
    owners = await _owners(db, [pctx.project])
    return _project_out(
        pctx.project,
        pctx.level,
        group_name=groups.get(pctx.project.project_group_id)
        if pctx.project.project_group_id
        else None,
        owner=owners.get(pctx.project.owner_user_id),
    )


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    pctx = await projects_service.context_for(db, ctx, project_id, user.id)
    project = await projects_service.update(
        db,
        pctx,
        ctx,
        name=body.name,
        description=body.description,
        group_id=uuid.UUID(body.project_group_id) if body.project_group_id else None,
        # "absent" and "explicitly null" mean different things here: one leaves
        # the group alone, the other moves the project out of every group.
        group_id_set="project_group_id" in body.model_fields_set,
        archived=body.archived,
    )
    groups = await _group_names(db, ctx.organisation.id)
    owners = await _owners(db, [project])
    return _project_out(
        project,
        pctx.level,
        group_name=groups.get(project.project_group_id) if project.project_group_id else None,
        owner=owners.get(project.owner_user_id),
    )


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    pctx = await projects_service.context_for(db, ctx, project_id, user.id)
    await projects_service.delete(db, pctx)


@router.post("/projects/{project_id}/owner", status_code=status.HTTP_204_NO_CONTENT)
async def transfer_project(
    project_id: uuid.UUID, body: TransferIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Hand the project to someone else.

    **Returns no body, deliberately.** Ownership is the caller's only route in
    unless they're an organisation admin or hold a separate grant, so handing
    it over can leave them with no access to the thing they just changed.
    Re-resolving their level to build a response would then 404 — on a commit
    that already succeeded, which reads as "it failed" when it didn't.

    The client refetches; a 404 there is the correct, honest answer, and the UI
    warns about it before asking for confirmation. Task ownership (Phase 4) has
    exactly the same shape.
    """
    pctx = await projects_service.context_for(db, ctx, project_id, user.id)
    await projects_service.transfer(db, pctx, ctx, new_owner_id=uuid.UUID(body.owner_user_id))


# --- who can see it -----------------------------------------------------------


def _grant_out(grant: ProjectMember, user: User | None, team: Team | None) -> GrantOut:
    return GrantOut(
        id=str(grant.id),
        level=grant.level,
        user=_person(user),
        team=_team_out(team, 0) if team else None,
        created_at=grant.created_at,
    )


@router.get("/projects/{project_id}/access", response_model=ProjectAccessOut)
async def project_access(
    project_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Who can see this project — all three routes in, stated in full.

    Organisation admins are listed explicitly rather than left implied. An
    admin tier that is real but invisible turns this screen into something that
    looks reassuring and isn't, which defeats the point of making access
    explicit in the first place.
    """
    pctx = await projects_service.context_for(db, ctx, project_id, user.id)
    grants = await projects_service.list_grants(db, project_id)
    owner = (
        await db.execute(select(User).where(User.id == pctx.project.owner_user_id))
    ).scalar_one_or_none()
    admins = await projects_service.list_implicit_viewers(
        db, ctx.organisation.id, pctx.project.owner_user_id
    )
    return ProjectAccessOut(
        owner=_person(owner),
        grants=[_grant_out(g, u, t) for g, u, t in grants],
        organisation_admins=[p for p in (_person(a) for a in admins) if p],
        can_manage=access_service.can_administer(pctx.level),
    )


@router.post(
    "/projects/{project_id}/access", response_model=GrantOut, status_code=status.HTTP_201_CREATED
)
async def add_grant(
    project_id: uuid.UUID, body: GrantIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    pctx = await projects_service.context_for(db, ctx, project_id, user.id)
    row = await projects_service.grant(
        db,
        pctx,
        ctx,
        user_id=uuid.UUID(body.user_id) if body.user_id else None,
        team_id=uuid.UUID(body.team_id) if body.team_id else None,
        level=body.level,
        granted_by=user,
    )
    grants = await projects_service.list_grants(db, project_id)
    return next(_grant_out(g, u, t) for g, u, t in grants if g.id == row.id)


@router.patch("/projects/{project_id}/access/{grant_id}", response_model=GrantOut)
async def change_grant(
    project_id: uuid.UUID,
    grant_id: uuid.UUID,
    body: GrantLevelIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    pctx = await projects_service.context_for(db, ctx, project_id, user.id)
    row = await projects_service.get_grant(db, project_id, grant_id)
    await projects_service.change_grant(db, pctx, row, level=body.level)
    grants = await projects_service.list_grants(db, project_id)
    return next(_grant_out(g, u, t) for g, u, t in grants if g.id == grant_id)


@router.delete(
    "/projects/{project_id}/access/{grant_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_grant(
    project_id: uuid.UUID, grant_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    pctx = await projects_service.context_for(db, ctx, project_id, user.id)
    row = await projects_service.get_grant(db, project_id, grant_id)
    await projects_service.revoke(db, pctx, row)
