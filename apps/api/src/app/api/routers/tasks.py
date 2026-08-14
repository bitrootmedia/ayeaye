"""Tasks, their history, and their per-task grants.

Thin: the rules live in `services/tasks.py` and `services/access.py`.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models import Attachment, Project, Tag, Task, TaskGrant, Team, User
from app.schemas.structure import GrantLevelIn, GrantOut, PersonOut, TeamOut
from app.schemas.tasks import (
    NoteIn,
    NoteOut,
    SearchHitOut,
    SearchOut,
    TagIn,
    TagOut,
    TagUpdate,
    TaskAccessOut,
    TaskCloseIn,
    TaskCreate,
    TaskEventOut,
    TaskFileOut,
    TaskGrantIn,
    TaskHiddenIn,
    TaskOut,
    TaskUpdate,
)
from app.services import access as access_service
from app.services import attachments as attachments_service
from app.services import conversations as conversations_service
from app.services import notes as notes_service
from app.services import projects as projects_service
from app.services import search as search_service
from app.services import tags as tags_service
from app.services import tasks as tasks_service

router = APIRouter(prefix="/organisations/{org_id}", tags=["tasks"])


@router.get("/search", response_model=SearchOut)
async def search(ctx: CurrentOrg, user: CurrentUser, db: DbSession, q: str = "", limit: int = 6):
    """Fuzzy search across everything in this organisation the caller can see.

    Registered before `/tasks/{task_id}` and friends so the literal path can't
    be swallowed by a UUID parameter — FastAPI matches in declaration order.

    **The access check is not a filter applied afterwards.** It's ANDed into
    the same statement as the text match, so there is no moment at which a row
    the caller can't see exists in the result set. That is the whole reason
    this is Postgres rather than a search engine — see services/search.py.
    """
    q = search_service.normalise(q)
    if not q:
        # An empty query is not "everything". Returning the whole organisation
        # to a cleared search box would be both slow and a surprise.
        return SearchOut(query="", hits=[])

    hits = await search_service.search(db, ctx, user.id, q=q, limit=min(limit, 20))
    return SearchOut(
        query=q,
        hits=[
            SearchHitOut(
                kind=h.kind,
                id=h.id,
                title=h.title,
                subtitle=h.subtitle,
                context=h.context,
                score=h.score,
                inactive=h.inactive,
            )
            for h in hits
        ],
    )


def _person(user: User | None) -> PersonOut | None:
    if user is None:
        return None
    return PersonOut(id=str(user.id), email=user.email, display_name=user.display_name)


async def _people(db: DbSession, tasks: list[Task]) -> dict[uuid.UUID, User]:
    """One lookup for every person named across the whole page."""
    ids = {t.owner_user_id for t in tasks} | {
        t.action_required_user_id for t in tasks if t.action_required_user_id
    }
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


async def _project_names(db: DbSession, org_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """Names only.

    This is rule "access flows up, read-only": given a task you can see, you
    get its project's *name* for the breadcrumb — not its siblings, and not a
    place in your project list. So it's a plain lookup, not a visibility query.
    """
    rows = (
        await db.execute(
            select(Project.id, Project.name).where(Project.organisation_id == org_id)
        )
    ).all()
    return {pid: name for pid, name in rows}


def _tag_out(tag: Tag, count: int = 0) -> TagOut:
    return TagOut(id=str(tag.id), name=tag.name, off_board=tag.off_board, task_count=count)


async def _tags_for(db: DbSession, tasks: list[Task]) -> dict[uuid.UUID, list[Tag]]:
    """One lookup for the whole page, never one per card."""
    return await tags_service.for_tasks(db, [t.id for t in tasks])


def _task_out(
    task: Task,
    level: str,
    *,
    people: dict[uuid.UUID, User],
    project_names: dict[uuid.UUID, str],
    is_owner: bool,
    tags: dict[uuid.UUID, list[Tag]] | None = None,
) -> TaskOut:
    return TaskOut(
        id=str(task.id),
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        is_open=task.closed_at is None,
        closed_at=task.closed_at,
        project_id=str(task.project_id) if task.project_id else None,
        project_name=project_names.get(task.project_id) if task.project_id else None,
        owner=_person(people.get(task.owner_user_id)),
        action_required=_person(people.get(task.action_required_user_id))
        if task.action_required_user_id
        else None,
        due_on=task.due_on,
        position=task.position,
        created_at=task.created_at,
        is_hidden=task.hidden_at is not None,
        access=level,
        can_close=tasks_service.can_close(level=level, is_owner=is_owner),
        can_hide=tasks_service.can_hide(is_owner=is_owner),
        tags=[_tag_out(t) for t in (tags or {}).get(task.id, [])],
    )


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    project_id: uuid.UUID | None = None,
    loose: bool = False,
    include_closed: bool = False,
    tag_id: uuid.UUID | None = None,
    include_off_board: bool = False,
):
    """Every task you can see, optionally narrowed. Narrowing never widens
    access.

    Tasks carrying an `off_board` tag are left out unless you ask for that tag
    by name (or set `include_off_board`). That is a **display** rule, not an
    access one: they are perfectly visible, they just aren't queueing for
    attention. See services/tags.py.
    """
    visible = await tasks_service.list_visible(
        db,
        ctx,
        user,
        project_id=project_id,
        loose_only=loose,
        include_closed=include_closed,
        tag_id=tag_id,
        include_off_board=include_off_board,
    )
    tasks = [t for t, _ in visible]
    people = await _people(db, tasks)
    names = await _project_names(db, ctx.organisation.id)
    tags = await _tags_for(db, tasks)
    return [
        _task_out(
            task,
            level,
            people=people,
            project_names=names,
            is_owner=task.owner_user_id == user.id,
            tags=tags,
        )
        for task, level in visible
    ]


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskCreate, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    task = await tasks_service.create(
        db,
        ctx,
        user,
        title=body.title,
        description=body.description,
        project_id=uuid.UUID(body.project_id) if body.project_id else None,
        status=body.status,
        priority=body.priority,
        owner_user_id=uuid.UUID(body.owner_user_id) if body.owner_user_id else None,
        action_required_user_id=uuid.UUID(body.action_required_user_id)
        if body.action_required_user_id
        else None,
        due_on=body.due_on,
    )
    people = await _people(db, [task])
    names = await _project_names(db, ctx.organisation.id)
    tags = await _tags_for(db, [task])
    return _task_out(
        task,
        access_service.LEVEL_OWNER if task.owner_user_id == user.id else "write",
        people=people,
        project_names=names,
        is_owner=task.owner_user_id == user.id,
        tags=tags,
    )


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    people = await _people(db, [tctx.task])
    names = await _project_names(db, ctx.organisation.id)
    tags = await _tags_for(db, [tctx.task])
    return _task_out(
        tctx.task,
        tctx.level,
        people=people,
        project_names=names,
        is_owner=tctx.is_owner,
        tags=tags,
    )


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID, body: TaskUpdate, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Partial update.

    Only the fields actually present in the request are applied, so `null` can
    mean "clear this" — which is how the action-required user, the due date and
    the project all get removed.
    """
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    fields: dict = {}
    for name in body.model_fields_set:
        value = getattr(body, name)
        if name in ("project_id", "owner_user_id", "action_required_user_id") and value:
            value = uuid.UUID(value)
        fields[name] = value

    task = await tasks_service.update(db, tctx, ctx, user, fields=fields)
    fresh = await tasks_service.context_for(db, ctx, task_id, user)
    people = await _people(db, [task])
    names = await _project_names(db, ctx.organisation.id)
    tags = await _tags_for(db, [task])
    return _task_out(
        task, fresh.level, people=people, project_names=names, is_owner=fresh.is_owner, tags=tags
    )


@router.post("/tasks/{task_id}/closed", response_model=TaskOut)
async def close_task(
    task_id: uuid.UUID, body: TaskCloseIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Close or reopen. **Only the owner** (or an organisation admin).

    403 rather than 404 for anyone else: they can see the task, so pretending
    it doesn't exist would be the wrong lie.
    """
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    task = await tasks_service.set_open(db, tctx, ctx, user, closed=body.closed)
    people = await _people(db, [task])
    names = await _project_names(db, ctx.organisation.id)
    tags = await _tags_for(db, [task])
    return _task_out(
        task, tctx.level, people=people, project_names=names, is_owner=tctx.is_owner, tags=tags
    )


# --- private notes ---------------------------------------------------------------


@router.get("/tasks/{task_id}/note", response_model=NoteOut)
async def get_note(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """**Your** note on this task. There is no endpoint for anyone else's.

    Not a permission check that admins pass — there is no branch at all. See
    services/notes.py.
    """
    await tasks_service.context_for(db, ctx, task_id, user)
    note = await notes_service.get(db, task_id, user)
    return NoteOut(body=note.body if note else "", updated_at=note.updated_at if note else None)


@router.put("/tasks/{task_id}/note", response_model=NoteOut)
async def put_note(
    task_id: uuid.UUID, body: NoteIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Write it. `read` on the task is enough — it's your note about their
    work, not a change to the work."""
    await tasks_service.context_for(db, ctx, task_id, user)
    note = await notes_service.save(db, task_id, user, body=body.body)
    return NoteOut(body=note.body if note else "", updated_at=note.updated_at if note else None)


# --- tags ---------------------------------------------------------------------


@router.get("/tags", response_model=list[TagOut])
async def list_tags(ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """The organisation's whole vocabulary, with usage counts.

    Not filtered by what the caller can see: a tag is shared vocabulary, and a
    picker that shows different words to different people is a picker that
    creates duplicates.
    """
    return [_tag_out(tag, count) for tag, count in await tags_service.list_for_org(db, ctx)]


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(body: TagIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Get-or-create by name. Anyone in the organisation may.

    201 even when it already existed: the caller asked for a tag with that
    name and now has one. Distinguishing the two would only tempt a client
    into treating "someone beat me to it" as a failure.
    """
    tag = await tags_service.get_or_create(db, ctx, user, name=body.name, off_board=body.off_board)
    return _tag_out(tag)


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: uuid.UUID, body: TagUpdate, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Rename, or move it on and off the board. **Organisation admins only** —
    both change what every existing tagging means."""
    tag = await tags_service.get_or_404(db, ctx, tag_id)
    tag = await tags_service.update(db, ctx, tag, fields=body.model_dump(exclude_unset=True))
    return _tag_out(tag)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Removes the label from every task carrying it. Never the work itself."""
    tag = await tags_service.get_or_404(db, ctx, tag_id)
    await tags_service.remove(db, ctx, tag)


@router.post("/tasks/{task_id}/tags", response_model=list[TagOut], status_code=201)
async def tag_task(
    task_id: uuid.UUID, body: TagIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Apply a tag by name, creating it if this is its first use.

    `write` on the task, like any other edit to it.
    """
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    tag = await tags_service.get_or_create(db, ctx, user, name=body.name)
    await tags_service.apply(db, tctx.task, tag)
    return [_tag_out(t) for t in (await tags_service.for_tasks(db, [task_id])).get(task_id, [])]


@router.delete("/tasks/{task_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def untag_task(
    task_id: uuid.UUID, tag_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Take the label off this task. The tag itself survives — it's shared."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    await tags_service.unapply(db, tctx.task, tag_id)


@router.post("/tasks/{task_id}/hidden", response_model=TaskOut)
async def hide_task(
    task_id: uuid.UUID, body: TaskHiddenIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Hide from everyone but the owner, or bring it back.

    **Only the owner** — an organisation admin is refused here, which is the
    one place in this API where that is true. Hiding leaves exactly one person
    who can see the task, so an admin doing it to someone else's work would be
    hiding it from themselves. See `services/access.py`.
    """
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    task = await tasks_service.set_hidden(db, tctx, user, hidden=body.hidden)
    people = await _people(db, [task])
    names = await _project_names(db, ctx.organisation.id)
    tags = await _tags_for(db, [task])
    return _task_out(
        task, tctx.level, people=people, project_names=names, is_owner=tctx.is_owner, tags=tags
    )


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    await tasks_service.delete(db, tctx)


@router.get("/tasks/{task_id}/events", response_model=list[TaskEventOut])
async def task_history(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """The append-only history. This IS the record of work on a task — there
    is no second audit log."""
    await tasks_service.context_for(db, ctx, task_id, user)
    return [
        TaskEventOut(
            id=str(event.id),
            kind=event.kind,
            actor=_person(actor),
            data=event.data or {},
            created_at=event.created_at,
        )
        for event, actor in await tasks_service.list_events(db, task_id)
    ]


# --- files ---------------------------------------------------------------------


def _file_out(attachment, who: User | None) -> TaskFileOut:
    return TaskFileOut(
        id=str(attachment.id),
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        url=attachments_service.view_url(attachment),
        thumbnail_url=attachments_service.thumbnail_url(attachment),
        from_comment=attachment.conversation_id is not None,
        uploaded_by=_person(who),
        created_at=attachment.created_at,
    )


@router.get("/tasks/{task_id}/files", response_model=list[TaskFileOut])
async def task_files(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Every file on this task — added directly **and** posted in its comments.

    One list because that is the question people actually ask ("where's the
    survey PDF"), and splitting it by how the file arrived means hunting
    through a thread. Each row says which it was.
    """
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    thread = await conversations_service.for_task(db, ctx, user, task_id)
    files = await attachments_service.for_task(
        db, tctx.task, thread.conversation.id if thread.conversation else None
    )
    people = {}
    ids = {f.user_id for f in files if f.user_id}
    if ids:
        rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
        people = {u.id: u for u in rows}
    return [_file_out(f, people.get(f.user_id)) for f in files]


@router.post(
    "/tasks/{task_id}/files", response_model=dict, status_code=status.HTTP_201_CREATED
)
async def stage_task_file(
    task_id: uuid.UUID, body: dict, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Step 1 of the handshake, anchored to the task rather than a comment.

    `write` on the task, not merely `read`: attaching a file to the task itself
    changes what the task *is*, where a comment is a contribution alongside it.
    """
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(
        tasks_service.can_edit(tctx.level), "you have read-only access to this task"
    )
    attachment, upload_url = await attachments_service.create(
        db,
        user,
        task=tctx.task,
        filename=str(body.get("filename") or ""),
        content_type=str(body.get("content_type") or ""),
    )
    return {
        "attachment": {"id": str(attachment.id), "filename": attachment.filename},
        "upload_url": upload_url,
        # Echo the normalised type: the signature covers Content-Type byte for
        # byte, so the client must send back exactly this.
        "content_type": attachment.content_type,
    }


@router.delete("/tasks/{task_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_file(
    task_id: uuid.UUID, file_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Remove a file, and its bytes.

    Yours, or the task owner's call. A file posted inside a comment is removed
    by removing the comment — deleting it from under a message would leave the
    comment referring to something that isn't there.
    """
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    attachment = (
        await db.execute(
            select(Attachment).where(Attachment.id == file_id, Attachment.task_id == task_id)
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    mine = attachment.user_id == user.id
    tctx.require(
        mine or tasks_service.can_manage_access(level=tctx.level, is_owner=tctx.is_owner),
        "you can only remove files you added",
    )
    await attachments_service.delete(db, attachment)


# --- who can see it ---------------------------------------------------------


def _grant_out(grant: TaskGrant, user: User | None, team: Team | None) -> GrantOut:
    return GrantOut(
        id=str(grant.id),
        level=grant.level,
        user=_person(user),
        team=TeamOut(id=str(team.id), name=team.name, member_count=0, created_at=team.created_at)
        if team
        else None,
        created_at=grant.created_at,
    )


@router.get("/tasks/{task_id}/access", response_model=TaskAccessOut)
async def task_access(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    task = tctx.task
    people = await _people(db, [task])
    names = await _project_names(db, ctx.organisation.id)
    admins = await projects_service.list_implicit_viewers(
        db, ctx.organisation.id, task.owner_user_id
    )
    return TaskAccessOut(
        owner=_person(people.get(task.owner_user_id)),
        action_required=_person(people.get(task.action_required_user_id))
        if task.action_required_user_id
        else None,
        project_name=names.get(task.project_id) if task.project_id else None,
        # The single most confusing thing about task access, so it's a field
        # rather than something the UI has to infer from project_name.
        inherits_from_project=task.project_id is not None,
        grants=[
            _grant_out(g, u, t) for g, u, t in await tasks_service.list_grants(db, task_id)
        ],
        organisation_admins=[p for p in (_person(a) for a in admins) if p],
        can_manage=tasks_service.can_manage_access(level=tctx.level, is_owner=tctx.is_owner),
    )


@router.post(
    "/tasks/{task_id}/access", response_model=GrantOut, status_code=status.HTTP_201_CREATED
)
async def add_task_grant(
    task_id: uuid.UUID, body: TaskGrantIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Share one task. Additive to whatever its project already grants — there
    is no way to grant *less* here, because that would be a deny rule."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    row = await tasks_service.grant(
        db,
        tctx,
        ctx,
        user,
        user_id=uuid.UUID(body.user_id) if body.user_id else None,
        team_id=uuid.UUID(body.team_id) if body.team_id else None,
        level=body.level,
    )
    grants = await tasks_service.list_grants(db, task_id)
    return next(_grant_out(g, u, t) for g, u, t in grants if g.id == row.id)


@router.patch("/tasks/{task_id}/access/{grant_id}", response_model=GrantOut)
async def change_task_grant(
    task_id: uuid.UUID,
    grant_id: uuid.UUID,
    body: GrantLevelIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    row = await tasks_service.get_grant(db, task_id, grant_id)
    tctx.require(
        tasks_service.can_manage_access(level=tctx.level, is_owner=tctx.is_owner),
        "only the task owner can change who has access",
    )
    row.level = body.level
    await db.commit()
    grants = await tasks_service.list_grants(db, task_id)
    return next(_grant_out(g, u, t) for g, u, t in grants if g.id == grant_id)


@router.delete("/tasks/{task_id}/access/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_task_grant(
    task_id: uuid.UUID, grant_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    row = await tasks_service.get_grant(db, task_id, grant_id)
    await tasks_service.revoke(db, tctx, user, row)
