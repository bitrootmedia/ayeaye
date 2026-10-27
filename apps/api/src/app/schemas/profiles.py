from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.working_hours import WorkingHourCell


class ProfileAbsence(BaseModel):
    id: str
    starts_on: date
    ends_on: date
    note: str | None
    away_now: bool


class ProfileTask(BaseModel):
    id: str
    title: str
    status: str
    priority: str
    project_id: str | None
    project_name: str | None
    due_on: date | None
    # From the *profile's* person's point of view, not the viewer's — the
    # screen is about what they're on.
    is_owner: bool
    is_action_required: bool
    is_open: bool
    updated_at: datetime
    closed_at: datetime | None


class ProfileTimer(BaseModel):
    task: ProfileTask
    started_at: datetime


class ProfileOut(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: str
    joined_at: datetime | None
    # IANA, or None for someone who has never opened the app.
    timezone: str | None
    status_message: str | None
    working_hours: list[WorkingHourCell]
    away: list[ProfileAbsence]
    # Only when it's on a task the viewer can see — see services/profiles.py.
    working_on: ProfileTimer | None
    open_tasks: list[ProfileTask]
    # How many open tasks of theirs the viewer can see in all, so the screen
    # can say "10 of 23" rather than implying ten is everything.
    open_total: int
    recently_closed: list[ProfileTask]
