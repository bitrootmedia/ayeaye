"""Tasks, their history, and their per-task grants.

Thin: the rules live in `services/tasks.py` and `services/access.py`.
"""

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models import Attachment, Project, Tag, Task, TaskGrant, TaskSeries, Team, User
from app.schemas.structure import GrantLevelIn, GrantOut, PersonOut, TeamOut
from app.schemas.tasks import (
    BoardColumn,
    BoardOut,
    ChecklistIn,
    ChecklistItemIn,
    ChecklistItemOut,
    ChecklistItemUpdate,
    ChecklistOut,
    ChecklistUpdate,
    NoteIn,
    NoteOut,
    SearchHitOut,
    SearchOut,
    SheetCellOut,
    SheetColumnIn,
    SheetColumnOut,
    SheetIn,
    SheetOut,
    SheetRowIn,
    SheetRowOut,
    SheetUpdate,
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
    TaskRecurrenceIn,
    TaskRecurrenceOut,
    TaskUpdate,
)
from app.services import access as access_service
from app.services import attachments as attachments_service
from app.services import checklists as checklists_service
from app.services import conversations as conversations_service
from app.services import notes as notes_service
from app.services import pins as pins_service
from app.services import projects as projects_service
from app.services import recurrence as recurrence_service
from app.services import richtext
from app.services import search as search_service
from app.services import sheets as sheets_service
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


@router.get("/tasks/similar", response_model=SearchOut)
async def similar_tasks(
    ctx: CurrentOrg, user: CurrentUser, db: DbSession, q: str = "", limit: int = 5
):
    """Tasks whose title already looks like this one — the duplicate-check
    the new-task dialog runs before it actually creates anything.

    Registered before `/tasks/{task_id}`, same reason as `/search` above.
    Deliberately **tasks only**, not the full multi-kind `search()`: a
    duplicate task isn't a duplicate project or a duplicate note, and this
    reuses `search_service.tasks_stmt` directly rather than filtering a mixed
    result down to one kind. Same access-scoped fuzzy match either way — a
    task you can't see can't be flagged as a duplicate of one you're about
    to create, the same as it can't turn up in search.
    """
    q = search_service.normalise(q)
    if len(q) < search_service.MIN_FUZZY_LENGTH:
        # Too short for a trigram match to mean anything — see
        # services/search.py's own threshold for why.
        return SearchOut(query=q, hits=[])

    await search_service.apply_threshold(db)
    stmt = search_service.tasks_stmt(user_id=user.id, ctx=ctx, q=q, limit=min(limit, 20))
    rows = (await db.execute(stmt)).all()
    return SearchOut(
        query=q,
        hits=[
            SearchHitOut(
                kind=row.kind,
                id=str(row.id),
                title=row.title,
                subtitle=search_service.snippet(row.subtitle, q),
                context=row.context,
                score=float(row.score or 0),
                inactive=bool(row.inactive),
            )
            for row in rows
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


async def _pinned_for(db: DbSession, tasks: list[Task], user: User) -> set[uuid.UUID]:
    """Which of these tasks the caller has pinned. One lookup for the whole
    page, same discipline as `_tags_for` — and personal to the caller, unlike
    a tag: two people looking at the same list can get two different answers."""
    return await pins_service.pinned_ids(db, [t.id for t in tasks], user)


def _recurrence_out(series: TaskSeries, *, user: User, org_role: str) -> TaskRecurrenceOut:
    return TaskRecurrenceOut(
        id=str(series.id),
        interval_unit=series.interval_unit,
        interval_count=series.interval_count,
        next_due_on=series.next_due_on,
        active=series.active,
        can_manage=recurrence_service.can_manage(series, user_id=user.id, org_role=org_role),
    )


async def _recurrence_for(
    db: DbSession, tasks: list[Task], user: User, ctx
) -> dict[uuid.UUID, TaskRecurrenceOut]:
    """One lookup for the whole page, same discipline as `_pinned_for` — used
    only where the caller re-renders from the response (the single-task
    endpoints), not on the list or board, which don't pay this row's cost."""
    series_map = await recurrence_service.for_tasks(db, tasks)
    out: dict[uuid.UUID, TaskRecurrenceOut] = {}
    for task in tasks:
        series = series_map.get(task.series_id) if task.series_id else None
        if series is not None:
            out[task.id] = _recurrence_out(series, user=user, org_role=ctx.role)
    return out


async def _image_urls(db: DbSession, tasks: list[Task]) -> dict[uuid.UUID, str]:
    """Fresh presigned URLs for every image referenced by these descriptions.

    One lookup for the whole page. A description with ten screenshots would
    otherwise be ten queries, and a board of them would be hundreds.

    Scoped to attachments **on these tasks**: an id copied from another task's
    description resolves to nothing and renders as a missing image, rather
    than as a working link to something the reader may not be allowed to see.
    """
    wanted: set[uuid.UUID] = set()
    for task in tasks:
        wanted.update(richtext.image_ids(task.description))
    if not wanted:
        return {}
    rows = (
        (
            await db.execute(
                select(Attachment).where(
                    Attachment.id.in_(wanted),
                    Attachment.task_id.in_([t.id for t in tasks]),
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.id: attachments_service.view_url(row) for row in rows}


def _task_out(
    task: Task,
    level: str,
    *,
    people: dict[uuid.UUID, User],
    project_names: dict[uuid.UUID, str],
    is_owner: bool,
    tags: dict[uuid.UUID, list[Tag]] | None = None,
    image_urls: dict[uuid.UUID, str] | None = None,
    pinned: set[uuid.UUID] | None = None,
    recurrence: dict[uuid.UUID, TaskRecurrenceOut] | None = None,
) -> TaskOut:
    return TaskOut(
        id=str(task.id),
        title=task.title,
        description=richtext.render(task.description, image_urls or {}),
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
        updated_at=task.updated_at,
        is_hidden=task.hidden_at is not None,
        is_pinned=task.id in (pinned or set()),
        recurrence=(recurrence or {}).get(task.id),
        access=level,
        can_close=tasks_service.can_close(level=level, is_owner=is_owner),
        can_hide=tasks_service.can_hide(is_owner=is_owner),
        tags=[_tag_out(t) for t in (tags or {}).get(task.id, [])],
    )


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    response: Response,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    project_id: uuid.UUID | None = None,
    loose: bool = False,
    include_closed: bool = False,
    tag_id: uuid.UUID | None = None,
    include_off_board: bool = False,
    status: str | None = None,
    priority: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    action_required_user_id: uuid.UUID | None = None,
    sort: str | None = None,
    dir: str = "asc",
    limit: int | None = None,
    offset: int = 0,
):
    """Every task you can see, optionally narrowed. Narrowing never widens
    access.

    **No default limit.** A silent cap is worse than a big response: the caller
    believes they have everything and quietly doesn't. Ask for a `limit` and
    the count of everything matching comes back in `X-Total-Count`, so a
    paging client always knows what it is a page *of*.

    Tasks carrying an `off_board` tag are left out unless you ask for that tag
    by name (or set `include_off_board`). That is a **display** rule, not an
    access one: they are perfectly visible, they just aren't queueing for
    attention. See services/tags.py.
    """
    filters = {
        "project_id": project_id,
        "loose_only": loose,
        "include_closed": include_closed,
        "tag_id": tag_id,
        "include_off_board": include_off_board,
        "status": status,
        "priority": priority,
        "owner_user_id": owner_user_id,
        "action_required_user_id": action_required_user_id,
        # An unknown sort key is ignored rather than rejected: the value comes
        # from a URL people share and edit, and a link naming a column that no
        # longer exists should show the default order, not an error page.
        "sort": sort if sort in access_service.SORTS else None,
        "descending": dir == "desc",
    }
    if limit is None:
        # Unbounded, as before. Every caller that doesn't page still gets
        # everything rather than a cap it never asked for.
        visible = await tasks_service.list_visible(db, ctx, user, **filters)
        total = len(visible)
    else:
        visible, total = await tasks_service.list_page(
            db, ctx, user, limit=limit, offset=offset, **filters
        )
    response.headers["X-Total-Count"] = str(total)
    tasks = [t for t, _ in visible]
    people = await _people(db, tasks)
    names = await _project_names(db, ctx.organisation.id)
    tags = await _tags_for(db, tasks)
    images = await _image_urls(db, tasks)
    pinned = await _pinned_for(db, tasks, user)
    return [
        _task_out(
            task,
            level,
            people=people,
            project_names=names,
            is_owner=task.owner_user_id == user.id,
            tags=tags,
            image_urls=images,
            pinned=pinned,
        )
        for task, level in visible
    ]


@router.get("/tasks/board", response_model=BoardOut)
async def task_board(
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    group: str = "status",
    per_group: int = 50,
    project_id: uuid.UUID | None = None,
    loose: bool = False,
    include_closed: bool = False,
    tag_id: uuid.UUID | None = None,
):
    """The board: the top `per_group` of each column, with each column's real
    total.

    Its own endpoint rather than a mode of `/tasks`, because a board cannot be
    paged with `LIMIT`. Rows come back priority-first, so the first N of
    several thousand are all criticals and four columns arrive empty. The
    window function in `access.board_stmt` bounds each column separately.

    Registered before `/tasks/{task_id}`: FastAPI matches in declaration
    order, and a literal path after a UUID parameter is a path that never
    runs.
    """
    per_group = max(1, min(per_group, 200))
    group = "priority" if group == "priority" else "status"
    rows = await tasks_service.board(
        db,
        ctx,
        user,
        group_by=group,
        per_group=per_group,
        project_id=project_id,
        loose_only=loose,
        include_closed=include_closed,
        tag_id=tag_id,
    )
    people = await _people(db, [t for t, _, _ in rows])
    names = await _project_names(db, ctx.organisation.id)
    tags = await _tags_for(db, [t for t, _, _ in rows])
    images = await _image_urls(db, [t for t, _, _ in rows])
    pinned = await _pinned_for(db, [t for t, _, _ in rows], user)

    columns: dict[str, BoardColumn] = {}
    for task, level, total in rows:
        key = task.priority if group == "priority" else task.status
        column = columns.setdefault(key, BoardColumn(key=key, total=total, tasks=[]))
        column.tasks.append(
            _task_out(
                task,
                level,
                people=people,
                project_names=names,
                is_owner=task.owner_user_id == user.id,
                tags=tags,
                image_urls=images,
                pinned=pinned,
            )
        )
    return BoardOut(group_by=group, per_group=per_group, columns=list(columns.values()))


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
    images = await _image_urls(db, [task])
    return _task_out(
        task,
        access_service.LEVEL_OWNER if task.owner_user_id == user.id else "write",
        people=people,
        project_names=names,
        is_owner=task.owner_user_id == user.id,
        tags=tags,
        image_urls=images,
    )


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    people = await _people(db, [tctx.task])
    names = await _project_names(db, ctx.organisation.id)
    tags = await _tags_for(db, [tctx.task])
    images = await _image_urls(db, [tctx.task])
    pinned = await _pinned_for(db, [tctx.task], user)
    recurrence = await _recurrence_for(db, [tctx.task], user, ctx)
    return _task_out(
        tctx.task,
        tctx.level,
        people=people,
        project_names=names,
        is_owner=tctx.is_owner,
        tags=tags,
        image_urls=images,
        pinned=pinned,
        recurrence=recurrence,
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
    images = await _image_urls(db, [task])
    pinned = await _pinned_for(db, [task], user)
    recurrence = await _recurrence_for(db, [task], user, ctx)
    return _task_out(
        task,
        fresh.level,
        people=people,
        project_names=names,
        is_owner=fresh.is_owner,
        tags=tags,
        image_urls=images,
        pinned=pinned,
        recurrence=recurrence,
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
    images = await _image_urls(db, [task])
    pinned = await _pinned_for(db, [task], user)
    recurrence = await _recurrence_for(db, [task], user, ctx)
    return _task_out(
        task,
        tctx.level,
        people=people,
        project_names=names,
        is_owner=tctx.is_owner,
        tags=tags,
        image_urls=images,
        pinned=pinned,
        recurrence=recurrence,
    )


# --- personal pins -----------------------------------------------------------


async def _task_response(db: DbSession, ctx, tctx, user: User) -> TaskOut:
    """Rebuild the full `TaskOut` for one task. Shared by every endpoint below
    that mutates something *about* the task without going through
    `tasks_service.update()` — pinning and recurrence both need the same
    people/tags/pinned/recurrence lookups a plain GET does."""
    people = await _people(db, [tctx.task])
    names = await _project_names(db, ctx.organisation.id)
    tags = await _tags_for(db, [tctx.task])
    images = await _image_urls(db, [tctx.task])
    pinned = await _pinned_for(db, [tctx.task], user)
    recurrence = await _recurrence_for(db, [tctx.task], user, ctx)
    return _task_out(
        tctx.task,
        tctx.level,
        people=people,
        project_names=names,
        is_owner=tctx.is_owner,
        tags=tags,
        image_urls=images,
        pinned=pinned,
        recurrence=recurrence,
    )


@router.post("/tasks/{task_id}/pin", response_model=TaskOut)
async def pin_task(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Bookmark it for your own dashboard. `read` is enough — see
    services/pins.py. Idempotent: pinning something already pinned changes
    nothing."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    await pins_service.set_pinned(db, task_id, user, pinned=True)
    return await _task_response(db, ctx, tctx, user)


@router.delete("/tasks/{task_id}/pin", response_model=TaskOut)
async def unpin_task(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    await pins_service.set_pinned(db, task_id, user, pinned=False)
    return await _task_response(db, ctx, tctx, user)


# --- recurrence ---------------------------------------------------------------


@router.post("/tasks/{task_id}/recurrence", response_model=TaskOut)
async def make_recurring(
    task_id: uuid.UUID, body: TaskRecurrenceIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Turn this task into the first occurrence of a series. `write` on the
    task, like any other edit — see `services/recurrence.py`."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    await recurrence_service.attach(
        db,
        ctx,
        user,
        tctx.task,
        interval_unit=body.interval_unit,
        interval_count=body.interval_count,
    )
    return await _task_response(db, ctx, tctx, user)


@router.post("/tasks/{task_id}/recurrence/stop", response_model=TaskOut)
async def stop_recurring(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Stop future occurrences. Whoever set it up, or an organisation admin —
    not the same rule as editing the task, because the series can outlive any
    one occurrence of it. Already-generated tasks are untouched."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    if tctx.task.series_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not a recurring task")
    series = await recurrence_service.get_or_404(db, tctx.task.series_id, ctx.organisation.id)
    await recurrence_service.stop(db, ctx, user, series)
    return await _task_response(db, ctx, tctx, user)


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
    await tasks_service.announce(db, tctx.task, "tagged")
    return [_tag_out(t) for t in (await tags_service.for_tasks(db, [task_id])).get(task_id, [])]


@router.delete("/tasks/{task_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def untag_task(
    task_id: uuid.UUID, tag_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Take the label off this task. The tag itself survives — it's shared."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    await tags_service.unapply(db, tctx.task, tag_id)
    await tasks_service.announce(db, tctx.task, "untagged")


def _checklist_out(checklist) -> ChecklistOut:
    return ChecklistOut(
        id=str(checklist.id),
        title=checklist.title,
        items=[
            ChecklistItemOut(id=str(item.id), text=item.text, done=item.done_at is not None)
            for item in checklist.items
        ],
    )


@router.get("/tasks/{task_id}/checklists", response_model=list[ChecklistOut])
async def list_checklists(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Every checklist on the task. `read` is enough — seeing what's on the
    list doesn't change it."""
    await tasks_service.context_for(db, ctx, task_id, user)
    return [_checklist_out(c) for c in await checklists_service.for_task(db, task_id)]


@router.post(
    "/tasks/{task_id}/checklists",
    response_model=ChecklistOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_checklist(
    task_id: uuid.UUID, body: ChecklistIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """`write` on the task, like any other edit to it — a checklist is shared
    content, not a personal record."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    checklist = await checklists_service.add_checklist(db, tctx.task, title=body.title)
    await tasks_service.announce(db, tctx.task, "checklist_added")
    # Built directly rather than through `_checklist_out`: a freshly created
    # checklist has no items yet, and `checklist.items` is unloaded here —
    # touching it would lazy-load outside an awaited call. See
    # `checklists_service.get_checklist_or_404`'s docstring for the trap.
    return ChecklistOut(id=str(checklist.id), title=checklist.title, items=[])


@router.patch("/tasks/{task_id}/checklists/{checklist_id}", response_model=ChecklistOut)
async def rename_checklist(
    task_id: uuid.UUID,
    checklist_id: uuid.UUID,
    body: ChecklistUpdate,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    checklist = await checklists_service.get_checklist_or_404(db, task_id, checklist_id)
    checklist = await checklists_service.rename_checklist(db, checklist, title=body.title)
    await tasks_service.announce(db, tctx.task, "checklist_renamed")
    return _checklist_out(checklist)


@router.delete(
    "/tasks/{task_id}/checklists/{checklist_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_checklist(
    task_id: uuid.UUID, checklist_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    checklist = await checklists_service.get_checklist_or_404(db, task_id, checklist_id)
    await checklists_service.remove_checklist(db, checklist)
    await tasks_service.announce(db, tctx.task, "checklist_removed")


@router.post(
    "/tasks/{task_id}/checklists/{checklist_id}/items",
    response_model=ChecklistItemOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_checklist_item(
    task_id: uuid.UUID,
    checklist_id: uuid.UUID,
    body: ChecklistItemIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    checklist = await checklists_service.get_checklist_or_404(db, task_id, checklist_id)
    item = await checklists_service.add_item(db, checklist, text=body.text)
    await tasks_service.announce(db, tctx.task, "checklist_item_added")
    return ChecklistItemOut(id=str(item.id), text=item.text, done=False)


@router.patch(
    "/tasks/{task_id}/checklists/{checklist_id}/items/{item_id}", response_model=ChecklistItemOut
)
async def update_checklist_item(
    task_id: uuid.UUID,
    checklist_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ChecklistItemUpdate,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """Check it off, or re-word it. `write`, same as everything else here —
    ticking a box is a change to shared content, not a personal record the
    way logging your own time against a `read`-only task is."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    item = await checklists_service.get_item_or_404(db, checklist_id, item_id)
    item = await checklists_service.update_item(
        db, item, fields=body.model_dump(exclude_unset=True)
    )
    await tasks_service.announce(db, tctx.task, "checklist_item_toggled")
    return ChecklistItemOut(id=str(item.id), text=item.text, done=item.done_at is not None)


@router.delete(
    "/tasks/{task_id}/checklists/{checklist_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_checklist_item(
    task_id: uuid.UUID,
    checklist_id: uuid.UUID,
    item_id: uuid.UUID,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    item = await checklists_service.get_item_or_404(db, checklist_id, item_id)
    await checklists_service.remove_item(db, item)
    await tasks_service.announce(db, tctx.task, "checklist_item_removed")


def _sheet_out(sheet, cells: dict) -> SheetOut:
    return SheetOut(
        id=str(sheet.id),
        title=sheet.title,
        rows=[SheetRowOut(id=str(r.id), label=r.label) for r in sheet.rows],
        columns=[SheetColumnOut(id=str(c.id), label=c.label) for c in sheet.columns],
        cells=[
            SheetCellOut(
                row_id=str(row_id),
                column_id=str(column_id),
                checked_by=PersonOut(
                    id=str(who.id), email=who.email, display_name=who.display_name
                ),
                checked_at=cell.created_at,
            )
            for (row_id, column_id), (cell, who) in cells.items()
        ],
    )


@router.get("/tasks/{task_id}/sheets", response_model=list[SheetOut])
async def list_sheets(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Every sheet on the task. `read` is enough — seeing the grid doesn't
    change it."""
    await tasks_service.context_for(db, ctx, task_id, user)
    sheets = await sheets_service.for_task(db, task_id)
    cells = await sheets_service.cells_for_sheets(db, [s.id for s in sheets])
    return [_sheet_out(s, cells) for s in sheets]


@router.post(
    "/tasks/{task_id}/sheets", response_model=SheetOut, status_code=status.HTTP_201_CREATED
)
async def create_sheet(
    task_id: uuid.UUID, body: SheetIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """`write` on the task, like any other edit to it — a sheet is shared
    content, not a personal record."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    sheet = await sheets_service.add_sheet(db, tctx.task, title=body.title)
    await tasks_service.announce(db, tctx.task, "sheet_added")
    # A freshly created sheet has no rows, columns or cells yet — built
    # directly rather than eager-loading empty relationships for nothing.
    return SheetOut(id=str(sheet.id), title=sheet.title, rows=[], columns=[], cells=[])


@router.patch("/tasks/{task_id}/sheets/{sheet_id}", response_model=SheetOut)
async def update_sheet(
    task_id: uuid.UUID,
    sheet_id: uuid.UUID,
    body: SheetUpdate,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    sheet = await sheets_service.get_sheet_or_404(db, task_id, sheet_id)
    sheet = await sheets_service.rename_sheet(db, sheet, title=body.title)
    cells = await sheets_service.cells_for_sheets(db, [sheet.id])
    await tasks_service.announce(db, tctx.task, "sheet_renamed")
    return _sheet_out(sheet, cells)


@router.delete("/tasks/{task_id}/sheets/{sheet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sheet(
    task_id: uuid.UUID, sheet_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    sheet = await sheets_service.get_sheet_or_404(db, task_id, sheet_id)
    await sheets_service.remove_sheet(db, sheet)
    await tasks_service.announce(db, tctx.task, "sheet_removed")


@router.post(
    "/tasks/{task_id}/sheets/{sheet_id}/rows",
    response_model=SheetRowOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_sheet_row(
    task_id: uuid.UUID,
    sheet_id: uuid.UUID,
    body: SheetRowIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """A new row starts unchecked for every existing column — there's
    nothing to backfill, since a cell's existence is the check (see
    `models/sheet.py`)."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    sheet = await sheets_service.get_sheet_or_404(db, task_id, sheet_id)
    row = await sheets_service.add_row(db, sheet, label=body.label)
    await tasks_service.announce(db, tctx.task, "sheet_row_added")
    return SheetRowOut(id=str(row.id), label=row.label)


@router.delete(
    "/tasks/{task_id}/sheets/{sheet_id}/rows/{row_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_sheet_row(
    task_id: uuid.UUID,
    sheet_id: uuid.UUID,
    row_id: uuid.UUID,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    row = await sheets_service.get_row_or_404(db, sheet_id, row_id)
    await sheets_service.remove_row(db, row)
    await tasks_service.announce(db, tctx.task, "sheet_row_removed")


@router.post(
    "/tasks/{task_id}/sheets/{sheet_id}/columns",
    response_model=SheetColumnOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_sheet_column(
    task_id: uuid.UUID,
    sheet_id: uuid.UUID,
    body: SheetColumnIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    sheet = await sheets_service.get_sheet_or_404(db, task_id, sheet_id)
    column = await sheets_service.add_column(db, sheet, label=body.label)
    await tasks_service.announce(db, tctx.task, "sheet_column_added")
    return SheetColumnOut(id=str(column.id), label=column.label)


@router.delete(
    "/tasks/{task_id}/sheets/{sheet_id}/columns/{column_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_sheet_column(
    task_id: uuid.UUID,
    sheet_id: uuid.UUID,
    column_id: uuid.UUID,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    column = await sheets_service.get_column_or_404(db, sheet_id, column_id)
    await sheets_service.remove_column(db, column)
    await tasks_service.announce(db, tctx.task, "sheet_column_removed")


@router.put(
    "/tasks/{task_id}/sheets/{sheet_id}/cells/{row_id}/{column_id}", response_model=SheetCellOut
)
async def check_sheet_cell(
    task_id: uuid.UUID,
    sheet_id: uuid.UUID,
    row_id: uuid.UUID,
    column_id: uuid.UUID,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """`PUT`, not `POST`: checking an already-checked cell is not an error,
    the same idempotent-on-purpose shape applying a tag twice already has."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    row = await sheets_service.get_row_or_404(db, sheet_id, row_id)
    column = await sheets_service.get_column_or_404(db, sheet_id, column_id)
    cell, who = await sheets_service.check_cell(db, row, column, user)
    await tasks_service.announce(db, tctx.task, "sheet_cell_checked")
    return SheetCellOut(
        row_id=str(row.id),
        column_id=str(column.id),
        checked_by=PersonOut(id=str(who.id), email=who.email, display_name=who.display_name),
        checked_at=cell.created_at,
    )


@router.delete(
    "/tasks/{task_id}/sheets/{sheet_id}/cells/{row_id}/{column_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def uncheck_sheet_cell(
    task_id: uuid.UUID,
    sheet_id: uuid.UUID,
    row_id: uuid.UUID,
    column_id: uuid.UUID,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    row = await sheets_service.get_row_or_404(db, sheet_id, row_id)
    column = await sheets_service.get_column_or_404(db, sheet_id, column_id)
    await sheets_service.uncheck_cell(db, row, column)
    await tasks_service.announce(db, tctx.task, "sheet_cell_unchecked")


@router.post("/tasks/{task_id}/sheets/{sheet_id}/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_task_sheet(
    task_id: uuid.UUID, sheet_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Clears every cell — the sweep is done, start the next round."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    sheet = await sheets_service.get_sheet_or_404(db, task_id, sheet_id)
    await sheets_service.reset_sheet(db, sheet)
    await tasks_service.announce(db, tctx.task, "sheet_reset")


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
    images = await _image_urls(db, [task])
    pinned = await _pinned_for(db, [task], user)
    recurrence = await _recurrence_for(db, [task], user, ctx)
    return _task_out(
        task,
        tctx.level,
        people=people,
        project_names=names,
        is_owner=tctx.is_owner,
        tags=tags,
        pinned=pinned,
        recurrence=recurrence,
        image_urls=images,
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
    await tasks_service.announce(db, tctx.task, "file_removed")


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
