"""The daily digest sweep: what's planned for today, and what closed yesterday.

Same claim discipline as `services/reminders.py` and `services/deadlines.py` —
`claim()` is one conditional UPDATE, not a select, so a restart or two
schedulers racing sends one digest per person per day, not several. The one
difference from those two: this also gates on the **hour**, because a digest
that could arrive at 3am is not a digest anybody reads. `claim()` only ever
returns anyone once `SUMMARY_HOUR` has arrived in their own zone that day.

**Opt-out, not opt-in** (`users.daily_summary_enabled`, default `true`) — see
the column's own comment for why a default-off setting nobody finds defeats
the point of a digest existing at all.

**Cross-organisation people get one digest per organisation, not one merged
across all of them.** A digest links somewhere, and there is no single
sensible landing page for "your planner across three organisations" — the
planner itself is scoped to one, like everything else that isn't the
notification inbox. An organisation with nothing to report that day is
skipped rather than sent an empty "nothing happened" message.
"""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organisation, OrganisationMember, PlannerEntry, Task, User
from app.models.organisation import STATUS_ACTIVE
from app.models.planner import BUCKET_TODAY
from app.services import access

# Local hour the digest goes out. Morning, not the top of the day: 7am is
# early enough to shape the day and late enough not to be the 3am problem
# every timezone-naive scheduler eventually causes somebody.
SUMMARY_HOUR = 7


async def timezones_in_use(db: AsyncSession) -> list[str]:
    """The distinct timezones of everyone who hasn't opted out."""
    rows = (
        await db.execute(
            select(func.coalesce(User.timezone, "UTC"))
            .where(User.daily_summary_enabled.is_(True))
            .distinct()
        )
    ).scalars().all()
    return list(rows)


async def claim(db: AsyncSession, *, tz_name: str) -> list[uuid.UUID]:
    """Claim everyone in this timezone whose local morning has arrived and
    who hasn't had today's digest yet.

    The hour check happens in Python before the UPDATE runs at all: there's
    no cheap way to ask Postgres "is it currently 7am in Europe/Lisbon" from
    inside a WHERE clause without doing the same zone conversion by hand, and
    doing it once here reads the same as `deadlines.claim`'s own date math.
    """
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        now = datetime.now(ZoneInfo("UTC"))
    if now.hour != SUMMARY_HOUR:
        return []
    today = now.date()

    in_zone = func.coalesce(User.timezone, "UTC") == tz_name
    rows = (
        await db.execute(
            update(User)
            .where(
                User.daily_summary_enabled.is_(True),
                in_zone,
                (User.last_daily_summary_sent_on.is_(None))
                | (User.last_daily_summary_sent_on < today),
            )
            .values(last_daily_summary_sent_on=today)
            .returning(User.id)
        )
    ).scalars().all()
    await db.commit()
    return list(rows)


def _yesterday_window(tz_name: str) -> tuple[datetime, datetime, date]:
    """The UTC instants bounding "yesterday" in this timezone, and today's
    date in it. Computed in Python, once, rather than pushed into SQL as an
    `AT TIME ZONE` — the rest of this codebase does timezone math on the
    Python side (see `reminders.today_for`) and this stays consistent with it.
    """
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    today_local = datetime.now(tz).date()
    yesterday_local = today_local - timedelta(days=1)
    start_yesterday = datetime.combine(yesterday_local, time.min, tzinfo=tz)
    start_today = datetime.combine(today_local, time.min, tzinfo=tz)
    return start_yesterday, start_today, today_local


class OrgSummary:
    __slots__ = ("organisation_id", "organisation_name", "planned_today", "done_yesterday")

    def __init__(self, organisation_id, organisation_name, planned_today, done_yesterday):
        self.organisation_id = organisation_id
        self.organisation_name = organisation_name
        self.planned_today = planned_today
        self.done_yesterday = done_yesterday


async def for_user(db: AsyncSession, user_id: uuid.UUID, *, tz_name: str) -> list[OrgSummary]:
    """One entry per organisation with something to say — see the module
    docstring for why this doesn't merge into a single cross-org digest."""
    start_yesterday, start_today, _today = _yesterday_window(tz_name)

    memberships = (
        await db.execute(
            select(Organisation.id, Organisation.name, OrganisationMember.role)
            .join(OrganisationMember, OrganisationMember.organisation_id == Organisation.id)
            .where(
                OrganisationMember.user_id == user_id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
            .order_by(Organisation.name)
        )
    ).all()

    out: list[OrgSummary] = []
    for org_id, org_name, role in memberships:
        visible = access.visible_task_ids_stmt(user_id=user_id, org_id=org_id, org_role=role)

        planned = (
            (
                await db.execute(
                    select(Task.title)
                    .join(PlannerEntry, PlannerEntry.task_id == Task.id)
                    .where(
                        PlannerEntry.user_id == user_id,
                        PlannerEntry.bucket == BUCKET_TODAY,
                        Task.id.in_(visible),
                    )
                    .order_by(PlannerEntry.position, PlannerEntry.id)
                )
            )
            .scalars()
            .all()
        )

        # Owner only — this is "what I finished", not everything that moved.
        # An owner always has a route to their own task (`task_level_
        # expression`'s first clause), hidden included, so no extra
        # visibility check is needed here the way `planned` needs `visible`.
        done = (
            (
                await db.execute(
                    select(Task.title)
                    .where(
                        Task.organisation_id == org_id,
                        Task.owner_user_id == user_id,
                        Task.closed_at.isnot(None),
                        Task.closed_at >= start_yesterday,
                        Task.closed_at < start_today,
                    )
                    .order_by(Task.closed_at)
                )
            )
            .scalars()
            .all()
        )

        if planned or done:
            out.append(OrgSummary(org_id, org_name, list(planned), list(done)))

    return out


__all__ = ["SUMMARY_HOUR", "OrgSummary", "claim", "for_user", "timezones_in_use"]
