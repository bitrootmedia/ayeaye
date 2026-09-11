"""Instance administration: who is on this installation, and stopping abuse.

**Two front doors, and the split between them is the whole design.**
`scripts/instance.sh` runs inside the `api` container the way
`scripts/reset-mfa.sh` does, and the `/api/instance/*` routes serve the web
panel at `/instance` for anybody holding an `instance_admins` row. This
module is the single implementation behind both — there is no second set of
queries for the screen.

It did not start that way: this was a shell tool alone, on the reasoning that
a web backoffice is the highest-value account on an instance, phishable and
brute-forceable in a way an SSH key is not. That reasoning still holds and is
the reason for every restriction below; what changed is the product decision
that an operator should be able to do this from the app. The mitigations are
what survived, and they are load-bearing rather than decorative:

* **The panel cannot appoint its own successors.** `instance_admins` rows are
  granted and revoked from the shell only (`grant-admin`/`revoke-admin`).
  One stolen session cannot become a permanent one, and it cannot widen the
  blast radius beyond itself.
* **An instance admin has no extra power inside any organisation.**
  `services/access.py` never learns this table exists — a hidden task stays
  hidden from them, a private note stays private, an export stays the
  requester's. `tests/test_schema_invariants.py` asserts that, exactly as it
  already asserts it of `users.disabled_at`.
* **Metadata only** (below), so the panel cannot browse anybody's content
  even though it can count it.

**There is still no staff tier.** `users` has no `role`, `kind` or `is_staff`
column and a test fails the build if one appears; being an instance admin is
a row in its own table, and it answers a different question from any role —
see `models/instance_admin.py`.

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
`users.disabled_at` decides whether an account works at all;
`organisations.suspended_at` decides whether an organisation does. Neither
says anything about what a working account may do inside a working
organisation, which still comes from membership and grants alone.
`services/access.py` reads neither, and a test asserts that stays true — the
enforcement points are `deps.get_current_user` and
`organisations.context_for`, both upstream of every visibility expression.

**"Last active" is derived, never stamped.** There is no `last_seen_at`
column and deliberately so: keeping one accurate means a write on the request
hot path for every signed-in person. Instead it is the newest of the things
somebody actually *did* — a task event, a time entry, a comment, a sign-in —
as four correlated subqueries under one `GREATEST`. The honest caveat, worth
knowing before reading the column as "last seen": **somebody who only reads
looks idle.** For triage that is the right bias anyway, since the thing being
looked for is people generating volume.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InstanceAdmin,
    LoginEvent,
    Message,
    Organisation,
    OrganisationMember,
    Task,
    TaskEvent,
    TimeEntry,
    User,
)
from app.models.organisation import STATUS_ACTIVE

logger = logging.getLogger("app.services.instance")


@dataclass(frozen=True)
class Totals:
    users: int
    disabled_users: int
    organisations: int
    suspended_organisations: int
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
    #: Derived, never stamped — see the module docstring. NULL for somebody
    #: who has signed up and not yet done anything, which is exactly the
    #: shape a registration script leaves behind.
    last_active_at: datetime | None
    is_instance_admin: bool


@dataclass(frozen=True)
class OrganisationRow:
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    owner_email: str | None
    members: int
    tasks: int
    #: The newest `tasks.updated_at` in it. That column is "last activity"
    #: by this product's own definition rather than "last row update" — a
    #: comment, a file, a tag or an hour logged all stamp it through
    #: `tasks_service.announce()` — so one subquery answers the question
    #: honestly where four would only add cost.
    last_active_at: datetime | None
    suspended_at: datetime | None
    suspended_reason: str | None


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
        select(func.count())
        .select_from(Organisation)
        .where(Organisation.suspended_at.isnot(None))
        .scalar_subquery(),
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


def _last_active() -> object:
    """The newest thing this person actually did.

    Four correlated `MAX`es under one `GREATEST`, chosen over a stamped
    `users.last_seen_at` column because keeping that accurate costs a write
    on the request hot path for every signed-in person — see the module
    docstring. Postgres' `GREATEST` skips NULLs and only returns NULL when
    every argument is, which is what makes "signed up and never did
    anything" come back as a real NULL rather than an epoch date.

    `login_events` joins on `supertokens_user_id` rather than `users.id`,
    because that table deliberately isn't foreign-keyed to `users` — the
    local row is created lazily and doesn't exist yet when a brand-new
    signup's first session is made (see `models/login_event.py`).
    """
    newest = [
        select(func.max(TaskEvent.created_at))
        .where(TaskEvent.actor_user_id == User.id)
        .correlate(User)
        .scalar_subquery(),
        select(func.max(TimeEntry.started_at))
        .where(TimeEntry.user_id == User.id)
        .correlate(User)
        .scalar_subquery(),
        select(func.max(Message.created_at))
        .where(Message.user_id == User.id)
        .correlate(User)
        .scalar_subquery(),
        select(func.max(LoginEvent.created_at))
        .where(LoginEvent.supertokens_user_id == User.supertokens_user_id)
        .correlate(User)
        .scalar_subquery(),
    ]
    return func.greatest(*newest)


def _is_admin_flag() -> object:
    """Whether this account holds an `instance_admins` row. Shown so the
    panel can mark its own operators — and so a lone admin can see that they
    are the lone admin before suspending themselves."""
    return (
        select(func.count())
        .select_from(InstanceAdmin)
        .where(InstanceAdmin.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    ) > 0


def _task_count() -> object:
    return (
        select(func.count())
        .select_from(Task)
        .where(Task.owner_user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )


async def list_users(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    newest_first: bool = True,
    q: str = "",
) -> tuple[list[UserRow], int]:
    """One page of accounts with their counts, and the total.

    Correlated scalar subqueries for the counts rather than GROUP BY joins,
    for the same reason `_inherited_project_rank` uses one: a join changes
    the statement's shape and a person with no organisations must still come
    back with a zero rather than dropping out of the list. `COUNT(*) OVER ()`
    supplies the total in the same statement, exactly as
    `access.paged_tasks_stmt` does for the task list.

    **`q` is a plain prefix/substring match, not `search_service.matches`.**
    An operator looking somebody up has the address in front of them — off a
    support ticket or an abuse report — and wants that person, not five
    people whose addresses rhyme with theirs. Typo tolerance is right for a
    palette and wrong for a lookup that ends in suspending an account.
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
            _last_active(),
            _is_admin_flag(),
            func.count().over().label("total"),
        )
        .order_by(order, User.id)
        .limit(limit)
        .offset(offset)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.display_name.ilike(like)))
    rows = (await db.execute(stmt)).all()
    if not rows:
        return [], 0
    return [UserRow(*r[:-1]) for r in rows], rows[0][-1]


async def list_organisations(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    newest_first: bool = True,
    q: str = "",
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
    # "Last activity", using the column that already means exactly that:
    # `tasks.updated_at` is stamped by `tasks_service.announce()` for a
    # comment, a file, a tag or an hour logged, not just a row edit.
    last_active = (
        select(func.max(Task.updated_at))
        .where(Task.organisation_id == Organisation.id)
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
            last_active,
            Organisation.suspended_at,
            Organisation.suspended_reason,
            func.count().over().label("total"),
        )
        .order_by(order, Organisation.id)
        .limit(limit)
        .offset(offset)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Organisation.name.ilike(like), Organisation.slug.ilike(like)))
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


async def find_organisation(db: AsyncSession, identifier: str) -> Organisation | None:
    """By id or by slug — an operator has whichever is to hand.

    Deliberately **not** by name: names are not unique, and the one command
    here that takes an organisation suspends it.
    """
    identifier = identifier.strip()
    try:
        as_id = uuid.UUID(identifier)
    except ValueError:
        as_id = None
    where = Organisation.id == as_id if as_id else Organisation.slug == identifier.lower()
    return (await db.execute(select(Organisation).where(where))).scalar_one_or_none()


async def set_organisation_suspended(
    db: AsyncSession, organisation: Organisation, *, suspended: bool, reason: str | None = None
) -> bool:
    """Lock an organisation, or unlock it. Returns whether anything changed.

    **Non-destructive, and enforced in exactly one place.** Nothing is
    deleted; `organisations.context_for` refuses while the flag is set, which
    is upstream of every visibility expression, so there is no second check
    anywhere to keep in sync and `services/access.py` stays ignorant of it.
    Clearing the flag puts every member back exactly where they were.

    No sessions are revoked, unlike suspending an *account*: the people in a
    suspended organisation may be perfectly legitimate members of others, and
    signing them out of the whole product would be punishing them for it.
    """
    already = organisation.suspended_at is not None
    if already == suspended:
        return False
    values = (
        {"suspended_at": func.now(), "suspended_reason": (reason or None)}
        if suspended
        else {"suspended_at": None, "suspended_reason": None}
    )
    await db.execute(
        update(Organisation).where(Organisation.id == organisation.id).values(**values)
    )
    await db.commit()
    return True


async def revoke_sessions(supertokens_user_id: str) -> int:
    """Sign somebody out everywhere. Returns how many sessions went.

    SuperTokens owns sessions, so this is its call to make rather than a row
    we could clear ourselves — which is why it lives beside `set_disabled`
    rather than inside it: that function writes one database row and should
    not drag a SuperTokens import into every caller that only wants the flag.

    **Never fatal.** The suspension has already landed by the time this runs,
    and an unreachable core must not leave the operator believing nothing
    happened when the important half did. `deps.get_current_user` turns an
    already-open tab away on its next request regardless, which is the belt
    to this braces.

    `init_auth()` rather than `create_app()`: the recipes have to be
    registered before any SuperTokens call, and the CLI process has done
    neither — building the whole FastAPI app for the same side effect would
    also mount every router and open a second engine for no reason. Inside
    the API it has already run and this is a no-op.
    """
    try:
        from supertokens_python.recipe.session.asyncio import revoke_all_sessions_for_user

        from app.security.authn import init_auth

        init_auth()
        return len(await revoke_all_sessions_for_user(supertokens_user_id))
    except Exception:  # pragma: no cover - depends on a live core
        logger.warning("could not revoke sessions for %s", supertokens_user_id, exc_info=True)
        return 0


# --- who administers the installation ---------------------------------------


async def is_instance_admin(db: AsyncSession, user: User) -> bool:
    """One row lookup. Called on `/me` and on every `/api/instance/*`
    request, so it stays a primary-key-shaped hit on a tiny table rather than
    anything cached — a revoked admin must stop being one on their next
    request, not on their next sign-in."""
    found = await db.execute(select(InstanceAdmin.id).where(InstanceAdmin.user_id == user.id))
    return found.scalar_one_or_none() is not None


async def list_admins(db: AsyncSession) -> list[tuple[User, InstanceAdmin]]:
    """Everybody holding the row. Not paged: an installation with enough
    instance admins to need a second page has a different problem."""
    rows = (
        await db.execute(
            select(User, InstanceAdmin)
            .join(InstanceAdmin, InstanceAdmin.user_id == User.id)
            .order_by(InstanceAdmin.created_at)
        )
    ).all()
    return [(u, a) for u, a in rows]


async def grant_admin(db: AsyncSession, user: User, *, note: str | None = None) -> bool:
    """Make somebody an instance admin. Returns whether anything changed.

    **Reachable from the shell alone**, never from the panel this unlocks —
    see `models/instance_admin.py`. A screen that can appoint its own
    successors turns one stolen session into a permanent foothold.
    """
    if await is_instance_admin(db, user):
        return False
    db.add(InstanceAdmin(user_id=user.id, note=(note or None)))
    await db.commit()
    return True


async def revoke_admin(db: AsyncSession, user: User) -> bool:
    """Take it away. Returns whether anything changed.

    No last-admin guard, deliberately — unlike an organisation's last owner,
    which `services/organisations.py` protects because nobody else could
    administer it afterwards. There is always a way back here: the shell.
    Somebody who can run this command can run `grant-admin` a second later,
    so refusing would protect nothing and would be one more rule to explain.
    """
    result = await db.execute(delete(InstanceAdmin).where(InstanceAdmin.user_id == user.id))
    await db.commit()
    return bool(result.rowcount)


__all__ = [
    "OrganisationRow",
    "Totals",
    "UserRow",
    "find_organisation",
    "find_user",
    "grant_admin",
    "is_instance_admin",
    "list_admins",
    "list_organisations",
    "list_users",
    "revoke_admin",
    "revoke_sessions",
    "set_disabled",
    "set_organisation_suspended",
    "totals",
]
