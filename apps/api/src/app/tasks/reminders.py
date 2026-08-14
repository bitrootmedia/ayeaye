"""The reminder sweep.

Runs on a schedule rather than on a request, because a reminder has to arrive
whether or not anybody has the app open — that is the entire point of one.

**Everything here is idempotent by construction.** The claim is a conditional
UPDATE inside `services/reminders.py`; this module only sends what that
returned. So the sweep running twice, a container restarting mid-run, or a
missed slot being caught up all produce one notification each. Getting that
wrong is invisible in testing and obvious to every user at once.

Scheduled hourly, not daily: an hourly sweep crossing every timezone's
midnight means "the day before" and "today" land within an hour of local
midnight wherever somebody is, and a machine that was asleep at 00:00 still
fires when it wakes.
"""

import logging
from datetime import date

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Reminder, Task
from app.models.notification import KIND_REMINDER_DUE, KIND_REMINDER_SOON
from app.services import notifications as notifications_service
from app.services import reminders as reminders_service
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.reminders")


@broker.task(schedule=[{"cron": "5 * * * *"}])
async def sweep_reminders() -> None:
    """Fire everything whose moment has come, once each.

    Five past the hour rather than on the hour: nothing else in this stack
    runs then, and a scheduler that fires at exactly 00:00 in a dozen
    timezones is a scheduler that fires alone.
    """
    sent = 0
    async with SessionLocal() as db:
        for tz_name in await reminders_service.timezones_in_use(db):
            # Order matters: claim the "due" window first. A reminder for
            # today qualifies for both windows, and it should say "this is
            # here", not "this is coming".
            for ahead in (False, True):
                ids = await reminders_service.claim(db, tz_name=tz_name, ahead=ahead)
                for reminder_id in ids:
                    sent += await _notify(db, reminder_id, ahead=ahead)
    if sent:
        logger.info("reminder sweep sent %d notification(s)", sent)


async def _notify(db, reminder_id, *, ahead: bool) -> int:
    """One notification for one claimed reminder.

    The row is already claimed, so a failure here loses that notification
    rather than repeating it. That is the right way round: a reminder that
    doesn't arrive is visible in the app as a red badge, where one that
    arrives four times is only visible in somebody's inbox.
    """
    row = (
        await db.execute(
            select(Reminder, Task).join(Task, Task.id == Reminder.task_id).where(
                Reminder.id == reminder_id
            )
        )
    ).first()
    if row is None:
        return 0
    reminder, task = row

    when: date = reminder.remind_on
    if ahead:
        title = f"Tomorrow: “{task.title}”"
    else:
        title = f"Today: “{task.title}”"
    await notifications_service.notify(
        db,
        user_id=reminder.user_id,
        kind=KIND_REMINDER_SOON if ahead else KIND_REMINDER_DUE,
        title=title,
        body=reminder.note,
        link_path=f"/orgs/{task.organisation_id}/tasks/{task.id}",
    )
    logger.debug("reminder %s for %s fired (ahead=%s)", reminder_id, when, ahead)
    return 1
