"""A colleague's profile: when to reach them, and what they're on.

Nothing here is new information. Every part of a profile is something the
viewer could already reach another way, and each part keeps the rule it
already had there — the profile only puts them on one screen:

1. **The person is visible to anyone who shares this organisation with
   them.** Name, role, status line, timezone, working hours and
   out-of-office are all membership-scoped, exactly as
   `services/working_hours.py` and `services/presence.py` already scope
   them. Not a member here reads as 404, like everywhere else.

2. **Their work is visible only as far as the viewer's own task access
   reaches.** The task lists are `access.visible_tasks_stmt` as the
   *viewer*, narrowed to the target with `mine_user_id` — so a hidden task,
   a private project or a revoked grant drops out precisely as it does on
   the task list. There is no "because you're looking at their profile"
   route in; a profile that showed more than the task list would be a hole
   in the access model with a friendly face.

3. **The running timer obeys the time tracker's own rule**: everyone's
   entries on tasks you can see (`time_tracking.entries_in_scope`). A timer
   on a task you can't see isn't "nothing running" either — it simply isn't
   reported, because saying "busy on something you can't see" would leak
   that the task exists.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrganisationMember, OutOfOffice, Task, TimeEntry, User, WorkingHour
from app.models.organisation import STATUS_ACTIVE
from app.services import access
from app.services.organisations import OrgContext

# Enough to answer "what are they on", not a second task list — the profile
# links to the real one for the rest, and says how many there are.
OPEN_LIMIT = 10
CLOSED_LIMIT = 5


@dataclass
class Profile:
    user: User
    member: OrganisationMember
    cells: list[WorkingHour]
    absences: list[OutOfOffice]
    running: tuple[TimeEntry, Task] | None
    open_tasks: list[Task]
    open_total: int
    recently_closed: list[Task]


async def _member(
    db: AsyncSession, ctx: OrgContext, user_id: uuid.UUID
) -> tuple[User, OrganisationMember]:
    row = (
        await db.execute(
            select(User, OrganisationMember)
            .join(OrganisationMember, OrganisationMember.user_id == User.id)
            .where(
                User.id == user_id,
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="not found")
    return row[0], row[1]


async def for_member(
    db: AsyncSession, ctx: OrgContext, viewer: User, user_id: uuid.UUID, *, today: date
) -> Profile:
    target, member = await _member(db, ctx, user_id)
    scope = dict(user_id=viewer.id, org_id=ctx.organisation.id, org_role=ctx.role)

    cells = list(
        (await db.execute(select(WorkingHour).where(WorkingHour.user_id == target.id)))
        .scalars()
        .all()
    )

    # Now and everything ahead, not the dashboard's fortnight: somebody
    # looking at one person is asking about that person's calendar, and a
    # holiday in three weeks is exactly what they'd want to know.
    absences = list(
        (
            await db.execute(
                select(OutOfOffice)
                .where(OutOfOffice.user_id == target.id, OutOfOffice.ends_on >= today)
                .order_by(OutOfOffice.starts_on)
            )
        )
        .scalars()
        .all()
    )

    running_row = (
        await db.execute(
            select(TimeEntry, Task)
            .join(Task, Task.id == TimeEntry.task_id)
            .where(
                TimeEntry.user_id == target.id,
                TimeEntry.ended_at.is_(None),
                Task.id.in_(access.visible_task_ids_stmt(**scope)),
            )
        )
    ).one_or_none()

    open_rows = (
        await db.execute(
            access.paged_tasks_stmt(
                limit=OPEN_LIMIT,
                offset=0,
                mine_user_id=target.id,
                sort="updated_at",
                descending=True,
                **scope,
            )
        )
    ).all()

    closed = (
        access.visible_tasks_stmt(mine_user_id=target.id, include_closed=True, **scope)
        .where(Task.closed_at.isnot(None))
        .order_by(None)
        .order_by(Task.closed_at.desc(), Task.id)
        .limit(CLOSED_LIMIT)
    )

    return Profile(
        user=target,
        member=member,
        cells=cells,
        absences=absences,
        running=(running_row[0], running_row[1]) if running_row else None,
        open_tasks=[t for t, _level, _total in open_rows],
        open_total=open_rows[0][2] if open_rows else 0,
        recently_closed=[t for t, _level in (await db.execute(closed)).all()],
    )
