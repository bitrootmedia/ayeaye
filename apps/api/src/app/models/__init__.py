# Import every model here so `import app.models` populates Base.metadata.
# Alembic's env.py imports this module for autogenerate to see the tables.
from app.models.checklist import TaskChecklist, TaskChecklistItem
from app.models.conversation import (
    Attachment,
    Conversation,
    Message,
    MessageRead,
)
from app.models.login_event import LoginEvent
from app.models.mfa import MfaBackupCode, MfaTotpDevice
from app.models.note import TaskNote
from app.models.notification import Notification
from app.models.organisation import Organisation, OrganisationMember
from app.models.personal_note import PersonalNote
from app.models.pin import TaskPin
from app.models.planner import PlannerEntry
from app.models.presence import Announcement, OutOfOffice
from app.models.reminder import Reminder
from app.models.sheet import TaskSheet, TaskSheetCell, TaskSheetColumn, TaskSheetRow
from app.models.structure import (
    Project,
    ProjectGroup,
    ProjectMember,
    Team,
    TeamMember,
)
from app.models.tag import Tag, TaskTag
from app.models.task import Task, TaskEvent, TaskGrant
from app.models.task_series import TaskSeries
from app.models.time_entry import TimeEntry
from app.models.token import PersonalAccessToken
from app.models.user import User

__all__ = [
    "Announcement",
    "Conversation",
    "Attachment",
    "Message",
    "MessageRead",
    "LoginEvent",
    "MfaBackupCode",
    "MfaTotpDevice",
    "Notification",
    "Organisation",
    "PersonalAccessToken",
    "OutOfOffice",
    "OrganisationMember",
    "PersonalNote",
    "PlannerEntry",
    "Project",
    "ProjectGroup",
    "ProjectMember",
    "Reminder",
    "Tag",
    "Task",
    "TaskChecklist",
    "TaskChecklistItem",
    "TaskEvent",
    "TaskGrant",
    "TaskNote",
    "TaskPin",
    "TaskSeries",
    "TaskSheet",
    "TaskSheetCell",
    "TaskSheetColumn",
    "TaskSheetRow",
    "TaskTag",
    "TimeEntry",
    "Team",
    "TeamMember",
    "User",
]
