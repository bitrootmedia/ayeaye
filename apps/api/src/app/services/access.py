"""Who can see what. Read this before touching anything that lists projects.

Four rules. Everything in this file, and every list endpoint in the product,
follows from them.

1. **A project is private until it is shared.** Creating one does not show it
   to your colleagues. The only ways in are: you own it, someone granted it to
   you by name, someone granted it to a team you're in, or you administer the
   organisation. There is no org-wide implicit read, and no group-wide one
   either — a project group is a label, not an access boundary.

2. **Most-permissive-wins.** Your effective level is the MAX over every route
   you have to the thing: your own grant, your teams' grants, ownership,
   organisation role. The consequence, stated out loud because people expect
   otherwise: **you cannot carve an exception out of a broader grant.** If the
   Design team can write, you cannot make one member of Design read-only. That
   would need deny rules. Don't add them — they turn every "why can't I see
   this" into a search rather than a lookup.

3. **No access reads as 404, never 403.** A project you have no part in must
   not be distinguishable from one that doesn't exist. 403 means only "you can
   see this, but not at that level" — and it is the *right* answer there,
   because telling someone their access is read-only is not a leak.

4. **Every list endpoint resolves access in ONE statement.** The builders below
   return a `Select`. Never filter a list in Python, and never check access
   per-row inside a loop: it is the difference between one query and one query
   per project, and it silently stops being correct the moment someone adds
   pagination on top of it.

## The one exception, and why it isn't rule 2 in disguise

**A hidden task is visible to its owner and to nobody else** — not to grantees,
not through its project, not to organisation admins. That is a product
decision (CLAUDE.md), and it is the only place in this product where access is
subtracted.

It is deliberately **not** modelled as a deny rule. A deny rule competes with
grants: it joins the `GREATEST`, and answering "why can't I see this" becomes a
search through every route. `hidden_at` instead **short-circuits ahead of the
whole expression** — if it is set and you are not the owner, no route is
resolved at all. One clause, at the top, in both `effective_task_level` and
`task_level_expression`. Rule 2 is untouched: the grants are still there,
un-hiding restores every one of them, and nothing has to be re-granted.

The cost is real and worth stating: **hiding removes an organisation admin's
escape hatch.** If the owner leaves, the only way back in is offboarding, which
reassigns ownership — and the new owner can then see it. That is the recovery
path; there is no other, and there should not be one, or "hidden" would mean
"hidden from colleagues" and the screen would be lying.

## Why there is no policy engine

Every question here is per-resource and dynamic. Plain RBAC with string
matching can express neither "may user U read project 47" nor "list every
project U can see", and the second one is what every screen in this product
asks. That is the whole argument in PLAN.md §2.1, and it is why authorization
is 200 lines of SQL builders rather than a policy store, an adapter and a
second place to look when something is denied.

## Levels

`read` < `write` < `owner`. Only `read` and `write` are ever stored;
`owner` is what being the project's owner or an organisation admin **resolves
to**. Storing it would create a second answer to "who owns this" that could
disagree with `projects.owner_user_id`.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import Select, and_, case, func, literal, or_, select
from sqlalchemy.orm import aliased

from app.models.knowledge_base import Article, Book, BookMember
from app.models.organisation import ROLE_ADMIN, ROLE_RANK
from app.models.structure import (
    LEVEL_OWNER,
    LEVEL_RANK,
    LEVEL_READ,
    LEVEL_WRITE,
    Project,
    ProjectMember,
    TeamMember,
)
from app.models.task import PRIORITY_RANK, STATUS_RANK, Task, TaskGrant
from app.models.user import User

# Ranks are what SQL compares; `_LEVEL_BY_RANK` turns the winner back into a
# name on the way out. -1 means "no route at all", which is the 404 case.
NO_ACCESS = -1
_LEVEL_BY_RANK = {v: k for k, v in LEVEL_RANK.items()}


# --- pure. no database, no request. ------------------------------------------


def level_name(rank: int) -> str | None:
    """`2 -> "owner"`, `-1 -> None`."""
    return _LEVEL_BY_RANK.get(rank)


def level_rank(level: str | None) -> int:
    return LEVEL_RANK.get(level or "", NO_ACCESS)


def administers_organisation(org_role: str) -> bool:
    """Organisation owners and admins see everything in their organisation.

    This is a product decision, not a convenience: without it, the day the only
    person who could see a project leaves is the day that project becomes
    unreachable, and a self-hosted product has no support desk to call.
    """
    return ROLE_RANK.get(org_role, -1) >= ROLE_RANK[ROLE_ADMIN]


def effective_task_level(
    *,
    org_role: str,
    is_owner: bool = False,
    is_action_required: bool = False,
    is_creator: bool = False,
    is_hidden: bool = False,
    project_level: str | None = None,
    direct: str | None = None,
    via_teams: tuple[str, ...] = (),
) -> str | None:
    """Rule 2 for a task, which has more routes in than a project.

    **`is_hidden` is checked first and returns immediately.** It is not a route
    with a low rank and it is not a deny rule — it decides whether the routes
    are consulted at all. Written this way so that reading the function tells
    you, in the first two lines, that ownership is the only thing that survives
    hiding.

    Six routes, and each exists for a reason worth keeping:

    * **owner** → `owner`. Responsible for it, and the only person who may
      close it.
    * **action required** → `write`. You cannot ask someone to act on
      something they can't open, so being named carries its own access — even
      on a project they've never been given.
    * **creator** → `read`. So filing a task and then handing it over doesn't
      make it vanish from your view.
    * **the project**, if it has one. This is rule 1 flowing down: whatever you
      have on the project, you have on its tasks.
    * **a direct task grant**, and **a task grant to a team you're in**.
      Additive to the project, never subtractive.
    * **organisation admin** → `owner`.

    A **loose task** — one with no project — is exactly this with the project
    route absent. That is the whole of PLAN.md §4's loose-task question: it is
    visible to its creator, owner, action-required user, explicit grantees and
    org admins, and to nobody else in the organisation. "No project" is a
    deliberate choice, not a leak.
    """
    if is_hidden:
        return LEVEL_OWNER if is_owner else None
    ranks = [
        level_rank(project_level),
        level_rank(direct),
        *(level_rank(t) for t in via_teams),
    ]
    if is_action_required:
        ranks.append(LEVEL_RANK[LEVEL_WRITE])
    if is_creator:
        ranks.append(LEVEL_RANK[LEVEL_READ])
    if is_owner or administers_organisation(org_role):
        ranks.append(LEVEL_RANK[LEVEL_OWNER])
    return level_name(max(ranks, default=NO_ACCESS))


def effective_level(
    *,
    is_owner: bool,
    org_role: str,
    direct: str | None = None,
    via_teams: tuple[str, ...] = (),
) -> str | None:
    """Rule 2, in one place, so the SQL below has something to be tested against.

    The Python and the SQL are two implementations of the same rule. This one
    is what the test matrix exercises exhaustively; keeping them in step is why
    they're in the same module.

    Generic over *which* resource — a project's or a book's grants are the
    identical shape (owner, a direct grant, a team grant, organisation role),
    so this same function is `effective_book_level` too. Nothing book-specific
    to add.
    """
    ranks = [level_rank(direct), *(level_rank(t) for t in via_teams)]
    if is_owner or administers_organisation(org_role):
        ranks.append(LEVEL_RANK[LEVEL_OWNER])
    best = max(ranks, default=NO_ACCESS)
    return level_name(best)


def effective_article_level(
    *,
    org_role: str,
    is_owner: bool = False,
    is_private: bool = False,
    book_level: str | None = None,
) -> str | None:
    """Rule 2 for an article — the identical shape `effective_task_level`
    already uses for `is_hidden`, just with fewer routes in: an article has
    no action-required or creator route, only the book's level plus
    ownership.

    **`is_private` is checked first and returns immediately.** Not a route
    with a low rank and not a deny rule — it decides whether the book route
    is consulted at all, so only the owner survives it. See this module's
    own docstring on `effective_task_level` for the full reasoning; it
    applies here unchanged, down to the consequence that an organisation
    admin cannot see a private article either.
    """
    if is_private:
        return LEVEL_OWNER if is_owner else None
    ranks = [level_rank(book_level)]
    if is_owner or administers_organisation(org_role):
        ranks.append(LEVEL_RANK[LEVEL_OWNER])
    return level_name(max(ranks, default=NO_ACCESS))


def can_read(level: str | None) -> bool:
    return level_rank(level) >= LEVEL_RANK[LEVEL_READ]


def can_write(level: str | None) -> bool:
    return level_rank(level) >= LEVEL_RANK[LEVEL_WRITE]


def can_administer(level: str | None) -> bool:
    """Grant and revoke access, rename, archive, delete, hand over ownership.

    Owner-only by design (the product decision in CLAUDE.md): a `write`
    grantee edits the work, but who else can see it stays with the person
    responsible for it. Organisation admins resolve to `owner`, so they qualify.
    """
    return level_rank(level) >= LEVEL_RANK[LEVEL_OWNER]


# --- the SQL. one statement, always. -----------------------------------------


def _grant_rank_subquery(user_id: uuid.UUID):
    """The best level this user has on a project through a stored grant.

    Covers both principals in one pass: a direct grant naming them, or a grant
    naming a team they belong to. The LEFT JOIN is what lets a single OR test
    both — an inner join would drop every direct grant, because a direct grant
    has a NULL `team_id` and matches no team member row.

    Correlated to `Project`, so it composes into the outer statement rather
    than becoming a second query.
    """
    tm = aliased(TeamMember)
    return (
        select(
            func.max(
                case(
                    (ProjectMember.level == LEVEL_WRITE, LEVEL_RANK[LEVEL_WRITE]),
                    else_=LEVEL_RANK[LEVEL_READ],
                )
            )
        )
        .select_from(ProjectMember)
        .outerjoin(tm, and_(tm.team_id == ProjectMember.team_id, tm.user_id == user_id))
        .where(
            ProjectMember.project_id == Project.id,
            or_(ProjectMember.user_id == user_id, tm.user_id.isnot(None)),
        )
        .correlate(Project)
        .scalar_subquery()
    )


def project_level_expression(user_id: uuid.UUID, org_role: str):
    """Rule 2 as a SQL expression: `GREATEST` over every route in.

    The mirror of `effective_level` above. Returns a rank, not a name — the
    router maps it back with `level_name`, because doing that translation in
    SQL would mean a CASE that has to be kept in step with the Python one.
    """
    routes = [
        case((Project.owner_user_id == user_id, LEVEL_RANK[LEVEL_OWNER]), else_=NO_ACCESS),
        func.coalesce(_grant_rank_subquery(user_id), NO_ACCESS),
    ]
    if administers_organisation(org_role):
        # A literal rather than a branch that builds a different query: one
        # statement, one code path, and the planner folds the constant.
        routes.append(literal(LEVEL_RANK[LEVEL_OWNER]))
    return func.greatest(*routes)


def visible_projects_stmt(
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    org_role: str,
    include_archived: bool = False,
) -> Select:
    """Every project in this organisation the user can see, with their level.

    Rule 4. Yields `(Project, rank)` rows — pass the rank through `level_name`.
    """
    level = project_level_expression(user_id, org_role)
    stmt = (
        select(Project, level.label("level_rank"))
        .where(Project.organisation_id == org_id, level > NO_ACCESS)
        .order_by(Project.name)
    )
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    return stmt


def visible_project_stmt(
    *, user_id: uuid.UUID, org_id: uuid.UUID, org_role: str, project_id: uuid.UUID
) -> Select:
    """One project, if the user can see it at all.

    Archived projects are included: you reached this by following a link to a
    specific thing, and hiding it would look like deletion. Only the *list*
    hides them.
    """
    level = project_level_expression(user_id, org_role)
    return select(Project, level.label("level_rank")).where(
        Project.id == project_id,
        Project.organisation_id == org_id,
        level > NO_ACCESS,
    )


def project_task_stats_stmt(*, user_id: uuid.UUID, org_id: uuid.UUID, org_role: str) -> Select:
    """Open task count, and open-and-important count, per project — one
    `GROUP BY`, not one query per card in the Projects grid.

    Grouped over **task** visibility (`task_level_expression`), not project
    visibility: a project you can see is not the same set as the tasks on it
    you can see (a project grant doesn't override a hidden task, and a task
    grant can reach further than the project's own). Counting tasks the
    caller has no route to would make a stat that leaks what's on a project
    beyond what the rest of the product already shows them.

    "Important" is critical, urgent or high combined into one number rather
    than three — the card this feeds is already dense, and the three-way
    split belongs to the dashboard's own Critical/Urgent/High cards, not a
    repeat of it here.
    """
    level = task_level_expression(user_id, org_role)
    important = Task.priority.in_(("critical", "urgent", "high"))
    return (
        select(
            Task.project_id,
            func.count().filter(Task.closed_at.is_(None)).label("open_count"),
            func.count().filter(Task.closed_at.is_(None), important).label("important_count"),
        )
        .where(Task.organisation_id == org_id, Task.project_id.isnot(None), level > NO_ACCESS)
        .group_by(Task.project_id)
    )


# --- tasks ---------------------------------------------------------------------


def _task_grant_rank_subquery(user_id: uuid.UUID):
    """The best level this user has on a task through a stored grant.

    Same shape as the project one, including the LEFT JOIN that lets a single
    OR cover both a direct grant and a grant to a team they're in.
    """
    tm = aliased(TeamMember)
    return (
        select(
            func.max(
                case(
                    (TaskGrant.level == LEVEL_WRITE, LEVEL_RANK[LEVEL_WRITE]),
                    else_=LEVEL_RANK[LEVEL_READ],
                )
            )
        )
        .select_from(TaskGrant)
        .outerjoin(tm, and_(tm.team_id == TaskGrant.team_id, tm.user_id == user_id))
        .where(
            TaskGrant.task_id == Task.id,
            or_(TaskGrant.user_id == user_id, tm.user_id.isnot(None)),
        )
        .correlate(Task)
        .scalar_subquery()
    )


def _inherited_project_rank(user_id: uuid.UUID, org_role: str):
    """Rule 1 flowing down: whatever you hold on the project, you hold on its
    tasks.

    A correlated subquery rather than a join, so a **loose task** — where
    `project_id` is NULL and this matches nothing — yields NULL and coalesces
    to "no route", instead of the join dropping the task from the result
    entirely. That distinction is the entire loose-task feature.

    Note it deliberately does *not* re-apply the org-admin literal: the outer
    expression already adds it, and doing it twice would be two constants to
    keep in step.
    """
    owner_or_grant = func.greatest(
        case((Project.owner_user_id == user_id, LEVEL_RANK[LEVEL_OWNER]), else_=NO_ACCESS),
        func.coalesce(_grant_rank_subquery(user_id), NO_ACCESS),
    )
    return (
        select(owner_or_grant)
        .select_from(Project)
        .where(Project.id == Task.project_id)
        .correlate(Task)
        .scalar_subquery()
    )


def task_level_expression(user_id: uuid.UUID, org_role: str):
    """`effective_task_level` as SQL. The two are tested against each other.

    The hidden short-circuit is the **outer** CASE, wrapping the `GREATEST`
    rather than joining it. A hidden task you don't own resolves to `NO_ACCESS`
    however many grants point at it, and the org-admin literal below never gets
    a chance to win. Everything that composes this expression — the board,
    search, the time rollups — inherits that for free, which is the whole
    reason there is one expression rather than a check per screen.
    """
    routes = [
        case((Task.owner_user_id == user_id, LEVEL_RANK[LEVEL_OWNER]), else_=NO_ACCESS),
        case(
            (Task.action_required_user_id == user_id, LEVEL_RANK[LEVEL_WRITE]),
            else_=NO_ACCESS,
        ),
        case((Task.created_by_user_id == user_id, LEVEL_RANK[LEVEL_READ]), else_=NO_ACCESS),
        func.coalesce(_inherited_project_rank(user_id, org_role), NO_ACCESS),
        func.coalesce(_task_grant_rank_subquery(user_id), NO_ACCESS),
    ]
    if administers_organisation(org_role):
        routes.append(literal(LEVEL_RANK[LEVEL_OWNER]))
    return case(
        (
            and_(Task.hidden_at.isnot(None), Task.owner_user_id != user_id),
            literal(NO_ACCESS),
        ),
        else_=func.greatest(*routes),
    )


def _priority_rank():
    """`critical` → 6 … `very_low` → 1, for ORDER BY."""
    return case(PRIORITY_RANK, value=Task.priority, else_=0)


# What the list view may be sorted by. A closed set, because the value lands
# in an ORDER BY: anything else is a 500 at best.
SORTS = (
    "title",
    "project",
    "created_at",
    "updated_at",
    "status",
    "priority",
    "owner",
    "action_required",
    "due_on",
)


def _sort_expression(sort: str):
    """One column's ORDER BY term.

    People and projects sort by **name**, not by id — an id ordering is
    stable, meaningless, and looks broken. Correlated scalar subqueries rather
    than joins, so the statement's shape doesn't change and the board can keep
    sharing this builder.

    Status and priority sort by **rank, not alphabetically**: "blocker,
    in_progress, on_hold, review, todo" orders the spellings, not the work.
    """
    if sort == "project":
        return (
            select(Project.name)
            .where(Project.id == Task.project_id)
            .correlate(Task)
            .scalar_subquery()
        )
    if sort in ("owner", "action_required"):
        column = Task.owner_user_id if sort == "owner" else Task.action_required_user_id
        return (
            select(func.coalesce(User.display_name, User.email))
            .where(User.id == column)
            .correlate(Task)
            .scalar_subquery()
        )
    if sort == "priority":
        return _priority_rank()
    if sort == "status":
        return case(STATUS_RANK, value=Task.status, else_=0)
    return getattr(Task, sort)


def visible_tasks_stmt(
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    org_role: str,
    project_id: uuid.UUID | None = None,
    loose_only: bool = False,
    include_closed: bool = False,
    tag_id: uuid.UUID | None = None,
    include_off_board: bool = False,
    status: str | None = None,
    priority: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    action_required_user_id: uuid.UUID | None = None,
    mine_user_id: uuid.UUID | None = None,
    due_after: date | None = None,
    due_before: date | None = None,
    sort: str | None = None,
    descending: bool = False,
) -> Select:
    """Every task the user can see, with their level. Rule 4: one statement.

    `project_id` narrows to one project; `loose_only` narrows to tasks with no
    project at all. Neither widens access — the level expression is the same
    either way, and so are the two tag filters. `due_after`/`due_before` are
    both inclusive, for the calendar — a task due on the last visible day of
    a month must still appear in that month.

    **`include_off_board` is a display rule, not an access rule.** A task
    tagged "Knowledge base" is perfectly visible; it is just not queueing for
    attention, so it stays off the board unless you asked for that tag by
    name. Filtering by a tag implies you did, so it overrides.

    **`mine_user_id` is the odd one of the three person filters: it ORs.**
    `owner_user_id` and `action_required_user_id` each narrow to one route
    and AND together, which is what the task list's two separate Owner and
    Action-required filters want. `mine_user_id` asks the different question
    the dashboard's escalation cards ask — "work that's mine, either way" —
    and is the same OR `my_priority_tasks_stmt` writes out for itself. It
    lives here rather than being a second builder because every other filter
    a caller might want to combine it with is already here; passing all three
    at once is legal and means what it says (mine, AND owned by X, AND...),
    though nothing does that today.
    """
    level = task_level_expression(user_id, org_role)
    stmt = (
        select(Task, level.label("level_rank"))
        .where(Task.organisation_id == org_id, level > NO_ACCESS)
        # Board order: most urgent first, then manual position, then creation
        # order (UUIDv7 sorts by time). Priority is stored as a name, so the
        # rank is a CASE rather than a column — the name stays authoritative
        # and there is no second field to keep in step.
        .order_by(_priority_rank().desc(), Task.position, Task.id)
    )
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if loose_only:
        stmt = stmt.where(Task.project_id.is_(None))
    if not include_closed:
        stmt = stmt.where(Task.closed_at.is_(None))
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)
    if owner_user_id is not None:
        stmt = stmt.where(Task.owner_user_id == owner_user_id)
    if action_required_user_id is not None:
        stmt = stmt.where(Task.action_required_user_id == action_required_user_id)
    if mine_user_id is not None:
        stmt = stmt.where(
            or_(
                Task.owner_user_id == mine_user_id,
                Task.action_required_user_id == mine_user_id,
            )
        )
    if due_after is not None:
        stmt = stmt.where(Task.due_on >= due_after)
    if due_before is not None:
        stmt = stmt.where(Task.due_on <= due_before)
    if tag_id is not None:
        # Imported here, not at module scope: `services/tags.py` imports this
        # module for `administers_organisation`, and at the top that is a
        # cycle. The alternative is a third module holding two EXISTS clauses.
        from app.services import tags as tags_service

        stmt = stmt.where(tags_service.tagged_with(tag_id))
    elif not include_off_board:
        from app.services import tags as tags_service

        stmt = stmt.where(~tags_service.off_board_exists())
    if sort in SORTS:
        term = _sort_expression(sort)
        # NULLs last either way: an unassigned task belongs at the bottom of a
        # sort by owner, not at the top of it.
        term = term.desc().nullslast() if descending else term.asc().nullslast()
        # `Task.id` breaks ties — UUIDv7, so equal rows keep creation order
        # rather than shuffling between pages of the same list.
        stmt = stmt.order_by(None).order_by(term, Task.id)
    return stmt


def my_priority_tasks_stmt(
    *, user_id: uuid.UUID, org_id: uuid.UUID, org_role: str, priority: str
) -> Select:
    """Open, at the given priority, and yours — either you own it or you're
    asked to act.

    The dashboard's escalation lists — one call per priority shown (Critical,
    Urgent), because they're separate cards, not one list split client-side.
    Deliberately narrower than `visible_tasks_stmt`'s
    `owner_user_id=`/`action_required_user_id=` filters, which AND against a
    single route: this ORs the two, because "work at this priority that's
    mine, either way" is one question. `level > NO_ACCESS` is still here for
    the same reason it's in every builder in this module — ownership and
    action-required both already resolve to a real level, so the OR below is
    a display filter layered on access already proven, not a second access
    decision.
    """
    level = task_level_expression(user_id, org_role)
    return (
        select(Task, level.label("level_rank"))
        .where(
            Task.organisation_id == org_id,
            level > NO_ACCESS,
            Task.priority == priority,
            Task.closed_at.is_(None),
            or_(Task.owner_user_id == user_id, Task.action_required_user_id == user_id),
        )
        # Yours to act on, first — that's the one with a clock on it.
        .order_by(
            case((Task.action_required_user_id == user_id, 0), else_=1),
            Task.position,
            Task.id,
        )
    )


def my_due_soon_tasks_stmt(
    *, user_id: uuid.UUID, org_id: uuid.UUID, org_role: str, today: date, horizon_days: int = 2
) -> Select:
    """Open, due within `horizon_days` (overdue included), and yours — the
    same OR as `my_priority_tasks_stmt`, filtered on the due date instead of
    priority.

    `today` is passed in rather than computed here because "today" is
    per-person timezone, resolved once by the caller the same way the
    dashboard already resolves it for out-of-office — computing it twice
    risks the two disagreeing about whether something is overdue.
    """
    level = task_level_expression(user_id, org_role)
    horizon = today + timedelta(days=horizon_days)
    return (
        select(Task, level.label("level_rank"))
        .where(
            Task.organisation_id == org_id,
            level > NO_ACCESS,
            Task.due_on.isnot(None),
            Task.due_on <= horizon,
            Task.closed_at.is_(None),
            or_(Task.owner_user_id == user_id, Task.action_required_user_id == user_id),
        )
        # Most overdue first — that is the one that has waited longest.
        .order_by(Task.due_on, Task.id)
    )


def paged_tasks_stmt(*, limit: int, offset: int, **kwargs) -> Select:
    """One page of the list, **and the size of the whole thing**, in one query.

    `COUNT(*) OVER ()` rather than a second `SELECT count(*)`: the access
    expression is the expensive part and running it twice to learn a number is
    the sort of thing that only shows up once there is data. The window is
    computed over the full result set before `LIMIT` applies, which is exactly
    the total a pager needs.
    """
    inner = visible_tasks_stmt(**kwargs)
    sub = inner.add_columns(func.count().over().label("total")).subquery()
    task = aliased(Task, sub)
    return select(task, sub.c.level_rank, sub.c.total).limit(limit).offset(offset)


def board_stmt(
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    org_role: str,
    group_by: str,
    per_group: int,
    project_id: uuid.UUID | None = None,
    loose_only: bool = False,
    include_closed: bool = False,
    tag_id: uuid.UUID | None = None,
    include_off_board: bool = False,
) -> Select:
    """The board: the top `per_group` tasks in each column, **and each
    column's real total**, in one statement.

    A board can't use a plain `LIMIT`. Its rows are ordered by priority, so
    the first 200 of 7,300 are all the criticals and four of the five columns
    come back empty — the page would be bounded and also wrong. `ROW_NUMBER()`
    partitioned by the grouping column bounds each column independently, and
    `COUNT()` over the same partition is what lets a column say "50 of 812"
    instead of quietly lying about how much work there is.

    Both windows ride the same scan as the access expression, so this stays
    one query however many columns there are.

    `group_by="action_required"` partitions on `Task.action_required_user_id`
    directly — a nullable column, unlike status and priority. Postgres treats
    NULL as one ordinary partition value for a window function (every row
    with nobody action-required lands in the same group), so no special
    casing is needed here; the caller turns that partition's key into the
    string `"none"` for a JSON-safe response.
    """
    inner = visible_tasks_stmt(
        user_id=user_id,
        org_id=org_id,
        org_role=org_role,
        project_id=project_id,
        loose_only=loose_only,
        include_closed=include_closed,
        tag_id=tag_id,
        include_off_board=include_off_board,
    )
    if group_by == "priority":
        group_col = Task.priority
    elif group_by == "action_required":
        group_col = Task.action_required_user_id
    else:
        group_col = Task.status
    within = [_priority_rank().desc(), Task.position, Task.id]
    sub = inner.add_columns(
        func.row_number().over(partition_by=group_col, order_by=within).label("rn"),
        func.count().over(partition_by=group_col).label("group_total"),
    ).subquery()

    task = aliased(Task, sub)
    return (
        select(task, sub.c.level_rank, sub.c.group_total)
        .where(sub.c.rn <= per_group)
        .order_by(sub.c.rn)
    )


def visible_task_ids_stmt(*, user_id: uuid.UUID, org_id: uuid.UUID, org_role: str) -> Select:
    """Just the ids, for composing into other queries.

    Time rollups aggregate over "every task you can see", and they must do it
    inside one statement — a Python list of ids would cap out and would go
    stale between the two round trips. This is the same expression
    `visible_tasks_stmt` uses, without the ordering and the row payload.
    """
    level = task_level_expression(user_id, org_role)
    return select(Task.id).where(Task.organisation_id == org_id, level > NO_ACCESS)


def visible_task_stmt(
    *, user_id: uuid.UUID, org_id: uuid.UUID, org_role: str, task_id: uuid.UUID
) -> Select:
    """One task, or nothing. Closed tasks included — you followed a link to a
    specific thing, and hiding it would look like deletion."""
    level = task_level_expression(user_id, org_role)
    return select(Task, level.label("level_rank")).where(
        Task.id == task_id,
        Task.organisation_id == org_id,
        level > NO_ACCESS,
    )


# --- knowledge base -----------------------------------------------------------


def _book_grant_rank_subquery(user_id: uuid.UUID):
    """The best level this user has on a book through a stored grant — a
    byte-for-byte copy of `_grant_rank_subquery`'s own reasoning, including
    the LEFT JOIN: an inner join would drop every direct grant, because a
    direct grant has a NULL `team_id` and matches no team-member row."""
    tm = aliased(TeamMember)
    return (
        select(
            func.max(
                case(
                    (BookMember.level == LEVEL_WRITE, LEVEL_RANK[LEVEL_WRITE]),
                    else_=LEVEL_RANK[LEVEL_READ],
                )
            )
        )
        .select_from(BookMember)
        .outerjoin(tm, and_(tm.team_id == BookMember.team_id, tm.user_id == user_id))
        .where(
            BookMember.book_id == Book.id,
            or_(BookMember.user_id == user_id, tm.user_id.isnot(None)),
        )
        .correlate(Book)
    )


def book_level_expression(user_id: uuid.UUID, org_role: str):
    """Rule 2 for a book, as SQL — the mirror of `project_level_expression`,
    reading `Book`/`BookMember` instead of `Project`/`ProjectMember`."""
    routes = [
        case((Book.owner_user_id == user_id, LEVEL_RANK[LEVEL_OWNER]), else_=NO_ACCESS),
        func.coalesce(_book_grant_rank_subquery(user_id), NO_ACCESS),
    ]
    if administers_organisation(org_role):
        routes.append(literal(LEVEL_RANK[LEVEL_OWNER]))
    return func.greatest(*routes)


def visible_books_stmt(
    *, user_id: uuid.UUID, org_id: uuid.UUID, org_role: str, include_archived: bool = False
) -> Select:
    """Every book in this organisation the user can see, with their level."""
    level = book_level_expression(user_id, org_role)
    stmt = (
        select(Book, level.label("level_rank"))
        .where(Book.organisation_id == org_id, level > NO_ACCESS)
        .order_by(Book.name)
    )
    if not include_archived:
        stmt = stmt.where(Book.archived_at.is_(None))
    return stmt


def visible_book_stmt(
    *, user_id: uuid.UUID, org_id: uuid.UUID, org_role: str, book_id: uuid.UUID
) -> Select:
    """One book, if the user can see it at all. Archived included — a link to
    a specific thing shouldn't look like deletion."""
    level = book_level_expression(user_id, org_role)
    return select(Book, level.label("level_rank")).where(
        Book.id == book_id,
        Book.organisation_id == org_id,
        level > NO_ACCESS,
    )


def article_level_expression(user_id: uuid.UUID, org_role: str):
    """`effective_article_level` as SQL — the same rule stated twice, the
    identical reasoning `task_level_expression` documents for tasks: one
    version pure Python and exhaustively tested with no database, one
    version the planner can actually run.

    `Article.is_private` short-circuits the whole expression: the outer
    `CASE` puts it ahead of everything else, and when it's true only
    ownership survives — an organisation admin does not see a private
    article, the same deliberate hole a hidden task has. When it's false,
    `book_level_expression` already folds the organisation-admin override
    into its own routes, so seeing the book is enough to see any article in
    it that isn't private; the owner route is still ORed in on top for the
    case where ownership outranks whatever the book itself grants.
    """
    owner_route = case(
        (Article.owner_user_id == user_id, LEVEL_RANK[LEVEL_OWNER]), else_=NO_ACCESS
    )
    return case(
        (Article.is_private, owner_route),
        else_=func.greatest(book_level_expression(user_id, org_role), owner_route),
    )


def visible_articles_stmt(
    *, user_id: uuid.UUID, org_id: uuid.UUID, org_role: str, book_id: uuid.UUID | None = None
) -> Select:
    """Every article the user can see — across the organisation, or scoped to
    one book for the table of contents. One statement; a private article
    that isn't theirs simply never matches, which is the vanish-from-
    contents behaviour, not a second filter."""
    level = article_level_expression(user_id, org_role)
    stmt = (
        select(Article, level.label("level_rank"))
        .select_from(Article)
        .join(Book, Book.id == Article.book_id)
        .where(Book.organisation_id == org_id, level > NO_ACCESS)
    )
    if book_id is not None:
        stmt = stmt.where(Article.book_id == book_id)
    return stmt


def visible_article_stmt(
    *, user_id: uuid.UUID, org_id: uuid.UUID, org_role: str, article_id: uuid.UUID
) -> Select:
    """One article, if the user can see it at all."""
    level = article_level_expression(user_id, org_role)
    return (
        select(Article, level.label("level_rank"))
        .select_from(Article)
        .join(Book, Book.id == Article.book_id)
        .where(Article.id == article_id, Book.organisation_id == org_id, level > NO_ACCESS)
    )
