# Import every model here so `import app.models` populates Base.metadata.
# Alembic's env.py imports this module for autogenerate to see the tables.
from app.models.conversation import (
    Attachment,
    Conversation,
    Message,
    MessageRead,
)
from app.models.note import TaskNote
from app.models.notification import Notification
from app.models.organisation import Organisation, OrganisationMember
from app.models.presence import Announcement, OutOfOffice
from app.models.reminder import Reminder
from app.models.structure import (
    Project,
    ProjectGroup,
    ProjectMember,
    Team,
    TeamMember,
)
from app.models.tag import Tag, TaskTag
from app.models.task import Task, TaskEvent, TaskGrant
from app.models.time_entry import TimeEntry
from app.models.token import PersonalAccessToken
from app.models.user import User

__all__ = [
    "Announcement",
    "Conversation",
    "Attachment",
    "Message",
    "MessageRead",
    "Notification",
    "Organisation",
    "PersonalAccessToken",
    "OutOfOffice",
    "OrganisationMember",
    "Project",
    "ProjectGroup",
    "ProjectMember",
    "Reminder",
    "Tag",
    "Task",
    "TaskEvent",
    "TaskGrant",
    "TaskNote",
    "TaskTag",
    "TimeEntry",
    "Team",
    "TeamMember",
    "User",
]
