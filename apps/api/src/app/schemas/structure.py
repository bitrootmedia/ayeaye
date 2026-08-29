"""Wire shapes for teams, project groups and projects."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.structure import GRANT_LEVELS

LEVEL_PATTERN = f"^({'|'.join(GRANT_LEVELS)})$"


class PersonOut(BaseModel):
    """A person, as shown in a roster or an access list."""

    id: str
    email: str | None
    display_name: str | None


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TeamOut(BaseModel):
    id: str
    name: str
    member_count: int
    created_at: datetime


class TeamDetailOut(TeamOut):
    members: list[PersonOut]


class TeamMemberIn(BaseModel):
    user_id: str


class ProjectGroupOut(BaseModel):
    id: str
    name: str
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    project_group_id: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    # Distinguished from "absent" by `model_fields_set` in the router, so that
    # moving a project out of every group (null) is expressible at all.
    project_group_id: str | None = None
    archived: bool | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None
    project_group_id: str | None
    project_group_name: str | None
    owner: PersonOut | None
    archived: bool
    created_at: datetime
    # The caller's resolved level: read | write | owner. The UI branches on
    # this and never re-derives it.
    access: str
    # Open tasks, and open tasks that are critical/urgent/high combined — the
    # caller's own visibility, same as everything else here. See
    # access.project_task_stats_stmt.
    open_task_count: int = 0
    important_task_count: int = 0


class GrantIn(BaseModel):
    """Exactly one of `user_id` / `team_id`. Enforced in the service, and by a
    CHECK constraint underneath it."""

    user_id: str | None = None
    team_id: str | None = None
    level: str = Field(default="read", pattern=LEVEL_PATTERN)


class GrantLevelIn(BaseModel):
    level: str = Field(pattern=LEVEL_PATTERN)


class GrantOut(BaseModel):
    id: str
    level: str
    user: PersonOut | None
    team: TeamOut | None
    created_at: datetime


class ProjectAccessOut(BaseModel):
    """Everyone who can see this project, stated in full.

    Three groups, because there are three genuinely different reasons someone
    has access, and collapsing them would hide the one people forget:

    * `owner`  — responsible for it, controls who else gets in;
    * `grants` — explicitly shared with, by name or by team;
    * `organisation_admins` — see everything in the organisation, whether or
      not anyone shared it with them. Listing them is the difference between
      an access screen that is true and one that merely looks reassuring.
    """

    owner: PersonOut | None
    grants: list[GrantOut]
    organisation_admins: list[PersonOut]
    # Whether the caller may change any of the above.
    can_manage: bool


class TransferIn(BaseModel):
    owner_user_id: str
