""" "Still working on this?" — asked now and then while a timer runs.

A timer is started with a click and stopped by remembering to, and the second
half is the one that fails: a clock left running over lunch, or overnight, is
a timesheet somebody corrects by hand next week. So a running timer asks,
every hour or two at random, whether you are still on it — and nobody
answering within fifteen to thirty minutes, also random, pauses it.

**The server asks, not a client.** A question that only the menu bar app could
ask would only reach people who run the menu bar app, and the person whose
timer is still going at midnight is quite likely nowhere near it. So the
state lives here, on the running entry (`TimeEntry.next_check_in_at`,
`check_in_asked_at`, `check_in_deadline`), the scheduler asks and expires,
and every surface answers the same question:

- **Telegram**, with two buttons, when that is the person's preference
  (`users.timer_check_ins = 'telegram'`, the default) and a chat is linked;
- the **menu bar app**, which reads the open question off `running_timer`
  and answers with `answer_check_in`;
- the **web header**, which reads it off `GET /me/timer`.

Answering anywhere answers it everywhere, because there is only one question
and it is a row.

**Random rather than on the hour** because a check that can be anticipated
can be answered in advance, and then it measures nothing. **Capped per day**
(`users.timer_check_ins_per_day`, counted in the person's own local day) so a
long day is not a nag.

**No answer ends the entry at the moment of asking**, not at the deadline:
the wait nobody answered is the one stretch we know was not work. Then
`timer_paused` is raised like any other notification, so it goes wherever
the person routes that kind — Telegram again, typically.

Both sweeps claim with a conditional UPDATE before acting, the same discipline
as `reminders.claim`, so a restarted worker or two schedulers ask once and
pause once.
"""

import logging
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationChannel, Task, TimeEntry, User
from app.models.notification import KIND_TIMER_PAUSED
from app.models.notification_channel import CHANNEL_TELEGRAM
from app.realtime import events as realtime

logger = logging.getLogger("app.services.check_ins")

MODE_TELEGRAM = "telegram"
MODE_APPS = "apps"
MODE_OFF = "off"
MODES = (MODE_TELEGRAM, MODE_APPS, MODE_OFF)

# Between questions, and how long one waits. Ranges, picked from at random.
EVERY = (timedelta(minutes=60), timedelta(minutes=120))
GRACE = (timedelta(minutes=15), timedelta(minutes=30))

ANSWER_YES = "yes"
ANSWER_STOP = "stop"
# What `answer` reports back.
CONFIRMED = "confirmed"
STOPPED = "stopped"
GONE = "gone"

CALLBACK_PREFIX = "checkin"

# --- pure. no database, no clock of its own. ---------------------------------


def pick(span: tuple[timedelta, timedelta], rng: random.Random | None = None) -> timedelta:
    """A random duration inside `span`, to the second. Not a security
    boundary — just something that can't be predicted to the minute."""
    low, high = (int(d.total_seconds()) for d in span)
    return timedelta(seconds=(rng or random).randint(low, high))  # noqa: S311


def local_day(now: datetime, tz_name: str | None) -> date:
    """Whose "today" the daily cap counts: the person's, not the server's.
    An unknown or missing zone is UTC, the same fallback reminders use."""
    try:
        zone = ZoneInfo(tz_name) if tz_name else UTC
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC
    return now.astimezone(zone).date()


def has_allowance(*, day: date | None, count: int, today: date, per_day: int) -> bool:
    """A count recorded on another day is a count of zero today."""
    return day != today or count < per_day


def callback_data(action: str, entry_id: uuid.UUID) -> str:
    """What a Telegram button carries — 64 bytes at most, and this is 50."""
    return f"{CALLBACK_PREFIX}:{action}:{entry_id}"


def parse_callback(data: str) -> tuple[str, uuid.UUID] | None:
    """The other half. Anything malformed is `None`, never an exception —
    the webhook answers everything with a 200."""
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX or parts[1] not in (ANSWER_YES, ANSWER_STOP):
        return None
    try:
        return parts[1], uuid.UUID(parts[2])
    except ValueError:
        return None


def first_check_in(now: datetime) -> datetime:
    """When a timer started `now` first asks."""
    return now + pick(EVERY)


def question_text(task_title: str, running_for: str) -> str:
    return (
        f"Still working on “{task_title}”?\n\n"
        f"The timer has been running for {running_for}. "
        "If nobody answers, it pauses itself."
    )


# --- the two sweeps ------------------------------------------------------------


async def ask_due(db: AsyncSession, *, now: datetime) -> int:
    """Ask every running timer whose moment has come. Returns how many."""
    from app.services import time_tracking

    rows = (
        await db.execute(
            select(TimeEntry, User, Task)
            .join(User, User.id == TimeEntry.user_id)
            .join(Task, Task.id == TimeEntry.task_id)
            .where(
                TimeEntry.ended_at.is_(None),
                TimeEntry.check_in_asked_at.is_(None),
                TimeEntry.next_check_in_at <= now,
                User.timer_check_ins != MODE_OFF,
            )
        )
    ).all()
    asked = 0
    for entry, user, task in rows:
        entry_id, started_at = entry.id, entry.started_at
        today = local_day(now, user.timezone)
        if not has_allowance(
            day=user.timer_check_ins_day,
            count=user.timer_check_ins_count,
            today=today,
            per_day=user.timer_check_ins_per_day,
        ):
            # Over today's allowance. Looked at again later rather than never:
            # tomorrow starts at zero.
            entry.next_check_in_at = now + pick(EVERY)
            await db.commit()
            continue

        claimed = (
            await db.execute(
                update(TimeEntry)
                .where(
                    TimeEntry.id == entry_id,
                    TimeEntry.ended_at.is_(None),
                    TimeEntry.check_in_asked_at.is_(None),
                )
                .values(
                    check_in_asked_at=now,
                    check_in_deadline=now + pick(GRACE),
                    next_check_in_at=None,
                )
                .returning(TimeEntry.id)
            )
        ).scalar_one_or_none()
        if claimed is None:
            # Asked by a concurrent sweep, or stopped since. Not rolled back:
            # nothing was written, and a rollback would expire every row this
            # loop has yet to reach.
            continue
        if user.timer_check_ins_day == today:
            user.timer_check_ins_count += 1
        else:
            user.timer_check_ins_day, user.timer_check_ins_count = today, 1
        await db.commit()
        asked += 1

        # Not `tasks_service.announce`: that bumps the task's "last activity",
        # and a question nobody has answered yet is not activity on the task.
        # The ping is for the apps, which re-read the timer on it.
        await realtime.publish_task_changed(
            task_id=str(task.id), organisation_id=str(task.organisation_id), change="timer_check_in"
        )
        if user.timer_check_ins == MODE_TELEGRAM:
            running = time_tracking.format_duration(
                time_tracking.duration_seconds(started_at, None, now=now)
            )
            await _ask_on_telegram(db, user.id, entry_id, question_text(task.title, running))
    return asked


async def expire_due(db: AsyncSession, *, now: datetime) -> int:
    """Pause every timer whose question went unanswered. Returns how many."""
    from app.services import notifications, time_tracking

    rows = (
        await db.execute(
            select(TimeEntry.id, TimeEntry.user_id, User.timer_check_ins)
            .join(User, User.id == TimeEntry.user_id)
            .where(TimeEntry.ended_at.is_(None), TimeEntry.check_in_deadline <= now)
        )
    ).all()
    paused = 0
    for entry_id, user_id, mode in rows:
        if mode == MODE_OFF:
            # Turned off while a question was up: withdrawn, not left to run
            # out and pause a timer somebody has just said not to watch.
            await withdraw(db, user_id)
            continue
        ended = await time_tracking.end_unanswered(db, entry_id)
        if ended is None:
            continue
        entry, task = ended
        recorded = time_tracking.format_duration(
            time_tracking.duration_seconds(entry.started_at, entry.ended_at, now=now)
        )
        await notifications.notify(
            db,
            user_id=user_id,
            kind=KIND_TIMER_PAUSED,
            title=f"Paused your timer on “{task.title}”",
            body=(
                "Nobody answered “still working on this?”, so the timer stopped when "
                f"it asked — {recorded} recorded. Start it again when you're back."
            ),
            link_path=f"/orgs/{task.organisation_id}/tasks/{task.id}",
            organisation_id=task.organisation_id,
        )
        paused += 1
    return paused


# --- answering -----------------------------------------------------------------


async def answer(
    db: AsyncSession, user: User, *, still_working: bool, entry_id: uuid.UUID | None = None
) -> str:
    """Yes, or stop. `entry_id` pins the answer to the timer the question
    was about — a Telegram button tapped an hour late must not confirm, or
    stop, a different timer started since. Without it, the running one.

    A yes with no question open is still a yes: it pushes the next one back,
    which is what somebody saying "I'm here" means."""
    from app.services import time_tracking

    entry = await time_tracking.running_for(db, user)
    if entry is None or (entry_id is not None and entry.id != entry_id):
        return GONE
    if not still_working:
        await time_tracking.stop(db, user)
        return STOPPED
    entry.check_in_asked_at = None
    entry.check_in_deadline = None
    entry.next_check_in_at = datetime.now(UTC) + pick(EVERY)
    task_id = entry.task_id
    await db.commit()
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is not None:
        await realtime.publish_task_changed(
            task_id=str(task.id), organisation_id=str(task.organisation_id), change="timer_check_in"
        )
    return CONFIRMED


async def withdraw(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Take back an open question — for somebody who just turned check-ins off."""
    await db.execute(
        update(TimeEntry)
        .where(TimeEntry.user_id == user_id, TimeEntry.ended_at.is_(None))
        .values(check_in_asked_at=None, check_in_deadline=None)
    )
    await db.commit()


# --- Telegram ------------------------------------------------------------------


async def _ask_on_telegram(
    db: AsyncSession, user_id: uuid.UUID, entry_id: uuid.UUID, text: str
) -> None:
    """Never raises: the question is already open on the apps either way, and
    a Bot API hiccup must not stop the sweep reaching the next person."""
    from app.services import telegram as telegram_service

    chat_id = (
        await db.execute(
            select(NotificationChannel.config["chat_id"].astext).where(
                NotificationChannel.user_id == user_id,
                NotificationChannel.kind == CHANNEL_TELEGRAM,
                NotificationChannel.verified_at.is_not(None),
            )
        )
    ).scalar_one_or_none()
    if not chat_id:
        return
    try:
        await telegram_service.send_question(
            chat_id,
            text,
            [
                ("Yes, still on it", callback_data(ANSWER_YES, entry_id)),
                ("Stop the timer", callback_data(ANSWER_STOP, entry_id)),
            ],
        )
    except Exception as exc:
        logger.warning("could not ask %s on Telegram: %s", user_id, exc)
