"""The daily digest: what's planned for today, and what closed yesterday.

Same shape as `tasks/deadlines.py` and `tasks/reminders.py`: runs on a
schedule, claims before it sends, and everything is idempotent by
construction because `services/daily_summary.claim` is a conditional UPDATE.
"""

import logging

from app.db import SessionLocal
from app.models.notification import KIND_DAILY_SUMMARY
from app.services import daily_summary as daily_summary_service
from app.services import notifications as notifications_service
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.daily_summary")


@broker.task(schedule=[{"cron": "25 * * * *"}])
async def sweep_daily_summaries() -> None:
    """Fire once per person whose local morning has arrived.

    Twenty-five past: `sweep_reminders` runs at five past and
    `sweep_deadlines` at fifteen past, so all three land in the same hourly
    tick without competing for it.
    """
    sent = 0
    async with SessionLocal() as db:
        for tz_name in await daily_summary_service.timezones_in_use(db):
            for user_id in await daily_summary_service.claim(db, tz_name=tz_name):
                sent += await _notify(db, user_id, tz_name=tz_name)
    if sent:
        logger.info("daily summary sweep sent %d digest(s)", sent)


async def _notify(db, user_id, *, tz_name: str) -> int:
    """One notification per organisation with something to report — never a
    single message merged across all of them. See the service docstring."""
    orgs = await daily_summary_service.for_user(db, user_id, tz_name=tz_name)
    sent = 0
    for org in orgs:
        lines = []
        if org.planned_today:
            lines.append("Planned for today:")
            lines += [f"- {title}" for title in org.planned_today]
        if org.done_yesterday:
            if lines:
                lines.append("")
            lines.append("Done yesterday:")
            lines += [f"- {title}" for title in org.done_yesterday]

        await notifications_service.notify(
            db,
            user_id=user_id,
            kind=KIND_DAILY_SUMMARY,
            title=f"Your day in {org.organisation_name}",
            body="\n".join(lines),
            link_path=f"/orgs/{org.organisation_id}/planner",
        )
        sent += 1
    return sent
