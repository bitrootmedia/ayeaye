"""The weekly report: last week in an organisation, for the people who run it.

Monday morning, to every owner and admin: articles added, facts added,
hours logged by each person, tasks opened and tasks closed — the week as the
organisation's admins would want it in one message rather than five screens.

**Seen as the recipient, not as the organisation.** Every list composes the
same access builders the screens use, run as the admin it is going to: a
somebody-else's hidden task, a private draft article and the hours on a
hidden task are missing here exactly as they are missing from the board,
the contents and the work report. An admin already sees everything else.
A report is not the place for a second exception (`services/access.py`
says why there is only one).

**Same claim and timing as the daily digest**, deliberately: one
conditional UPDATE (`last_weekly_report_sent_on`, a date), gated on Monday
and on the person's own `daily_summary_hour` in their own zone, strict
equality for the same reason — a missed tick costs one report, where "at or
after" would let a worker that was down all morning send it at midnight.
One hour setting, not two: a second picker for a weekly message is a second
thing to find.

**"Last week" is the recipient's**, Monday 00:00 to Monday 00:00 in their
zone. A team across zones gets reports whose edges differ by a few hours,
which is the honest reading of "the week" for each of them.

**One per organisation, never merged, and none for a quiet one** — the
digest's rules, for the digest's reasons.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Article,
    ArticleRevision,
    Book,
    Organisation,
    OrganisationMember,
    Task,
    User,
)
from app.models.organisation import ROLES, STATUS_ACTIVE
from app.services import access, work_reports
from app.services.organisations import OrgContext

# How many titles each section lists. The counts are always whole; the list
# is for reading, and the link is for the rest.
LIST_LIMIT = 10
# A fact is a few sentences; the report quotes its start.
FACT_PREVIEW = 120
# `access.administers_organisation`, as a list a WHERE clause can use.
ADMIN_ROLES = tuple(r for r in ROLES if access.administers_organisation(r))


# --- pure. no database. ------------------------------------------------------


def last_week(today: date) -> tuple[date, date]:
    """Monday to Sunday of the week before the one `today` is in."""
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday - timedelta(days=1)


def preview(text: str, limit: int = FACT_PREVIEW) -> str:
    """The first line of a fact, cut at a word if it runs long."""
    line = " ".join(text.split())
    if len(line) <= limit:
        return line
    cut = line[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "…"


@dataclass
class OrgWeek:
    organisation_id: uuid.UUID
    organisation_name: str
    since: date
    until: date
    total_seconds: int = 0
    by_person: list[tuple[str, int]] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    opened_count: int = 0
    closed: list[str] = field(default_factory=list)
    closed_count: int = 0
    articles: list[str] = field(default_factory=list)
    articles_count: int = 0
    facts: list[str] = field(default_factory=list)
    facts_count: int = 0

    @property
    def is_quiet(self) -> bool:
        return not (
            self.total_seconds
            or self.opened_count
            or self.closed_count
            or self.articles_count
            or self.facts_count
        )


def week_label(since: date, until: date) -> str:
    """`19–25 Oct 2026`, or `27 Oct – 2 Nov 2026` across a month."""
    if since.month == until.month:
        return f"{since.day}–{until.day} {until:%b %Y}"
    if since.year == until.year:
        return f"{since.day} {since:%b} – {until.day} {until:%b %Y}"
    return f"{since.day} {since:%b %Y} – {until.day} {until:%b %Y}"


def render(week: OrgWeek) -> tuple[str, str]:
    """The notification's title and plain-text body. Empty sections are
    left out rather than reported as zero — except the counts line, which
    says the whole week in one glance."""
    from app.services.time_tracking import format_duration

    title = f"Week of {week_label(week.since, week.until)} in {week.organisation_name}"
    lines = [
        f"{format_duration(week.total_seconds)} logged · "
        f"{week.opened_count} tasks opened · {week.closed_count} closed · "
        f"{week.articles_count} articles · {week.facts_count} facts"
    ]

    def section(heading: str, items: list[str], count: int) -> None:
        if not count:
            return
        lines.append("")
        lines.append(f"{heading} ({count}):")
        lines.extend(f"- {item}" for item in items)
        if count > len(items):
            lines.append(f"- …and {count - len(items)} more")

    if week.total_seconds:
        lines.append("")
        lines.append("Time by person:")
        lines.extend(f"- {name}: {format_duration(s)}" for name, s in week.by_person)
    section("Tasks opened", week.opened, week.opened_count)
    section("Tasks closed", week.closed, week.closed_count)
    section("Articles added", week.articles, week.articles_count)
    section("Facts added", week.facts, week.facts_count)
    return title, "\n".join(lines)


# --- the sweep ---------------------------------------------------------------


def _zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _administers():
    """This user is an active owner or admin somewhere — the only people a
    report is for, so the claim never stamps anybody else."""
    return exists().where(
        OrganisationMember.user_id == User.id,
        OrganisationMember.status == STATUS_ACTIVE,
        OrganisationMember.role.in_(ADMIN_ROLES),
    )


async def timezones_in_use(db: AsyncSession) -> list[str]:
    rows = (
        await db.execute(
            select(func.coalesce(User.timezone, "UTC"))
            .where(User.weekly_report_enabled.is_(True), _administers())
            .distinct()
        )
    ).scalars().all()
    return list(rows)


async def claim(
    db: AsyncSession, *, tz_name: str, now: datetime | None = None
) -> list[uuid.UUID]:
    """Claim every admin in this zone whose Monday hour has just struck.
    `now` is only ever passed by a test."""
    now = (now or datetime.now(_zone(tz_name))).astimezone(_zone(tz_name))
    if now.weekday() != 0:
        return []
    today = now.date()
    rows = (
        await db.execute(
            update(User)
            .where(
                User.weekly_report_enabled.is_(True),
                User.disabled_at.is_(None),
                func.coalesce(User.timezone, "UTC") == tz_name,
                User.daily_summary_hour == now.hour,
                (User.last_weekly_report_sent_on.is_(None))
                | (User.last_weekly_report_sent_on < today),
                _administers(),
            )
            .values(last_weekly_report_sent_on=today)
            .returning(User.id)
        )
    ).scalars().all()
    await db.commit()
    return list(rows)


def _name(user: User | None) -> str:
    if user is None:
        return "nobody"
    return user.display_name or user.email or "someone"


async def for_org(
    db: AsyncSession, ctx: OrgContext, user: User, *, since: date, until: date
) -> OrgWeek:
    """One organisation's week, as `user` may see it."""
    tz = work_reports.zone(user.timezone)
    start, end = work_reports.window(since, until, tz, now=datetime.now(tz))
    org = ctx.organisation
    week = OrgWeek(org.id, org.name, since, until)

    time = await work_reports.report(
        db, ctx, user, since=since, until=until, tz_name=user.timezone
    )
    week.total_seconds = time["total_seconds"]
    week.by_person = [(p["name"], p["seconds"]) for p in time["by_person"]]

    visible = access.visible_task_ids_stmt(user_id=user.id, org_id=org.id, org_role=ctx.role)
    owner = User.__table__.alias("owner")

    async def tasks(column) -> tuple[list[str], int]:
        where = (Task.id.in_(visible), column >= start, column < end)
        count = (await db.execute(select(func.count()).where(*where))).scalar_one()
        rows = (
            await db.execute(
                select(Task.title, owner.c.display_name, owner.c.email)
                .outerjoin(owner, owner.c.id == Task.owner_user_id)
                .where(*where)
                .order_by(column)
                .limit(LIST_LIMIT)
            )
        ).all()
        return [f"{t} ({n or e})" if (n or e) else t for t, n, e in rows], count

    week.opened, week.opened_count = await tasks(Task.created_at)
    week.closed, week.closed_count = await tasks(Task.closed_at)

    # Published ones only: a draft is its owner's until they say otherwise,
    # and "added" means added to what everybody reads.
    latest_title = (
        select(ArticleRevision.title)
        .where(ArticleRevision.article_id == Article.id)
        .order_by(ArticleRevision.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    articles = (
        access.visible_articles_stmt(user_id=user.id, org_id=org.id, org_role=ctx.role)
        .where(Article.is_private.is_(False), Article.created_at >= start, Article.created_at < end)
        .subquery()
    )
    week.articles_count = (
        await db.execute(select(func.count()).select_from(articles))
    ).scalar_one()
    rows = (
        await db.execute(
            select(latest_title, Book.name)
            .select_from(Article)
            .join(Book, Book.id == Article.book_id)
            .where(Article.id.in_(select(articles.c.id)))
            .order_by(Article.created_at)
            .limit(LIST_LIMIT)
        )
    ).all()
    week.articles = [f"{t or 'Untitled'} ({b})" for t, b in rows]

    facts = access.visible_facts_stmt(user_id=user.id, org_id=org.id, org_role=ctx.role).subquery()
    fact_window = (facts.c.created_at >= start, facts.c.created_at < end)
    week.facts_count = (
        await db.execute(select(func.count()).select_from(facts).where(*fact_window))
    ).scalar_one()
    rows = (
        await db.execute(
            select(facts.c.body, Book.name)
            .join(Book, Book.id == facts.c.book_id)
            .where(*fact_window)
            .order_by(facts.c.created_at)
            .limit(LIST_LIMIT)
        )
    ).all()
    week.facts = [f"{preview(body)} ({b})" for body, b in rows]
    return week


async def for_user(db: AsyncSession, user: User, *, today: date) -> list[OrgWeek]:
    """Every organisation this person administers, with something to say."""
    since, until = last_week(today)
    rows = (
        await db.execute(
            select(Organisation, OrganisationMember)
            .join(OrganisationMember, OrganisationMember.organisation_id == Organisation.id)
            .where(
                OrganisationMember.user_id == user.id,
                OrganisationMember.status == STATUS_ACTIVE,
                OrganisationMember.role.in_(ADMIN_ROLES),
            )
            .order_by(Organisation.name)
        )
    ).all()
    out = []
    for org, membership in rows:
        week = await for_org(
            db, OrgContext(organisation=org, membership=membership), user, since=since, until=until
        )
        if not week.is_quiet:
            out.append(week)
    return out


__all__ = [
    "LIST_LIMIT",
    "OrgWeek",
    "claim",
    "for_org",
    "for_user",
    "last_week",
    "preview",
    "render",
    "timezones_in_use",
    "week_label",
]
