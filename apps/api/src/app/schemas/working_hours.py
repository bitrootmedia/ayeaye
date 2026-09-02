from pydantic import BaseModel, Field


class WorkingHourCell(BaseModel):
    weekday: int = Field(ge=0, le=6)
    hour: int = Field(ge=0, le=23)


class WorkingHoursOut(BaseModel):
    # None for someone who has never opened the app — see `users.timezone`'s
    # own comment. The client decides what to do with that (there is nothing
    # honest to convert a schedule *to* without one).
    timezone: str | None
    cells: list[WorkingHourCell]
