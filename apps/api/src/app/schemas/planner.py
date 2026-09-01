"""Wire shapes for the day planner."""

from pydantic import BaseModel, Field

from app.models.planner import BUCKETS

BUCKET_PATTERN = f"^({'|'.join(BUCKETS)})$"


class PlannerTaskOut(BaseModel):
    id: str
    title: str
    priority: str
    # Neither asked for explicitly, but free from the same row — lets a
    # planned task that later closes render with a closed indicator instead
    # of looking identical to an open one. Status and open/closed are two
    # different fields everywhere else in this product; this is no exception.
    status: str
    is_open: bool


class PlannerEntryOut(BaseModel):
    task: PlannerTaskOut
    bucket: str
    position: int


class PlannerOut(BaseModel):
    pool: list[PlannerTaskOut]
    # Always all five keys, even empty — the frontend never has to guess
    # which buckets exist.
    buckets: dict[str, list[PlannerEntryOut]]


class PlannerPlaceIn(BaseModel):
    bucket: str = Field(pattern=BUCKET_PATTERN)
    # Required from the Planner board itself, which always knows where a
    # drop landed relative to its new neighbours. Omit it — the task
    # screen's own bucket picker does — and the task is appended to the end
    # of the bucket instead; see `services/planner.py::place`.
    position: int | None = None
