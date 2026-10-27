"""Wire shapes for work reports. Seconds, like the rest of time tracking —
the client formats, totals and draws them."""

from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.structure import PersonOut
from app.schemas.time import RollupRow, TimeEntryOut


class TaskRollupRow(RollupRow):
    project_name: str | None = None


class DaySeconds(BaseModel):
    id: str
    seconds: int


class DayRow(BaseModel):
    date: date
    seconds: int
    # Who that day's total is made of, largest first — the chart's tooltip.
    people: list[DaySeconds]


class WorkReportOut(BaseModel):
    since: date
    until: date
    # The zone every date and hour here is in: the viewer's, echoed back so a
    # zone the server didn't recognise is visible as UTC rather than silent.
    tz: str
    total_seconds: int
    by_person: list[RollupRow]
    by_project: list[RollupRow]
    by_task: list[TaskRollupRow]
    by_day: list[DayRow]
    # Seven rows, Monday first, of twenty-four hours each.
    by_hour: list[list[int]]
    entries: list[TimeEntryOut]
    # How many entries the window holds; `entries` is the newest of them.
    entries_total: int


class InProgressTask(BaseModel):
    id: str
    title: str
    project_id: str | None


class RightNowRow(BaseModel):
    user: PersonOut
    role: str
    running: TimeEntryOut | None
    in_progress: list[InProgressTask]
    last_active_at: datetime | None
