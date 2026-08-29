"""The deadline sweep: a not-closed task, due tomorrow.

Same shape as `services/reminders.py`, and the same reason: "tomorrow" needs
a timezone, and the sweep has to claim before it sends or a restart (or two
schedulers racing) sends the same nudge twice.

**Whose tomorrow?** A task has one due date but can have two interested
people in two different timezones — the owner and whoever is action-required.
Reminders side-step this because a reminder belongs to exactly one person.
Here the **owner's** timezone decides when "tomorrow" has arrived; the owner
is the one accountable for the date, the same reasoning that makes them (and
not action-required) the one who can close the task. Action-required is
notified in the same message when the sweep fires, not on their own clock.
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, User

# One day, like reminders' own AHEAD_DAYS — "tomorrow" is what's useful to
# prepare for; further out and it competes with everything else in the inbox.
AHEAD_DAYS = 1


async def timezones_in_use(db: AsyncSession) -> list[str]:
    """The distinct timezones of owners with an open, dated task.

    Same reasoning as `reminders.timezones_in_use`: there's no single global
    "tomorrow", so the sweep runs once per timezone actually in use rather
    than once per task.
    """
    rows = (
        await db.execute(
            select(func.coalesce(User.timezone, "UTC"))
            .join(Task, Task.owner_user_id == User.id)
            .where(Task.closed_at.is_(None), Task.due_on.isnot(None))
            .distinct()
        )
    ).scalars().all()
    return list(rows)


async def claim(db: AsyncSession, *, tz_name: str) -> list[uuid.UUID]:
    """Claim every open task, owned by someone in this timezone, due
    tomorrow-in-that-zone — or that the sweep has never caught up with yet.

    One conditional UPDATE, same as `reminders.claim`: `deadline_notified_at
    IS NULL` is the claim itself, so whoever runs this first marks the row
    and a second, racing run matches nothing. `<=` rather than `==` on the
    date so a sweep that missed its slot still fires what it slept through.
    """
    try:
        today = datetime.now(ZoneInfo(tz_name)).date()
    except (ZoneInfoNotFoundError, ValueError):
        today = datetime.now(ZoneInfo("UTC")).date()
    tomorrow = today + timedelta(days=AHEAD_DAYS)

    owner_in_zone = Task.owner_user_id.in_(
        select(User.id).where(func.coalesce(User.timezone, "UTC") == tz_name)
    )
    rows = (
        await db.execute(
            update(Task)
            .where(
                Task.closed_at.is_(None),
                Task.deadline_notified_at.is_(None),
                Task.due_on.isnot(None),
                Task.due_on <= tomorrow,
                owner_in_zone,
            )
            .values(deadline_notified_at=func.now())
            .returning(Task.id)
        )
    ).scalars().all()
    await db.commit()
    return list(rows)


__all__ = ["AHEAD_DAYS", "claim", "timezones_in_use"]
