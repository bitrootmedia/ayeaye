"""@-mentions in a comment.

Two halves, and the first is what makes the second safe.

**Who can be mentioned is exactly who can see the task.** Not the
organisation's roster: mentioning somebody who can't open the thing would
either notify them about a task they can't read — a title outside the access
model, the thing `services/notifications.py` exists to avoid — or silently
notify nobody, which is worse than no feature at all.

That set is computed by applying `access.effective_task_level` — the **Python**
statement of rule 2, the one `tests/test_access_matrix.py` proves over the
whole grid — to each active member, with every input fetched once up front.
Deliberately not a third derivation of the rule: the reverse question ("who
can see this one task") cannot reuse `task_level_expression`, because that
builder takes a `user_id` literal and an `org_role` known at build time, and
inverting it would mean writing the six routes out in SQL a second time. Four
queries for one task and a pure-Python fold over the roster is the cheaper
honesty. This is a *single* task, not a list — the "one statement per list"
rule is about list endpoints resolving access per row, and there is no list
here.

**The comment body is the only record of a mention.** There is no
`message_mentions` table and no marker syntax: the server resolves `@Name`
against the candidate set at post time and again on an edit. That's one source
of truth rather than a body and an id list that can disagree — the same
reasoning `notifications.organisation_id` gives for being a real column rather
than a value parsed back out of `link_path`, pointed the other way: here the
prose *is* the value, and a separate list of ids would be the copy that goes
stale the moment somebody edits the text.

Three consequences worth knowing:

* **Every writer gets mentions, not just the composer.** A comment posted over
  MCP or curl with somebody's name in it notifies them, because nothing about
  the resolution depends on the client having a picker.
* **An edit that adds a name notifies it**, and one that doesn't, doesn't —
  `find_mentions` is run against the old body as well and only the difference
  is told. Without that, "I forgot to @ them" would be a silent no-op, and
  re-notifying on every edit would make a typo fix a second nudge.
* **A rename doesn't rewrite history.** The stored text keeps the name that
  was typed, so an old comment stops resolving to that person. A mention is a
  notification, not a link that has to survive forever, and the alternative is
  markers in the prose that render as noise wherever they aren't parsed.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    OrganisationMember,
    Project,
    ProjectMember,
    Task,
    TaskGrant,
    TeamMember,
    User,
)
from app.models.organisation import STATUS_ACTIVE
from app.services import access

# The most people one comment can name. Not an error when exceeded — the
# extras are simply not notified, in body order, because refusing to post a
# comment over a notification detail would lose somebody's words.
MAX_MENTIONS = 20


@dataclass(frozen=True)
class Mentionable:
    """Somebody who can see the task, and therefore can be named in its
    thread. `level` is theirs, not the caller's — the composer only needs the
    names, but the notify path uses the same rows and the level is free."""

    user: User
    level: str


def needles(display_name: str | None, email: str | None) -> tuple[str, ...]:
    """What text counts as naming this person.

    Their display name, their email, and the email's local part — the last one
    because `@bob` is what somebody types when a colleague has never set a
    display name. Lowercased, because matching is case-insensitive: nobody
    types `@Kuba Nowak` with the capitals right every time.
    """
    out: list[str] = []
    for candidate in (display_name, email, (email or "").split("@")[0]):
        value = (candidate or "").strip().lower()
        if value and value not in out:
            out.append(value)
    return tuple(out)


def find_mentions[T](body: str, candidates: list[tuple[str, T]]) -> list[T]:
    """Whoever this text names, in the order they appear.

    Pure, and tested as such (`tests/test_mention_parsing.py`) — the fiddly
    half of this feature is entirely here, and it needs no database to prove.

    `candidates` is `(needle, key)` pairs; the **longest needle wins** at each
    `@`, so an organisation containing both "Acme" and "Acme Corp" resolves
    `@Acme Corp` to the second rather than the first plus stray text — the
    identical longest-match-first reasoning `telegram_commands.match_
    organisation` already applies to picking an organisation by name.

    Two guards do most of the work:

    * **The `@` must not follow a word character**, so `bob@example.com` in
      the middle of a sentence is an email address, not a mention of Bob.
    * **The match must end on a word boundary**, so `@Sam` does not match
      inside `@Samantha` when both exist.
    """
    ordered = sorted(candidates, key=lambda pair: len(pair[0]), reverse=True)
    found: list[T] = []
    lowered = body.lower()
    index = 0
    while True:
        at = lowered.find("@", index)
        if at == -1:
            break
        index = at + 1
        if at > 0 and (lowered[at - 1].isalnum() or lowered[at - 1] in "._-+"):
            continue
        for needle, key in ordered:
            end = at + 1 + len(needle)
            if lowered[at + 1 : end] != needle:
                continue
            if end < len(lowered) and (lowered[end].isalnum() or lowered[end] == "_"):
                continue
            if key not in found:
                found.append(key)
            # Resume after the name, not after the "@": a display name can
            # itself contain an "@" (an email used as one), and rescanning
            # inside a name already matched would find it a second time.
            index = end
            break
    return found[:MAX_MENTIONS]


async def for_task(db: AsyncSession, org_id: uuid.UUID, task: Task) -> list[Mentionable]:
    """Everyone who can see this task, resolved through rule 2.

    Sorted by the name a person is displayed under — the same convention
    people and projects sort by everywhere else in this product.
    """
    roster = (
        await db.execute(
            select(User, OrganisationMember.role)
            .join(OrganisationMember, OrganisationMember.user_id == User.id)
            .where(
                OrganisationMember.organisation_id == org_id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).all()

    task_grants = (
        (await db.execute(select(TaskGrant).where(TaskGrant.task_id == task.id))).scalars().all()
    )

    project_owner_id: uuid.UUID | None = None
    project_grants: list[ProjectMember] = []
    if task.project_id is not None:
        project_owner_id = (
            await db.execute(select(Project.owner_user_id).where(Project.id == task.project_id))
        ).scalar_one_or_none()
        project_grants = list(
            (
                await db.execute(
                    select(ProjectMember).where(ProjectMember.project_id == task.project_id)
                )
            )
            .scalars()
            .all()
        )

    # One lookup for every team named by either kind of grant, rather than one
    # per grant — the same batching every list endpoint here already does.
    team_ids = {g.team_id for g in (*task_grants, *project_grants) if g.team_id is not None}
    teams: dict[uuid.UUID, set[uuid.UUID]] = {tid: set() for tid in team_ids}
    if team_ids:
        for team_id, user_id in (
            await db.execute(
                select(TeamMember.team_id, TeamMember.user_id).where(
                    TeamMember.team_id.in_(team_ids)
                )
            )
        ).all():
            teams[team_id].add(user_id)

    is_hidden = task.hidden_at is not None
    out: list[Mentionable] = []
    for user, role in roster:
        task_direct = next((g.level for g in task_grants if g.user_id == user.id), None)
        task_teams = tuple(
            g.level for g in task_grants if g.team_id is not None and user.id in teams[g.team_id]
        )
        project_direct = next((g.level for g in project_grants if g.user_id == user.id), None)
        project_teams = tuple(
            g.level for g in project_grants if g.team_id is not None and user.id in teams[g.team_id]
        )
        # `org_role="member"` deliberately: the organisation-admin route is
        # applied once, by `effective_task_level` below. Applying it here too
        # would be the same constant in two places — the identical note
        # `access._inherited_project_rank` carries for its SQL twin.
        project_level = (
            access.effective_level(
                is_owner=project_owner_id == user.id,
                org_role="member",
                direct=project_direct,
                via_teams=project_teams,
            )
            if task.project_id is not None
            else None
        )
        level = access.effective_task_level(
            org_role=role,
            is_owner=task.owner_user_id == user.id,
            is_action_required=task.action_required_user_id == user.id,
            is_creator=task.created_by_user_id == user.id,
            is_hidden=is_hidden,
            project_level=project_level,
            direct=task_direct,
            via_teams=task_teams,
        )
        if level is not None:
            out.append(Mentionable(user=user, level=level))

    out.sort(key=lambda m: (m.user.display_name or m.user.email or "").lower())
    return out


def resolve(body: str, candidates: list[Mentionable], *, exclude: uuid.UUID) -> list[uuid.UUID]:
    """The people this comment names, minus its author.

    Naming yourself notifies nobody — the same "never about yourself" rule
    every notification in `services/tasks.py` already follows.
    """
    pairs: list[tuple[str, uuid.UUID]] = [
        (needle, candidate.user.id)
        for candidate in candidates
        for needle in needles(candidate.user.display_name, candidate.user.email)
    ]
    return [uid for uid in find_mentions(body, pairs) if uid != exclude]


__all__ = ["MAX_MENTIONS", "Mentionable", "find_mentions", "for_task", "needles", "resolve"]
