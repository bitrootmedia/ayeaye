"""Work reports: who worked on what, when, and what they're on right now.

**Organisation admins only.** Everyone can already see the time logged on
the tasks they can see (`/time`) — this screen is a different question,
"how is the team's week going", and it is asked about people rather than
about work. That makes it an admin's question, the same rank that manages
members. Gated with a 403, not a 404: the caller can see the organisation,
just not at this level.

Three rules:

1. **It composes `time_tracking.entries_in_scope`, and does not widen it.**
   An admin already sees every task in the organisation except somebody
   else's *hidden* one, and a report is not the place to carve a second
   exception into that (`services/access.py` says why there is only one).
   Hours on a hidden task are missing from the report exactly as the task is
   missing from the board. The alternative — counting them under a
   placeholder — tells an admin a hidden task exists, which is what hiding
   it was for.

2. **Time is clipped to the window, and spread across the hours it covers.**
   An entry from 23:30 to 01:15 is 30 minutes on one day and 75 on the next,
   in three hour-cells of the activity grid. Bucketing by `started_at` alone
   would put a three-hour block in the hour it began and make every chart
   lie about *when*. This is `spread`, a pure function with its own tests.

3. **"When" is the viewer's wall clock**, passed as `tz`. A person's own
   zone would be truer for one person and incoherent for a team spread over
   three of them; the viewer's is the one a chart can be read in.

The arithmetic happens in Python over rows fetched in **one** statement —
access is resolved in SQL, as everywhere, and an admin's window over a team
is a few thousand rows at most. Running entries count up to now, as the
rollups on `/time` already do.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Task, TimeEntry, User
from app.models.organisation import STATUS_ACTIVE, OrganisationMember
from app.models.task import STATUS_IN_PROGRESS
from app.services import access
from app.services.organisations import OrgContext
from app.services.time_tracking import entries_in_scope

# A year and a day, so "this time last year" fits. Past that the grid is
# averaging seasons and the entry list is a data export — which exists.
MAX_RANGE_DAYS = 366
# The newest entries in the window. The totals and charts cover all of them;
# the list is for reading, and nobody reads five hundred rows.
ENTRY_LIMIT = 500
# What somebody "is on" beyond the running timer: their open, in-progress
# tasks, most recently touched first.
IN_PROGRESS_LIMIT = 5


def require_admin(ctx: OrgContext) -> None:
    ctx.require(
        access.administers_organisation(ctx.role),
        "work reports are for organisation admins",
    )


# --- pure. no database, no request. -----------------------------------------


def zone(tz_name: str | None) -> ZoneInfo:
    """The viewer's zone, or UTC for a name that isn't one — a bad `tz` from
    a URL somebody edited should still draw a chart, not an error."""
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def window(
    since: date, until: date, tz: ZoneInfo, *, now: datetime
) -> tuple[datetime, datetime]:
    """`since`..`until` inclusive, as the two instants bounding it.

    Ends at now, not at midnight: a week that includes today hasn't finished,
    and a running timer must not be counted into the future.
    """
    if until < since:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="that range ends before it starts",
        )
    if (until - since).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"a report covers at most {MAX_RANGE_DAYS} days",
        )
    start = datetime.combine(since, time.min, tzinfo=tz)
    end = datetime.combine(until + timedelta(days=1), time.min, tzinfo=tz)
    return start, min(end, now)


def spread(
    started_at: datetime,
    ended_at: datetime | None,
    *,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    now: datetime,
):
    """Yield `(local hour, seconds)` for every wall-clock hour an entry covers
    inside `[start, end)`. Seconds are fractional: truncating each slice would
    lose up to a second per hour, and a 2h 30m entry would total 2h 29m.

    Steps by local hour boundaries, converted back to UTC to find the next
    one, so a zone that is half an hour off UTC still lands on its own hours,
    and a DST change is simply an hour that has a different label.
    """
    lo = max(started_at, start)
    hi = min(ended_at or now, end)
    while lo < hi:
        local = lo.astimezone(tz)
        floor = local.replace(minute=0, second=0, microsecond=0)
        boundary = floor.astimezone(UTC) + timedelta(hours=1)
        step = min(boundary, hi)
        yield floor, (step - lo).total_seconds()
        lo = step


@dataclass
class Row:
    """One entry as the report reads it."""

    entry: TimeEntry
    user: User
    task: Task
    project_id: uuid.UUID | None
    project_name: str | None


def _name(user: User) -> str:
    return user.display_name or user.email


def aggregate(
    rows: list[Row], *, start: datetime, end: datetime, tz: ZoneInfo, now: datetime
) -> dict:
    """Every total the screen draws, from one pass over the rows.

    Each figure is the clipped, spread seconds, so the day chart, the grid
    and the three rollups always add up to the same total.
    """
    total = 0.0
    people: dict[uuid.UUID, list] = {}
    projects: dict[uuid.UUID | None, list] = {}
    tasks: dict[uuid.UUID, list] = {}
    days: dict[date, dict[uuid.UUID, float]] = defaultdict(lambda: defaultdict(float))
    grid = [[0.0] * 24 for _ in range(7)]

    for row in rows:
        seconds = 0.0
        for hour, s in spread(
            row.entry.started_at, row.entry.ended_at, start=start, end=end, tz=tz, now=now
        ):
            seconds += s
            days[hour.date()][row.user.id] += s
            grid[hour.weekday()][hour.hour] += s
        if not seconds:
            continue
        total += seconds
        people.setdefault(row.user.id, [_name(row.user), 0])[1] += seconds
        # Loose tasks are grouped under no project, not dropped — that time
        # was still spent.
        projects.setdefault(row.project_id, [row.project_name or "No project", 0])[1] += seconds
        tasks.setdefault(row.task.id, [row.task.title, row.project_name, 0])[2] += seconds

    def ranked(d: dict, shape):
        return sorted((shape(k, v) for k, v in d.items()), key=lambda r: -r["seconds"])

    # Every day of the window, empty ones included: a gap in a bar chart is
    # information, and a chart that skips it squeezes Monday against Friday.
    by_day = []
    cursor = start.astimezone(tz).date()
    last = (end - timedelta(microseconds=1)).astimezone(tz).date()
    while cursor <= last:
        per = days.get(cursor, {})
        by_day.append(
            {
                "date": cursor,
                "seconds": round(sum(per.values())),
                "people": sorted(
                    ({"id": str(k), "seconds": round(v)} for k, v in per.items()),
                    key=lambda r: -r["seconds"],
                ),
            }
        )
        cursor += timedelta(days=1)

    return {
        "total_seconds": round(total),
        "by_person": ranked(
            people, lambda k, v: {"id": str(k), "name": v[0], "seconds": round(v[1])}
        ),
        "by_project": ranked(
            projects,
            lambda k, v: {"id": str(k) if k else None, "name": v[0], "seconds": round(v[1])},
        ),
        "by_task": ranked(
            tasks,
            lambda k, v: {
                "id": str(k),
                "name": v[0],
                "project_name": v[1],
                "seconds": round(v[2]),
            },
        )[:20],
        "by_day": by_day,
        "by_hour": [[round(s) for s in row] for row in grid],
    }


# --- reads -------------------------------------------------------------------


async def report(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    *,
    since: date,
    until: date,
    tz_name: str | None,
    user_ids: list[uuid.UUID] | None = None,
    project_id: uuid.UUID | None = None,
) -> dict:
    require_admin(ctx)
    tz = zone(tz_name)
    now = datetime.now(UTC)
    start, end = window(since, until, tz, now=now)

    stmt = (
        select(TimeEntry, User, Task, Project.id, Project.name)
        .join(User, User.id == TimeEntry.user_id)
        .join(Task, Task.id == TimeEntry.task_id)
        .outerjoin(Project, Project.id == Task.project_id)
        .where(
            entries_in_scope(user_id=user.id, ctx=ctx),
            # Overlaps the window — an entry that began before it still
            # counts for the part inside it.
            TimeEntry.started_at < end,
            func.coalesce(TimeEntry.ended_at, func.now()) > start,
        )
        .order_by(TimeEntry.started_at.desc())
    )
    if user_ids:
        stmt = stmt.where(TimeEntry.user_id.in_(user_ids))
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)

    rows = [Row(e, u, t, pid, pname) for e, u, t, pid, pname in (await db.execute(stmt)).all()]
    data = aggregate(rows, start=start, end=end, tz=tz, now=now)
    data.update(
        since=since,
        until=until,
        tz=tz.key,
        entries=rows[:ENTRY_LIMIT],
        entries_total=len(rows),
    )
    return data


@dataclass
class NowRow:
    user: User
    role: str
    running: Row | None
    in_progress: list[Task]
    last_active_at: datetime | None


async def right_now(db: AsyncSession, ctx: OrgContext, user: User) -> list[NowRow]:
    """Every active member, with what they're timing, what they have in
    progress, and when they last logged anything.

    Four statements, one per question, never one per person. Each composes
    the same access the report does: a timer running on a task the admin
    can't see — somebody's hidden one, or one in another organisation —
    reads as nothing running, the same as rule 1 above.
    """
    require_admin(ctx)
    org_id = ctx.organisation.id

    members = (
        await db.execute(
            select(User, OrganisationMember.role)
            .join(OrganisationMember, OrganisationMember.user_id == User.id)
            .where(
                OrganisationMember.organisation_id == org_id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).all()

    running = {
        e.user_id: Row(e, u, t, pid, pname)
        for e, u, t, pid, pname in (
            await db.execute(
                select(TimeEntry, User, Task, Project.id, Project.name)
                .join(User, User.id == TimeEntry.user_id)
                .join(Task, Task.id == TimeEntry.task_id)
                .outerjoin(Project, Project.id == Task.project_id)
                .where(TimeEntry.ended_at.is_(None), entries_in_scope(user_id=user.id, ctx=ctx))
            )
        ).all()
    }

    in_progress: dict[uuid.UUID, list[Task]] = defaultdict(list)
    for task in (
        await db.execute(
            select(Task)
            .where(
                Task.id.in_(
                    access.visible_task_ids_stmt(user_id=user.id, org_id=org_id, org_role=ctx.role)
                ),
                Task.status == STATUS_IN_PROGRESS,
                Task.closed_at.is_(None),
            )
            .order_by(Task.updated_at.desc())
        )
    ).scalars():
        if len(in_progress[task.owner_user_id]) < IN_PROGRESS_LIMIT:
            in_progress[task.owner_user_id].append(task)

    last_active = dict(
        (
            await db.execute(
                select(
                    TimeEntry.user_id,
                    func.max(func.coalesce(TimeEntry.ended_at, func.now())),
                )
                .where(entries_in_scope(user_id=user.id, ctx=ctx))
                .group_by(TimeEntry.user_id)
            )
        ).all()
    )

    out = [
        NowRow(
            user=u,
            role=role,
            running=running.get(u.id),
            in_progress=in_progress.get(u.id, []),
            last_active_at=last_active.get(u.id),
        )
        for u, role in members
    ]
    # Busy first, then whoever was active most recently, then by name — the
    # order the question "who is on what" is read in.
    out.sort(
        key=lambda r: (
            r.running is None,
            -(r.last_active_at.timestamp() if r.last_active_at else 0),
            _name(r.user).lower(),
        )
    )
    return out
