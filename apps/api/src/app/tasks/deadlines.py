"""The deadline sweep: nudge whoever's on the hook the day before it's due.

Same shape as `tasks/reminders.py` — runs on a schedule because a deadline
has to arrive whether or not anybody has the app open, and everything here is
idempotent by construction because `services/deadlines.claim` is a conditional
UPDATE, not a select.
"""

import logging

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Task
from app.models.notification import KIND_DEADLINE_TOMORROW
from app.services import deadlines as deadlines_service
from app.services import notifications as notifications_service
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.deadlines")


@broker.task(schedule=[{"cron": "15 * * * *"}])
async def sweep_deadlines() -> None:
    """Fire once per open, dated task whose owner's tomorrow has arrived.

    Quarter past the hour: `sweep_reminders` already runs at five past, and a
    scheduler that fires everything at once is a scheduler that fires late
    for whichever job loses the race.
    """
    sent = 0
    async with SessionLocal() as db:
        for tz_name in await deadlines_service.timezones_in_use(db):
            for task_id in await deadlines_service.claim(db, tz_name=tz_name):
                sent += await _notify(db, task_id)
    if sent:
        logger.info("deadline sweep sent %d notification(s)", sent)


async def _notify(db, task_id) -> int:
    """The owner, and whoever is action-required, if that isn't the owner —
    the same stake-holding pair `services/conversations.py` notifies for a
    comment. The row is already claimed, so a failure here loses this one
    notification rather than repeating it — the right way round, per
    `tasks/reminders.py`'s identical reasoning."""
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None:
        return 0

    recipients = {task.owner_user_id}
    if task.action_required_user_id:
        recipients.add(task.action_required_user_id)

    link = f"/orgs/{task.organisation_id}/tasks/{task.id}"
    sent = 0
    for user_id in recipients:
        await notifications_service.notify(
            db,
            user_id=user_id,
            kind=KIND_DEADLINE_TOMORROW,
            title=f"Due tomorrow: “{task.title}”",
            link_path=link,
        )
        sent += 1
    return sent
