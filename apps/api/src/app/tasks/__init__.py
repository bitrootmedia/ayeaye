"""Taskiq broker + task registry.

The worker is started as `taskiq worker app.tasks:broker`, so importing this
package must register every task. Handler modules are imported here **for that
side effect** — a new task module that isn't listed below simply never runs,
with no error anywhere to tell you why.
"""

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from app.tasks import (
    daily_summary,  # noqa: F401  registers sweep_daily_summaries
    deadlines,  # noqa: F401  registers sweep_deadlines
    invites,  # noqa: F401  registers send_invite_email
    notifications,  # noqa: F401  registers send_notification_email
    recurrence,  # noqa: F401  registers sweep_recurring_tasks
    reminders,  # noqa: F401  registers sweep_reminders
    thumbnails,  # noqa: F401  registers make_thumbnail
)
from app.tasks.broker import broker

# Started as `taskiq scheduler app.tasks:scheduler` in its own container.
#
# `LabelScheduleSource` reads the `schedule=` label off the task itself, so a
# periodic job's cadence lives next to the code it runs rather than in a
# config file that can disagree with it. The scheduler only *enqueues* — the
# work still happens in the worker, so a slow sweep can't delay the next one.
scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])

__all__ = [
    "broker",
    "scheduler",
    "daily_summary",
    "deadlines",
    "invites",
    "notifications",
    "recurrence",
    "reminders",
    "thumbnails",
]
