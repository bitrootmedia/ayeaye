"""The recurrence sweep: generate the next occurrence of every series that's due.

Same shape as `tasks/deadlines.py`: runs on a schedule, claims before it acts,
and reuses `tasks_service.create()` rather than inserting a row directly —
there is deliberately not a second path that creates a task, the same reason
`app/mcp/server.py` never writes a raw `select()`. Generation happens *as the
series owner*: `task.owner_user_id` ends up as itself, so no "you're now the
owner" notification fires for a task that owner already knew was coming.

**No notification on generation, on purpose.** The owner set the cadence
themselves; a ping every time their own recurring task reappears is exactly
the noise `services/conversations.py` already argues against for comments.
If they want a nudge, the daily digest's "planned for today" already covers
it once the task lands there, and the dashboard's Due-soon card covers it as
the date approaches.
"""

import logging

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Organisation, User
from app.services import organisations as organisations_service
from app.services import recurrence as recurrence_service
from app.services import tasks as tasks_service
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.recurrence")


@broker.task(schedule=[{"cron": "35 * * * *"}])
async def sweep_recurring_tasks() -> None:
    """Generate one task per series whose next occurrence has arrived.

    Thirty-five past: reminders (:05), deadlines (:15) and the daily digest
    (:25) already claim the earlier slots in the hour.
    """
    created = 0
    async with SessionLocal() as db:
        for tz_name in await recurrence_service.timezones_in_use(db):
            for series in await recurrence_service.due_in_zone(db, tz_name=tz_name):
                due_on = await recurrence_service.try_claim(db, series)
                if due_on is None:
                    continue  # lost the race to another sweep
                created += await _generate(db, series, due_on=due_on)
    if created:
        logger.info("recurrence sweep created %d task(s)", created)


async def _generate(db, series, *, due_on) -> int:
    """One occurrence. The claim already advanced `next_due_on`, so a
    failure here — the owner lost project access, say — skips this
    occurrence rather than retrying it. The same trade `tasks/reminders.py`
    accepts: repeating on failure risks a duplicate, which is the worse of
    the two failures.
    """
    owner = (
        await db.execute(select(User).where(User.id == series.owner_user_id))
    ).scalar_one_or_none()
    org = (
        await db.execute(select(Organisation).where(Organisation.id == series.organisation_id))
    ).scalar_one_or_none()
    if owner is None or org is None:
        logger.warning("series %s has no owner or organisation left; skipping", series.id)
        return 0

    try:
        ctx = await organisations_service.context_for(db, org.id, owner)
        task = await tasks_service.create(
            db,
            ctx,
            owner,
            title=series.title,
            description=series.description,
            project_id=series.project_id,
            priority=series.priority,
            owner_user_id=series.owner_user_id,
            due_on=due_on,
        )
    except Exception as exc:
        logger.warning("could not generate the next occurrence of series %s: %s", series.id, exc)
        return 0

    task.series_id = series.id
    await db.commit()
    return 1
