"""Wire shapes for time tracking.

Durations go over the wire as **seconds**, and are formatted for display by
the client. A server-formatted "1h 30m" would be a string the UI can't total,
sort or re-render in another unit.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.structure import PersonOut


class TimeEntryOut(BaseModel):
    id: str
    task_id: str
    task_title: str | None = None
    project_name: str | None = None
    user: PersonOut | None
    started_at: datetime
    # None means running. The client ticks the elapsed value itself rather than
    # polling — a clock that only moves when the network does looks broken.
    ended_at: datetime | None
    seconds: int
    note: str | None
    edited_at: datetime | None


class TimerOut(BaseModel):
    """The caller's running timer, or nothing.

    Carries the organisation so the header can link to it: there is one timer
    per person across the whole installation, and it may well be running
    against a task in an organisation you don't currently have open.
    """

    entry: TimeEntryOut | None
    organisation_id: str | None = None


class StartTimerOut(BaseModel):
    entry: TimeEntryOut
    # What starting this one displaced, if anything. Surfaced so the UI can say
    # so out loud rather than silently stopping the previous task's clock.
    stopped: TimeEntryOut | None = None


class ManualEntryIn(BaseModel):
    """A duration, not two timestamps.

    "I spent 90 minutes on this" is how people think about time they've already
    spent, and it removes end-before-start mistakes at the door. `started_at`
    is only needed to backdate.
    """

    minutes: int = Field(gt=0, le=24 * 60)
    started_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class TimeEntryUpdate(BaseModel):
    minutes: int | None = Field(default=None, gt=0, le=24 * 60)
    note: str | None = Field(default=None, max_length=500)


class RollupRow(BaseModel):
    id: str | None
    name: str
    seconds: int


class TimeSummaryOut(BaseModel):
    total_seconds: int
    by_person: list[RollupRow]
    by_project: list[RollupRow]
    by_task: list[RollupRow]
