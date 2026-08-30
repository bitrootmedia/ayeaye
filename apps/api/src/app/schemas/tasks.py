"""Wire shapes for tasks, their history and the notification inbox."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.task import PRIORITIES, STATUSES
from app.models.task_series import INTERVAL_UNITS
from app.schemas.structure import LEVEL_PATTERN, GrantOut, PersonOut

STATUS_PATTERN = f"^({'|'.join(STATUSES)})$"
PRIORITY_PATTERN = f"^({'|'.join(PRIORITIES)})$"
INTERVAL_PATTERN = f"^({'|'.join(INTERVAL_UNITS)})$"


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    # Omit for a loose task — one that belongs to the organisation rather than
    # any project. Deliberately not visible to the whole organisation; see
    # services/access.py.
    project_id: str | None = None
    status: str = Field(default="todo", pattern=STATUS_PATTERN)
    priority: str = Field(default="normal", pattern=PRIORITY_PATTERN)
    owner_user_id: str | None = None
    action_required_user_id: str | None = None
    due_on: date | None = None
    estimated_start_on: date | None = None
    estimated_hours: float | None = Field(default=None, ge=0, le=9999.9)


class TaskUpdate(BaseModel):
    """Every field is optional, and `None` is a real value for three of them.

    The router passes `model_fields_set` through to the service so "absent" and
    "explicitly null" stay distinguishable — clearing the action-required user,
    the due date or the project are all things people need to do.
    """

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    status: str | None = Field(default=None, pattern=STATUS_PATTERN)
    priority: str | None = Field(default=None, pattern=PRIORITY_PATTERN)
    project_id: str | None = None
    owner_user_id: str | None = None
    action_required_user_id: str | None = None
    due_on: date | None = None
    estimated_start_on: date | None = None
    estimated_hours: float | None = Field(default=None, ge=0, le=9999.9)
    position: int | None = None


class TaskRecurrenceIn(BaseModel):
    interval_unit: str = Field(pattern=INTERVAL_PATTERN)
    interval_count: int = Field(default=1, ge=1, le=52)


class TaskRecurrenceOut(BaseModel):
    id: str
    interval_unit: str
    interval_count: int
    next_due_on: date
    active: bool
    # Resolved server-side, same discipline as `can_close`/`can_hide`: the UI
    # hides "Stop repeating" rather than showing it and taking a 403.
    can_manage: bool


class TaskOut(BaseModel):
    id: str
    title: str
    description: str | None
    status: str
    priority: str
    # Open/closed is separate from status, on purpose: a task can be closed
    # from any status, and "closed while still blocked" is a real thing to say.
    is_open: bool
    closed_at: datetime | None
    project_id: str | None
    project_name: str | None
    owner: PersonOut | None
    action_required: PersonOut | None
    due_on: date | None
    estimated_start_on: date | None
    estimated_hours: float | None
    position: int
    created_at: datetime
    # "Last activity", not "last row update": a comment, a file, a tag or an
    # hour logged all bump it. A private note deliberately does not — see
    # services/tasks.py:announce.
    updated_at: datetime
    # Hidden: only the owner ever sees a task with this set, so anyone reading
    # this field is that owner. It is on the wire so the screen can say so.
    is_hidden: bool
    # The caller's own bookmark, not a property of the task — two people
    # looking at the same task can get two different answers here.
    is_pinned: bool
    # Set only when this task is part of a recurring series. `None` on the
    # list and board views, which don't pay this lookup's cost per row — see
    # `_recurrence_for` in the router.
    recurrence: TaskRecurrenceOut | None = None
    # Every tag on it. Sent with the task rather than fetched per card: the
    # board renders dozens at a time and one lookup covers the page.
    tags: list["TagOut"] = []
    # The caller's resolved level, and what it lets them do here. The UI
    # branches on these and never re-derives them.
    access: str
    can_close: bool
    # Owner-only, and not the same as `can_close` — an organisation admin
    # qualifies for that one and deliberately not for this.
    can_hide: bool


class TagOut(BaseModel):
    id: str
    name: str
    # Tasks carrying this leave the board and the list. They stay searchable
    # and reachable by filtering for the tag — nothing becomes unfindable.
    off_board: bool
    # Only on the vocabulary screen; the board doesn't ask.
    task_count: int = 0


class TagIn(BaseModel):
    # A name, not an id: the picker offers "create «foo»" the moment nothing
    # matches, and get-or-create means two people doing that at once get one
    # tag rather than one tag and one 409.
    name: str = Field(min_length=1, max_length=40)
    off_board: bool = False


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    off_board: bool | None = None


class ChecklistItemOut(BaseModel):
    id: str
    text: str
    done: bool


class ChecklistOut(BaseModel):
    id: str
    title: str
    items: list[ChecklistItemOut]


class ChecklistIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChecklistUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChecklistItemIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ChecklistItemUpdate(BaseModel):
    text: str | None = None
    done: bool | None = None


class SheetCellOut(BaseModel):
    row_id: str
    column_id: str
    checked_by: PersonOut
    checked_at: datetime


class SheetRowOut(BaseModel):
    id: str
    label: str


class SheetColumnOut(BaseModel):
    id: str
    label: str


class SheetOut(BaseModel):
    id: str
    title: str
    rows: list[SheetRowOut]
    columns: list[SheetColumnOut]
    # Sparse — only checked cells appear. Every (row, column) pair not
    # listed here is unchecked, including one from a row or column added
    # after every other cell in the grid.
    cells: list[SheetCellOut]


class SheetIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SheetUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SheetRowIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)


class SheetColumnIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)


class NoteIn(BaseModel):
    # Empty deletes it — "clear the box" and "remove the note" are one gesture.
    body: str = ""


class NoteOut(BaseModel):
    body: str
    updated_at: datetime | None


class BoardColumn(BaseModel):
    key: str
    # The column's REAL size, not len(tasks). A board that shows fifty cards
    # and says "50" when there are 812 is a board that lies about the work.
    total: int
    tasks: list[TaskOut]


class BoardOut(BaseModel):
    group_by: str
    per_group: int
    columns: list[BoardColumn]


class TaskCloseIn(BaseModel):
    closed: bool


class TaskHiddenIn(BaseModel):
    hidden: bool


class TaskEventOut(BaseModel):
    id: str
    kind: str
    actor: PersonOut | None
    data: dict
    created_at: datetime


class TaskAccessOut(BaseModel):
    """Everyone who can see this task, and how.

    Tasks have more routes in than projects, so this spells them out rather
    than showing a flat list: inherited from the project, granted directly on
    the task, or held by being the owner, the person asked to act, or an
    organisation admin.
    """

    owner: PersonOut | None
    action_required: PersonOut | None
    project_name: str | None
    inherits_from_project: bool
    grants: list[GrantOut]
    organisation_admins: list[PersonOut]
    can_manage: bool


class TaskGrantIn(BaseModel):
    user_id: str | None = None
    team_id: str | None = None
    level: str = Field(default="read", pattern=LEVEL_PATTERN)


class NotificationOut(BaseModel):
    id: str
    kind: str
    title: str
    body: str | None
    link_path: str | None
    read_at: datetime | None
    created_at: datetime


class UnreadCountOut(BaseModel):
    unread: int


class SearchHitOut(BaseModel):
    """One search result.

    `kind` is what the UI keys its icon and link off. Keeping the link
    server-shaped would tie the API to the frontend's routing; keeping it a
    kind plus an id does not.
    """

    kind: str
    id: str
    title: str
    # A window around the match, so a hit deep in a description shows why it
    # matched rather than the first line of something unrelated.
    subtitle: str | None
    # Where it lives — a task's project, for instance.
    context: str | None
    score: float
    # Closed or archived. Shown rather than hidden: people search for finished
    # work precisely because they can't remember where it went.
    inactive: bool


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHitOut]


class TaskFileOut(BaseModel):
    """One file on a task, however it got there."""

    id: str
    filename: str
    content_type: str
    size_bytes: int
    url: str
    # None until the worker has made one, or for anything that isn't an image.
    # The UI falls back to the full-size object.
    thumbnail_url: str | None
    # True when it arrived in a comment rather than through the Files panel.
    # The panel shows both — a file dropped into a reply is as much "a file on
    # this task" as one added directly — but says which is which.
    from_comment: bool
    uploaded_by: PersonOut | None
    created_at: datetime


class TaskSummaryOut(BaseModel):
    """Just enough of another task to tell, at a glance, whether it's
    blocking — no description, no owner, nothing this endpoint would have to
    re-check access for beyond what `list_dependencies` already resolved."""

    id: str
    title: str
    status: str
    is_open: bool


class TaskDependencyIn(BaseModel):
    depends_on_task_id: str


class TaskDependencyOut(BaseModel):
    """One edge. `task` is `None` when the other side is invisible to the
    caller — never its title or status, only that something is there."""

    id: str
    task: TaskSummaryOut | None


class TaskDependenciesOut(BaseModel):
    """Both directions. `depends_on` is the edit surface — what this task is
    waiting on; `blocks` is read-only here — what's waiting on *this* task,
    editable only from that task's own list."""

    depends_on: list[TaskDependencyOut]
    blocks: list[TaskDependencyOut]
