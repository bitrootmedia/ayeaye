"""Work reports: who worked on what and when, and who is on what right now.

Organisation admins only — see `services/work_reports.py`. Thin: the window,
the clipping and the totals all live in the service.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.api.routers.time import _entry_out
from app.schemas.structure import PersonOut
from app.schemas.work_reports import InProgressTask, RightNowRow, WorkReportOut
from app.services import work_reports

router = APIRouter(prefix="/organisations/{org_id}/reports", tags=["reports"])


@router.get("/work", response_model=WorkReportOut)
async def work_report(
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    since: str | None = None,
    until: str | None = None,
    tz: str | None = None,
    user_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    project_id: uuid.UUID | None = None,
):
    """Time in `since`..`until` (inclusive dates, in `tz`), by day, by hour of
    the week, by person, project and task, plus the newest entries.

    Defaults to the last seven days including today. `user_id` repeats to
    report on several people at once.
    """
    tzinfo = work_reports.zone(tz)
    today = datetime.now(UTC).astimezone(tzinfo).date()
    until_d = _date(until) or today
    since_d = _date(since) or until_d - timedelta(days=6)
    data = await work_reports.report(
        db,
        ctx,
        user,
        since=since_d,
        until=until_d,
        tz_name=tz,
        user_ids=user_id,
        project_id=project_id,
    )
    data["entries"] = [
        _entry_out(r.entry, who=r.user, task_title=r.task.title, project_name=r.project_name)
        for r in data["entries"]
    ]
    return WorkReportOut(**data)


@router.get("/now", response_model=list[RightNowRow])
async def right_now(ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Every active member: their running timer here, their open in-progress
    tasks, and when they last logged time."""
    return [
        RightNowRow(
            user=PersonOut(id=str(r.user.id), email=r.user.email, display_name=r.user.display_name),
            role=r.role,
            running=_entry_out(
                r.running.entry,
                who=r.user,
                task_title=r.running.task.title,
                project_name=r.running.project_name,
            )
            if r.running
            else None,
            in_progress=[
                InProgressTask(
                    id=str(t.id),
                    title=t.title,
                    project_id=str(t.project_id) if t.project_id else None,
                )
                for t in r.in_progress
            ],
            last_active_at=r.last_active_at,
        )
        for r in await work_reports.right_now(db, ctx, user)
    ]


def _date(value: str | None) -> date | None:
    """A date from the URL, or None for anything that isn't one — the same
    "ignore what you can't read" rule as an unknown sort key."""
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None
