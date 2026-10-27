"""The weekly report: last week, to each organisation's admins, on Monday.

Same shape as `tasks/daily_summary.py`: claims before it sends, so a restart
or two schedulers racing sends one report per person per week.
"""

import logging
from datetime import datetime

from app.db import SessionLocal
from app.models import User
from app.models.notification import KIND_WEEKLY_REPORT
from app.services import notifications as notifications_service
from app.services import weekly_report as weekly_report_service
from app.services.work_reports import zone
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.weekly_report")


@broker.task(schedule=[{"cron": "45 * * * *"}])
async def sweep_weekly_reports() -> None:
    """Hourly, because Monday morning arrives at a different hour in every
    zone. Forty-five past: :05, :15, :25 and :35 are taken."""
    sent = 0
    async with SessionLocal() as db:
        for tz_name in await weekly_report_service.timezones_in_use(db):
            for user_id in await weekly_report_service.claim(db, tz_name=tz_name):
                sent += await send(db, user_id)
    if sent:
        logger.info("weekly report sweep sent %d report(s)", sent)


async def send(db, user_id) -> int:
    """One notification per organisation with something to report."""
    user = await db.get(User, user_id)
    if user is None:
        return 0
    today = datetime.now(zone(user.timezone)).date()
    sent = 0
    for week in await weekly_report_service.for_user(db, user, today=today):
        title, body = weekly_report_service.render(week)
        await notifications_service.notify(
            db,
            user_id=user.id,
            kind=KIND_WEEKLY_REPORT,
            title=title,
            body=body,
            link_path=(
                f"/orgs/{week.organisation_id}/reports?since={week.since}&until={week.until}"
            ),
            organisation_id=week.organisation_id,
        )
        sent += 1
    return sent
