"""Dependencies between tasks — informational, never enforced.

"`task_id` depends on `depends_on_task_id`" reads left to right: the
dependent task, then what it's waiting on. Closing a task with open
dependencies still works — the ask was visibility ("to see if it's not
blocking"), not a gate, and this codebase doesn't invent enforcement beyond
what's asked. See CLAUDE.md's Tasks section for the fuller reasoning.

Two rules:

1. **You can only point a dependency at a task you can already open.** Reuses
   `tasks_service.context_for` for the *other* task exactly the way every
   other cross-task reference in this codebase already does — there is no
   second access path written here.
2. **The graph stays a DAG.** One recursive query walks forward from the
   proposed blocker through its own existing dependencies; if the task being
   edited turns up in that reachable set, the new edge would close a cycle
   and is refused with 409 rather than silently accepted.
"""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskDependency, User
from app.models.task import EVENT_DEPENDENCY_ADDED, EVENT_DEPENDENCY_REMOVED
from app.services import access
from app.services import tasks as tasks_service
from app.services.organisations import OrgContext


async def _reachable_from(db: AsyncSession, start_task_id: uuid.UUID) -> set[uuid.UUID]:
    """Everything `start_task_id` transitively depends on already — walking
    forward through existing `depends_on` edges. One recursive query, not a
    query per hop, the same "one statement" discipline every list endpoint
    in this codebase follows once access or a graph gets involved.
    """
    td = TaskDependency.__table__
    base = select(td.c.depends_on_task_id).where(td.c.task_id == start_task_id)
    cte = base.cte("reachable", recursive=True)
    step = select(td.c.depends_on_task_id).where(td.c.task_id == cte.c.depends_on_task_id)
    # A plain UNION (not UNION ALL): dedupes visited nodes, which is also
    # what keeps this from looping forever if the graph were ever somehow
    # inconsistent.
    cte = cte.union(step)
    rows = (await db.execute(select(cte.c.depends_on_task_id))).scalars().all()
    return set(rows)


async def add_dependency(
    db: AsyncSession,
    tctx: tasks_service.TaskContext,
    ctx: OrgContext,
    user: User,
    *,
    depends_on_task_id: uuid.UUID,
) -> TaskDependency:
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    if depends_on_task_id == tctx.task.id:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a task cannot depend on itself",
        )
    # 404s if the caller can't see it — rule 1.
    await tasks_service.context_for(db, ctx, depends_on_task_id, user)

    if tctx.task.id in await _reachable_from(db, depends_on_task_id):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="that would create a dependency cycle",
        )

    row = TaskDependency(
        task_id=tctx.task.id, depends_on_task_id=depends_on_task_id, created_by_user_id=user.id
    )
    db.add(row)
    tasks_service.record(
        db, tctx.task, user, EVENT_DEPENDENCY_ADDED, depends_on_task_id=str(depends_on_task_id)
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="already linked"
        ) from exc
    await db.refresh(row)
    await tasks_service.announce(db, tctx.task, "dependency added")
    return row


async def remove_dependency(
    db: AsyncSession, tctx: tasks_service.TaskContext, user: User, dependency_id: uuid.UUID
) -> None:
    tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")
    row = (
        await db.execute(
            select(TaskDependency).where(
                TaskDependency.id == dependency_id, TaskDependency.task_id == tctx.task.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="dependency not found"
        )
    tasks_service.record(
        db,
        tctx.task,
        user,
        EVENT_DEPENDENCY_REMOVED,
        depends_on_task_id=str(row.depends_on_task_id),
    )
    await db.delete(row)
    await db.commit()
    await tasks_service.announce(db, tctx.task, "dependency removed")


@dataclass
class DependencyEdge:
    dependency_id: uuid.UUID
    other_task_id: uuid.UUID
    # None means the other side is invisible to the caller.
    task: Task | None


async def list_dependencies(
    db: AsyncSession, ctx: OrgContext, user: User, task_id: uuid.UUID
) -> tuple[list[DependencyEdge], list[DependencyEdge]]:
    """Both directions in two small queries plus one batched visibility
    check — never a lookup per row. `depends_on` is what this task is
    waiting on; `blocks` is the reverse, read-only on this screen because
    editing it belongs to the other task's own list.

    Each referenced task resolves through the *caller's* own visibility —
    task-level access can differ between two people looking at the same
    edge — so a dependency on a task this viewer can't see comes back with
    `task=None` rather than leaking its title or status.
    """
    depends_on_rows = (
        (
            await db.execute(
                select(TaskDependency)
                .where(TaskDependency.task_id == task_id)
                .order_by(TaskDependency.id)
            )
        )
        .scalars()
        .all()
    )
    blocks_rows = (
        (
            await db.execute(
                select(TaskDependency)
                .where(TaskDependency.depends_on_task_id == task_id)
                .order_by(TaskDependency.id)
            )
        )
        .scalars()
        .all()
    )

    other_ids = {r.depends_on_task_id for r in depends_on_rows} | {r.task_id for r in blocks_rows}
    tasks_by_id: dict[uuid.UUID, Task] = {}
    if other_ids:
        visible_ids_stmt = access.visible_task_ids_stmt(
            user_id=user.id, org_id=ctx.organisation.id, org_role=ctx.role
        ).where(Task.id.in_(other_ids))
        visible_ids = set((await db.execute(visible_ids_stmt)).scalars().all())
        if visible_ids:
            rows = (await db.execute(select(Task).where(Task.id.in_(visible_ids)))).scalars().all()
            tasks_by_id = {t.id: t for t in rows}

    depends_on = [
        DependencyEdge(
            dependency_id=r.id,
            other_task_id=r.depends_on_task_id,
            task=tasks_by_id.get(r.depends_on_task_id),
        )
        for r in depends_on_rows
    ]
    blocks = [
        DependencyEdge(
            dependency_id=r.id, other_task_id=r.task_id, task=tasks_by_id.get(r.task_id)
        )
        for r in blocks_rows
    ]
    return depends_on, blocks
