"""Instance administration: who is on this installation, and stopping abuse.

**This is an operator capability, not an in-app role, and that is the whole
design.** There is no staff tier in this product — `users` has no `role`,
`kind` or `is_staff` column, and `tests/test_schema_invariants.py` fails the
build if one appears. Nothing here is reachable over HTTP: the only caller is
`scripts/instance.sh`, which runs inside the `api` container the same way
`scripts/reset-mfa.sh` already does. Shell access to the box *is* the
credential, and it is a better one than a login would be — whoever has it
already has Postgres and `.env`, so this grants no new power, it only makes
power they already hold ergonomic. A web backoffice would instead be the
single highest-value account on the instance, phishable and brute-forceable,
guarding data that organisation admins deliberately cannot reach.

**Metadata only. Nothing here reads anybody's content.** Counts, dates and
names — never a task title, a comment, a private note or a file. That is not
squeamishness: this product makes hard promises that a browsing backoffice
would quietly void (a hidden task is invisible to organisation admins,
`services/notes.py` has no override branch at all, an export is the
requester's "not even an admin's"). Spam triage needs volume and timing, not
prose, so there is no reason to spend those promises. An organisation's
*name* is the one judgement call, and it is included because a name is what
a spam organisation is usually recognised by.

**Suspension is upstream of the access model, never inside it.**
`users.disabled_at` decides whether an account works at all; it says nothing
about what a working account may do, which still comes from membership and
grants alone. `services/access.py` never reads it, and a test asserts that
stays true.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organisation, OrganisationMember, Task, User
from app.models.organisation import STATUS_ACTIVE


@dataclass(frozen=True)
class Totals:
    users: int
    disabled_users: int
    organisations: int
    tasks: int
    users_last_24h: int
    organisations_last_24h: int


@dataclass(frozen=True)
class UserRow:
    id: uuid.UUID
    email: str
    display_name: str | None
    created_at: datetime
    disabled_at: datetime | None
    disabled_reason: str | None
    organisations: int
    tasks: int


@dataclass(frozen=True)
class OrganisationRow:
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    owner_email: str | None
    members: int
    tasks: int


async def totals(db: AsyncSession) -> Totals:
    """The headline numbers, in one round trip rather than six.

    Scalar subqueries rather than joins: counting three unrelated tables in
    one statement by joining them multiplies the rows together, which is the
    classic way to report a task count times a member count and not notice.
    """
    stmt = select(
        select(func.count()).select_from(User).scalar_subquery(),
        select(func.count()).select_from(User).where(User.disabled_at.isnot(None)).scalar_subquery(),
        select(func.count()).select_from(Organisation).scalar_subquery(),
        select(func.count()).select_from(Task).scalar_subquery(),
        select(func.count())
        .select_from(User)
        .where(User.created_at > func.now() - func.make_interval(0, 0, 0, 1))
        .scalar_subquery(),
        select(func.count())
        .select_from(Organisation)
        .where(Organisation.created_at > func.now() - func.make_interval(0, 0, 0, 1))
        .scalar_subquery(),
    )
    row = (await db.execute(stmt)).one()
    return Totals(*row)


def _org_count() -> object:
    return (
        select(func.count())
        .select_from(OrganisationMember)
        .where(
            OrganisationMember.user_id == User.id,
            OrganisationMember.status == STATUS_ACTIVE,
        )
        .correlate(User)
        .scalar_subquery()
    )


def _task_count() -> object:
    return (
        select(func.count())
        .select_from(Task)
        .where(Task.owner_user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )


async def list_users(
    db: AsyncSession, *, limit: int = 50, offset: int = 0, newest_first: bool = True
) -> tuple[list[UserRow], int]:
    """One page of accounts with their counts, and the total.

    Correlated scalar subqueries for the two counts rather than two GROUP BY
    joins, for the same reason `_inherited_project_rank` uses one: a join
    changes the statement's shape and a person with no organisations must
    still come back with a zero rather than dropping out of the list.
    `COUNT(*) OVER ()` supplies the total in the same statement, exactly as
    `access.paged_tasks_stmt` does for the task list.
    """
    order = User.created_at.desc() if newest_first else User.created_at.asc()
    stmt = (
        select(
            User.id,
            User.email,
            User.display_name,
            User.created_at,
            User.disabled_at,
            User.disabled_reason,
            _org_count(),
            _task_count(),
            func.count().over().label("total"),
        )
        .order_by(order, User.id)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return [], 0
    return [UserRow(*r[:-1]) for r in rows], rows[0][-1]


async def list_organisations(
    db: AsyncSession, *, limit: int = 50, offset: int = 0, newest_first: bool = True
) -> tuple[list[OrganisationRow], int]:
    """One page of organisations with member and task counts, and the total.

    The owner's email comes from the membership rows rather than a column on
    `organisations`, because that is where the role actually lives — the
    creator is the first owner but ownership can move, and reading
    `created_by_user_id` would report whoever *made* it, which is a different
    question from who runs it now.
    """
    members = (
        select(func.count())
        .select_from(OrganisationMember)
        .where(
            OrganisationMember.organisation_id == Organisation.id,
            OrganisationMember.status == STATUS_ACTIVE,
        )
        .correlate(Organisation)
        .scalar_subquery()
    )
    tasks = (
        select(func.count())
        .select_from(Task)
        .where(Task.organisation_id == Organisation.id)
        .correlate(Organisation)
        .scalar_subquery()
    )
    owner = (
        select(User.email)
        .select_from(OrganisationMember)
        .join(User, User.id == OrganisationMember.user_id)
        .where(
            OrganisationMember.organisation_id == Organisation.id,
            OrganisationMember.role == "owner",
            OrganisationMember.status == STATUS_ACTIVE,
        )
        .order_by(OrganisationMember.created_at)
        .limit(1)
        .correlate(Organisation)
        .scalar_subquery()
    )
    order = Organisation.created_at.desc() if newest_first else Organisation.created_at.asc()
    stmt = (
        select(
            Organisation.id,
            Organisation.name,
            Organisation.slug,
            Organisation.created_at,
            owner,
            members,
            tasks,
            func.count().over().label("total"),
        )
        .order_by(order, Organisation.id)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return [], 0
    return [OrganisationRow(*r[:-1]) for r in rows], rows[0][-1]


async def find_user(db: AsyncSession, identifier: str) -> User | None:
    """By email, or by id — an operator has whichever is to hand."""
    identifier = identifier.strip()
    try:
        as_id = uuid.UUID(identifier)
    except ValueError:
        as_id = None
    where = User.id == as_id if as_id else User.email == identifier.lower()
    return (await db.execute(select(User).where(where))).scalar_one_or_none()


async def set_disabled(
    db: AsyncSession, user: User, *, disabled: bool, reason: str | None = None
) -> bool:
    """Suspend or restore an account. Returns whether anything changed.

    **Only the flag is written here; revoking their live sessions is the
    caller's job** (`scripts/instance.sh` does it through SuperTokens, which
    owns sessions). Splitting it that way keeps this module free of a
    SuperTokens import for a decision that is purely about a database row —
    and the flag has to land first regardless, or a session revoked while
    sign-in is still permitted just sends them to the login screen and
    straight back in.
    """
    already = user.disabled_at is not None
    if already == disabled:
        return False
    values = (
        {"disabled_at": func.now(), "disabled_reason": (reason or None)}
        if disabled
        else {"disabled_at": None, "disabled_reason": None}
    )
    await db.execute(update(User).where(User.id == user.id).values(**values))
    await db.commit()
    return True


__all__ = [
    "OrganisationRow",
    "Totals",
    "UserRow",
    "find_user",
    "list_organisations",
    "list_users",
    "set_disabled",
    "totals",
]
