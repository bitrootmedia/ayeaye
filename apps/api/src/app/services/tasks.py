"""Tasks: the workflow, the history, and who gets told.

The rules at the top are pure and tested without infrastructure, the same way
`organisations.py` and `access.py` are. They are the ones that fail *silently*
if they're wrong — a missing notification, a re-notification, an event that
never got written — so they're worth pinning individually.

Five rules, from PLAN.md §5 and the product decisions in CLAUDE.md:

1. **Only the owner closes.** A non-owner who can see the task gets 403, not
   404 — they can see it, they just may not do that.
2. **Status and open/closed are independent.** Closing is not a status, and a
   task can be closed from any status.
3. **Action-required notifies on the transition, not on the write.** Setting
   it to the person who already has it must not re-notify; a save button that
   pings someone every time is a save button people stop pressing.
4. **Changing the owner is an event, and the new owner is told.**
5. **Every one of these writes a `task_events` row**, in the same transaction
   as the change. That table *is* the history — don't build a second one.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    OrganisationMember,
    Project,
    Task,
    TaskEvent,
    TaskGrant,
    Team,
    User,
)
from app.models.notification import (
    KIND_ACTION_REQUIRED,
    KIND_TASK_CLOSED,
    KIND_TASK_OWNER,
    KIND_TASK_SHARED,
)
from app.models.organisation import STATUS_ACTIVE
from app.models.structure import GRANT_LEVELS
from app.models.task import (
    EVENT_ACCESS_GRANTED,
    EVENT_ACCESS_REVOKED,
    EVENT_ACTION_REQUIRED_CLEARED,
    EVENT_ACTION_REQUIRED_SET,
    EVENT_CLOSED,
    EVENT_CREATED,
    EVENT_DUE_CHANGED,
    EVENT_HIDDEN,
    EVENT_MOVED,
    EVENT_OWNER_CHANGED,
    EVENT_PRIORITY_CHANGED,
    EVENT_RENAMED,
    EVENT_REOPENED,
    EVENT_STATUS_CHANGED,
    EVENT_UNHIDDEN,
    PRIORITIES,
    PRIORITY_NORMAL,
    STATUSES,
)
from app.realtime import events as realtime
from app.services import access, notifications, richtext
from app.services.organisations import OrgContext

# --- pure rules. no database, no request. -----------------------------------


def is_valid_status(status: str) -> bool:
    return status in STATUSES


def is_valid_priority(priority: str) -> bool:
    return priority in PRIORITIES


def can_close(*, level: str, is_owner: bool) -> bool:
    """Rule 1. Only the owner — not an editor, not the person being asked to
    act. Organisation admins resolve to `owner` level, so they qualify: that is
    the escape hatch for a task whose owner has left."""
    return is_owner or access.can_administer(level)


def can_edit(level: str) -> bool:
    return access.can_write(level)


def can_manage_access(*, level: str, is_owner: bool) -> bool:
    """Sharing a task, and handing it over. Same rule as closing."""
    return is_owner or access.can_administer(level)


def can_hide(*, is_owner: bool) -> bool:
    """**The actual owner, and nobody else — not even an organisation admin.**

    Deliberately not `can_close`'s rule. An admin hiding a task they don't own
    would hide it *from themselves*, since hiding leaves exactly one person who
    can see it and that person is the owner. A control whose only effect is to
    make the thing you were looking at disappear is not a feature.

    It also means an admin cannot un-hide someone else's task. That is correct
    and it is the point: they can't see it to find it. The recovery path when
    the owner leaves is offboarding, which reassigns ownership.
    """
    return is_owner


def should_notify_action_required(
    *, previous: uuid.UUID | None, incoming: uuid.UUID | None, actor: uuid.UUID
) -> bool:
    """Rule 3: notify on the *transition*, and never about yourself.

    Three cases that must not notify, each of which a naive "if incoming: send"
    would get wrong:

    * setting it to whoever already has it — the commonest accidental re-ping,
      because every save resubmits the whole form;
    * clearing it;
    * putting it on yourself, which you already know about.
    """
    if incoming is None or incoming == previous:
        return False
    return incoming != actor


def describe_status(status: str) -> str:
    """For event text and email subjects. Kept next to the tuple it maps."""
    return {
        "todo": "To do",
        "in_progress": "In progress",
        "on_hold": "On hold",
        "review": "In review",
        "blocker": "Blocked",
    }.get(status, status)


# --- context ------------------------------------------------------------------


@dataclass(frozen=True)
class TaskContext:
    task: Task
    level: str
    is_owner: bool

    def require(self, allowed: bool, detail: str) -> None:
        """403. They can see the task; they just may not do this to it."""
        if not allowed:
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=detail)


async def context_for(
    db: AsyncSession, ctx: OrgContext, task_id: uuid.UUID, user: User
) -> TaskContext:
    row = (
        await db.execute(
            access.visible_task_stmt(
                user_id=user.id,
                org_id=ctx.organisation.id,
                org_role=ctx.role,
                task_id=task_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="task not found")
    task, rank = row
    return TaskContext(
        task=task,
        level=access.level_name(rank) or "",
        is_owner=task.owner_user_id == user.id,
    )


# --- history --------------------------------------------------------------------


def record(db: AsyncSession, task: Task, actor: User, kind: str, **data) -> None:
    """Append one history row. Not committed here — the caller commits it in
    the same transaction as the change, so the two can never disagree."""
    db.add(TaskEvent(task_id=task.id, actor_user_id=actor.id, kind=kind, data=data))


async def list_events(
    db: AsyncSession, task_id: uuid.UUID
) -> list[tuple[TaskEvent, User | None]]:
    rows = (
        await db.execute(
            select(TaskEvent, User)
            .outerjoin(User, User.id == TaskEvent.actor_user_id)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.id)
        )
    ).all()
    return [(event, actor) for event, actor in rows]


# --- reads ------------------------------------------------------------------------


async def list_visible(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    **filters,
) -> list[tuple[Task, str]]:
    """Everything matching, unbounded. `**filters` goes straight through to
    `visible_tasks_stmt` — one place defines what a task list can be narrowed
    or sorted by, and this and `list_page` can\'t drift apart."""
    rows = (
        await db.execute(
            access.visible_tasks_stmt(
                user_id=user.id,
                org_id=ctx.organisation.id,
                org_role=ctx.role,
                **filters,
            )
        )
    ).all()
    return [(task, access.level_name(rank) or "") for task, rank in rows]


async def list_page(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    *,
    limit: int,
    offset: int,
    **filters,
) -> tuple[list[tuple[Task, str]], int]:
    """One page, and the total. Returns `([], 0)` for a page past the end."""
    rows = (
        await db.execute(
            access.paged_tasks_stmt(
                limit=limit,
                offset=offset,
                user_id=user.id,
                org_id=ctx.organisation.id,
                org_role=ctx.role,
                **filters,
            )
        )
    ).all()
    total = int(rows[0][2]) if rows else 0
    return [(task, access.level_name(rank) or "") for task, rank, _ in rows], total


async def board(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    *,
    group_by: str,
    per_group: int,
    project_id: uuid.UUID | None = None,
    loose_only: bool = False,
    include_closed: bool = False,
    tag_id: uuid.UUID | None = None,
) -> list[tuple[Task, str, int]]:
    """The board, bounded per column. Returns `(task, level, column_total)`."""
    rows = (
        await db.execute(
            access.board_stmt(
                user_id=user.id,
                org_id=ctx.organisation.id,
                org_role=ctx.role,
                group_by=group_by,
                per_group=per_group,
                project_id=project_id,
                loose_only=loose_only,
                include_closed=include_closed,
                tag_id=tag_id,
            )
        )
    ).all()
    return [(task, access.level_name(rank) or "", int(total)) for task, rank, total in rows]


async def _member_or_404(db: AsyncSession, ctx: OrgContext, user_id: uuid.UUID) -> None:
    found = (
        await db.execute(
            select(OrganisationMember.id).where(
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.user_id == user_id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="that person is not a member of this organisation",
        )


async def _writable_project_or_404(
    db: AsyncSession, ctx: OrgContext, user: User, project_id: uuid.UUID
) -> Project:
    """You may only put a task in a project you could edit.

    Read access is not enough: filing work into someone's project changes what
    they see, and a viewer shouldn't be able to do that.
    """
    row = (
        await db.execute(
            access.visible_project_stmt(
                user_id=user.id,
                org_id=ctx.organisation.id,
                org_role=ctx.role,
                project_id=project_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="project not found")
    project, rank = row
    if not access.can_write(access.level_name(rank)):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="you have read-only access to that project",
        )
    return project


# --- writes -------------------------------------------------------------------------


async def create(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    *,
    title: str,
    description: str | None = None,
    project_id: uuid.UUID | None = None,
    status: str = "todo",
    priority: str = PRIORITY_NORMAL,
    owner_user_id: uuid.UUID | None = None,
    action_required_user_id: uuid.UUID | None = None,
    due_on: date | None = None,
) -> Task:
    """Create a task. **You own it unless you say otherwise.**"""
    title = title.strip()
    if not title:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a task needs a title"
        )
    if not is_valid_status(status):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of {', '.join(STATUSES)}",
        )
    if not is_valid_priority(priority):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"priority must be one of {', '.join(PRIORITIES)}",
        )
    if project_id is not None:
        await _writable_project_or_404(db, ctx, user, project_id)
    if owner_user_id is not None and owner_user_id != user.id:
        await _member_or_404(db, ctx, owner_user_id)
    if action_required_user_id is not None:
        await _member_or_404(db, ctx, action_required_user_id)

    task = Task(
        organisation_id=ctx.organisation.id,
        project_id=project_id,
        title=title,
        description=richtext.sanitise(description),
        status=status,
        priority=priority,
        owner_user_id=owner_user_id or user.id,
        action_required_user_id=action_required_user_id,
        created_by_user_id=user.id,
        due_on=due_on,
    )
    db.add(task)
    await db.flush()

    record(db, task, user, EVENT_CREATED, title=title, loose=project_id is None)
    if action_required_user_id:
        record(db, task, user, EVENT_ACTION_REQUIRED_SET, user_id=str(action_required_user_id))
    await db.commit()
    await db.refresh(task)

    # Notify after the commit: a nudge about a task that then failed to save is
    # worse than a nudge that arrives a moment late.
    if should_notify_action_required(
        previous=None, incoming=action_required_user_id, actor=user.id
    ):
        await notifications.notify(
            db,
            user_id=action_required_user_id,
            kind=KIND_ACTION_REQUIRED,
            title=f"{_who(user)} needs you on “{title}”",
            link_path=f"/orgs/{ctx.organisation.id}/tasks/{task.id}",
        )
    if task.owner_user_id != user.id:
        await notifications.notify(
            db,
            user_id=task.owner_user_id,
            kind=KIND_TASK_OWNER,
            title=f"{_who(user)} made you the owner of “{title}”",
            link_path=f"/orgs/{ctx.organisation.id}/tasks/{task.id}",
        )
    return task


def _who(user: User) -> str:
    return user.display_name or user.email or "Someone"


async def announce(db: AsyncSession, task: Task, change: str) -> None:
    """Record that a task changed: stamp `updated_at`, then tell every screen.

    **One function for both, deliberately.** They have the same trigger and
    the same set of call sites, and splitting them means the day somebody adds
    a seventh kind of change they remember one and forget the other. The rule
    is a single sentence: *if it writes to a task, it announces.*

    **`updated_at` is "last activity", not "last row update".** A comment, a
    file, a tag, an hour logged — none of those touch the `tasks` row, so
    without this the column answers a question nobody asks. It is a sortable
    column on the list view precisely so people can find what has been moving.

    **The exception is a private note**, which never calls this. A note nobody
    else can read must not announce itself by bumping a timestamp everybody
    can see — that would leak, through the back door, exactly what the feature
    promises to keep. Reminders are personal in the same way and are left out
    for the same reason.

    **After the commit, never before.** A ping about a change that then failed
    to save sends everyone to refetch the old state and believe it is new.
    """
    # Python-side rather than `func.now()`: the in-memory instance is what the
    # response is built from, and a SQL function would leave it holding an
    # expression until something refreshed it.
    task.updated_at = datetime.now(UTC)
    await db.commit()
    await realtime.publish_task_changed(
        task_id=str(task.id), organisation_id=str(task.organisation_id), change=change
    )


async def update(
    db: AsyncSession,
    tctx: TaskContext,
    ctx: OrgContext,
    user: User,
    *,
    fields: dict,
) -> Task:
    """Apply a partial update, writing one history row per real change.

    Takes an already-filtered dict of set fields rather than a pile of
    sentinels, because "absent" and "explicitly null" mean different things for
    `project_id`, `action_required_user_id` and `due_on` — all three are
    legitimately clearable.
    """
    task = tctx.task
    tctx.require(can_edit(tctx.level), "you have read-only access to this task")

    notify_action_required: uuid.UUID | None = None
    notify_new_owner: uuid.UUID | None = None

    if "title" in fields:
        title = (fields["title"] or "").strip()
        if not title:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="a task needs a title",
            )
        if title != task.title:
            record(db, task, user, EVENT_RENAMED, was=task.title, now=title)
            task.title = title

    if "description" in fields:
        # Sanitised on the way in, always. The editor produces tidy HTML and
        # that is irrelevant — anyone can PATCH a `<script>` with curl.
        task.description = richtext.sanitise(fields["description"])

    if "status" in fields and fields["status"] != task.status:
        status = fields["status"]
        if not is_valid_status(status):
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"status must be one of {', '.join(STATUSES)}",
            )
        record(db, task, user, EVENT_STATUS_CHANGED, was=task.status, now=status)
        task.status = status

    if "priority" in fields and fields["priority"] != task.priority:
        priority = fields["priority"]
        if not is_valid_priority(priority):
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"priority must be one of {', '.join(PRIORITIES)}",
            )
        record(db, task, user, EVENT_PRIORITY_CHANGED, was=task.priority, now=priority)
        task.priority = priority

    if "due_on" in fields and fields["due_on"] != task.due_on:
        record(
            db,
            task,
            user,
            EVENT_DUE_CHANGED,
            was=task.due_on.isoformat() if task.due_on else None,
            now=fields["due_on"].isoformat() if fields["due_on"] else None,
        )
        task.due_on = fields["due_on"]

    if "position" in fields:
        task.position = int(fields["position"])

    if "project_id" in fields and fields["project_id"] != task.project_id:
        new_project = fields["project_id"]
        if new_project is not None:
            await _writable_project_or_404(db, ctx, user, new_project)
        record(
            db,
            task,
            user,
            EVENT_MOVED,
            was=str(task.project_id) if task.project_id else None,
            now=str(new_project) if new_project else None,
        )
        task.project_id = new_project

    if "action_required_user_id" in fields:
        incoming = fields["action_required_user_id"]
        previous = task.action_required_user_id
        if incoming != previous:
            if incoming is not None:
                # The mirror of the guard in `set_hidden`: you cannot ask
                # someone to act on a task they are not allowed to open.
                if task.hidden_at is not None and incoming != user.id:
                    raise HTTPException(
                        status_code=http_status.HTTP_409_CONFLICT,
                        detail="this task is hidden — un-hide it before asking someone to act",
                    )
                await _member_or_404(db, ctx, incoming)
                record(db, task, user, EVENT_ACTION_REQUIRED_SET, user_id=str(incoming))
            else:
                record(db, task, user, EVENT_ACTION_REQUIRED_CLEARED)
            task.action_required_user_id = incoming
        # Rule 3: computed from the transition, so a resubmitted form that
        # names the same person again sends nothing.
        if should_notify_action_required(previous=previous, incoming=incoming, actor=user.id):
            notify_action_required = incoming

    if "owner_user_id" in fields and fields["owner_user_id"] != task.owner_user_id:
        # Handing a task over is not an edit — it decides who may close it.
        tctx.require(
            can_manage_access(level=tctx.level, is_owner=tctx.is_owner),
            "only the task owner can hand it over",
        )
        new_owner = fields["owner_user_id"]
        if new_owner is None:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="a task needs an owner",
            )
        await _member_or_404(db, ctx, new_owner)
        record(db, task, user, EVENT_OWNER_CHANGED, was=str(task.owner_user_id), now=str(new_owner))
        task.owner_user_id = new_owner
        if new_owner != user.id:
            notify_new_owner = new_owner

    await db.commit()
    await db.refresh(task)

    await announce(db, task, "updated")

    link = f"/orgs/{ctx.organisation.id}/tasks/{task.id}"
    if notify_action_required:
        await notifications.notify(
            db,
            user_id=notify_action_required,
            kind=KIND_ACTION_REQUIRED,
            title=f"{_who(user)} needs you on “{task.title}”",
            link_path=link,
        )
    if notify_new_owner:
        await notifications.notify(
            db,
            user_id=notify_new_owner,
            kind=KIND_TASK_OWNER,
            title=f"{_who(user)} made you the owner of “{task.title}”",
            link_path=link,
        )
    return task


async def set_open(
    db: AsyncSession, tctx: TaskContext, ctx: OrgContext, user: User, *, closed: bool
) -> Task:
    """Close or reopen. Rule 1: the owner, or an organisation admin.

    403 rather than 404 on purpose — they can see the task, so pretending it
    doesn't exist would be a worse lie than telling them they can't close it.
    """
    task = tctx.task
    tctx.require(
        can_close(level=tctx.level, is_owner=tctx.is_owner),
        "only the task owner can close or reopen this",
    )
    if closed == (task.closed_at is not None):
        return task

    if closed:
        task.closed_at = func.now()
        task.closed_by_user_id = user.id
        # Closing does NOT change the status. "Closed while still blocked" is a
        # real and useful thing to be able to say.
        record(db, task, user, EVENT_CLOSED, status=task.status)
    else:
        task.closed_at = None
        task.closed_by_user_id = None
        record(db, task, user, EVENT_REOPENED)
    await db.commit()
    await db.refresh(task)
    await announce(db, task, "closed" if closed else "reopened")

    # Tell the person who was asked to act, and the previous owner if it isn't
    # the closer — the two people most likely to be waiting on it.
    if closed:
        for recipient in {task.action_required_user_id, task.owner_user_id} - {user.id, None}:
            await notifications.notify(
                db,
                user_id=recipient,
                kind=KIND_TASK_CLOSED,
                title=f"{_who(user)} closed “{task.title}”",
                link_path=f"/orgs/{ctx.organisation.id}/tasks/{task.id}",
            )
    return task


async def set_hidden(
    db: AsyncSession, tctx: TaskContext, user: User, *, hidden: bool
) -> Task:
    """Hide a task from everyone but its owner, or bring it back.

    Two guards, and the second is the interesting one:

    * **only the owner**, per `can_hide` — an admin doing this would be hiding
      the task from themselves.
    * **not while somebody else is being asked to act on it.** Being named
      action-required is one of the six routes in; hiding would revoke it
      silently, and the person would be left with a notification that 404s.
      Refused with a message rather than quietly clearing the flag, because
      un-asking a colleague is a decision the owner should make on purpose.

    Grants are left in place. Hiding suspends them; un-hiding restores every
    one, with nothing to re-grant and no way to forget who used to have access.
    """
    task = tctx.task
    tctx.require(can_hide(is_owner=tctx.is_owner), "only the task owner can hide this")
    if hidden == (task.hidden_at is not None):
        return task

    if hidden and task.action_required_user_id not in (None, user.id):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="clear the action required first — hiding it would take that away silently",
        )

    if hidden:
        task.hidden_at = func.now()
        record(db, task, user, EVENT_HIDDEN)
    else:
        task.hidden_at = None
        record(db, task, user, EVENT_UNHIDDEN)
    await db.commit()
    await db.refresh(task)
    # Watchers who just lost access get a 404 from their refetch, which is how
    # their screen learns to say so. That is the event doing its job, not a
    # leak — it carries nothing but the id they were already looking at.
    await announce(db, task, "hidden" if hidden else "unhidden")
    return task


async def delete(db: AsyncSession, tctx: TaskContext) -> None:
    tctx.require(
        can_manage_access(level=tctx.level, is_owner=tctx.is_owner),
        "only the task owner can delete this",
    )
    await db.delete(tctx.task)
    await db.commit()


# --- per-task grants ------------------------------------------------------------


async def list_grants(
    db: AsyncSession, task_id: uuid.UUID
) -> list[tuple[TaskGrant, User | None, Team | None]]:
    rows = (
        await db.execute(
            select(TaskGrant, User, Team)
            .outerjoin(User, User.id == TaskGrant.user_id)
            .outerjoin(Team, Team.id == TaskGrant.team_id)
            .where(TaskGrant.task_id == task_id)
            .order_by(TaskGrant.id)
        )
    ).all()
    return [(grant, u, t) for grant, u, t in rows]


async def grant(
    db: AsyncSession,
    tctx: TaskContext,
    ctx: OrgContext,
    user: User,
    *,
    user_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
    level: str,
) -> TaskGrant:
    """Share one task, on top of whatever its project already grants.

    Additive only. You cannot use this to take access away from someone who has
    it through the project — that would be a deny rule.
    """
    tctx.require(
        can_manage_access(level=tctx.level, is_owner=tctx.is_owner),
        "only the task owner can change who has access",
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
        await _member_or_404(db, ctx, user_id)
    else:
        found = (
            await db.execute(
                select(Team.id).where(
                    Team.id == team_id, Team.organisation_id == ctx.organisation.id
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="team not found")

    row = TaskGrant(
        task_id=tctx.task.id,
        user_id=user_id,
        team_id=team_id,
        level=level,
        granted_by_user_id=user.id,
    )
    db.add(row)
    record(
        db,
        tctx.task,
        user,
        EVENT_ACCESS_GRANTED,
        user_id=str(user_id) if user_id else None,
        team_id=str(team_id) if team_id else None,
        level=level,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="they already have access — change the level instead",
        ) from exc
    await db.refresh(row)
    await announce(db, tctx.task, "shared")

    if user_id and user_id != user.id:
        await notifications.notify(
            db,
            user_id=user_id,
            kind=KIND_TASK_SHARED,
            title=f"{_who(user)} shared “{tctx.task.title}” with you",
            link_path=f"/orgs/{ctx.organisation.id}/tasks/{tctx.task.id}",
        )
    return row


async def get_grant(db: AsyncSession, task_id: uuid.UUID, grant_id: uuid.UUID) -> TaskGrant:
    row = (
        await db.execute(
            select(TaskGrant).where(TaskGrant.id == grant_id, TaskGrant.task_id == task_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="grant not found")
    return row


async def revoke(db: AsyncSession, tctx: TaskContext, user: User, row: TaskGrant) -> None:
    tctx.require(
        can_manage_access(level=tctx.level, is_owner=tctx.is_owner),
        "only the task owner can change who has access",
    )
    record(
        db,
        tctx.task,
        user,
        EVENT_ACCESS_REVOKED,
        user_id=str(row.user_id) if row.user_id else None,
        team_id=str(row.team_id) if row.team_id else None,
    )
    await db.delete(row)
    await db.commit()
    await announce(db, tctx.task, "unshared")


# --- offboarding ------------------------------------------------------------------


async def reassign_owned_tasks(
    db: AsyncSession, *, org_id: uuid.UUID, from_user_id: uuid.UUID, to_user_id: uuid.UUID
) -> int:
    """Hand every task owned by someone leaving to someone who is staying.

    PLAN.md §5 asked whether removing a member should be blocked or should
    reassign. **Reassign**, because blocking makes offboarding a puzzle: you'd
    have to find every task a departing colleague owns before you can remove
    them, with no screen that lists them. `tasks.owner_user_id` is RESTRICT, so
    without this the DELETE simply fails with a foreign-key error and no
    explanation a human could act on.

    Also clears them from `action_required`, which is SET NULL anyway — doing
    it here means the task shows up as needing an owner's attention rather than
    silently losing its flag.
    """
    tasks = (
        (
            await db.execute(
                select(Task).where(
                    Task.organisation_id == org_id, Task.owner_user_id == from_user_id
                )
            )
        )
        .scalars()
        .all()
    )
    for task in tasks:
        task.owner_user_id = to_user_id
        db.add(
            TaskEvent(
                task_id=task.id,
                actor_user_id=None,
                kind=EVENT_OWNER_CHANGED,
                data={
                    "was": str(from_user_id),
                    "now": str(to_user_id),
                    "reason": "previous owner left the organisation",
                },
            )
        )
    return len(tasks)
