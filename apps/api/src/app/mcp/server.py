"""The MCP server: an assistant acting as a person.

## The one rule

**Every tool resolves through `services/access.py`, as the token's owner.**
Not "as an integration", not with a service account, not with a wider query
written for convenience. A token is a person; whatever they can see, it can
see, and nothing else.

That is why this module is thin. It parses arguments, calls the same services
the REST API calls, and formats the answer — and there is deliberately not a
single `select()` in it. A query written here would be a second access path,
and the moment there are two, one of them is wrong and nobody knows which.

## Authentication

Two credential shapes, both bearer tokens, both resolved before a tool ever
runs: a personal access token from the account screen
(`Authorization: Bearer ayc_…`, see `services/tokens.py` — shown once,
hashed at rest, scoped, revocable from the screen that made it), or an
OAuth access token from the flow at `/oauth/authorize` (see
`services/oauth.py`), which is what lets Claude.ai and ChatGPT's own
"connect an MCP server" features add this server with no manual token
pasting. Not the session cookie either way: an MCP client is not a browser.

**Verification happens at the transport layer, not in `_caller()`.**
`OAuthTokenVerifier` (`services/oauth.py`) is wired into `main.py`'s ASGI
middleware around this module's `/mcp` mount — a missing or bad token gets a
real `401` with `WWW-Authenticate` before any tool code runs, which is the
signal an OAuth-aware client needs to go start the flow at all. `_caller()`
below just resolves the already-verified principal to a `User` row.

## Shape of the answers

Tools return **text, not JSON blobs**. The consumer is a language model
choosing what to say next, and a compact readable line per task costs a
fraction of the tokens of the same data as JSON — with the id kept on every
row so a follow-up call can address it.
"""

import base64
import binascii
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import HTTPException
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

# **`mcp.server.mcpserver.context`, not `mcp.server.context`.** There are two
# classes called Context in this SDK, and the tool decorator only recognises
# this one — the other is accepted by the type checker and then fails at
# registration with a Pydantic schema error about IsInstanceSchema, which says
# nothing at all about the actual mistake.
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import AnyHttpUrl, Field

from app.core.config import settings
from app.db import SessionLocal
from app.models import Book, User
from app.models.changelog import MAX_DESCRIPTION_LENGTH as MAX_CHANGELOG_DESCRIPTION
from app.models.organisation import STATUS_ACTIVE as MEMBER_STATUS_ACTIVE
from app.models.planner import BUCKETS as PLANNER_BUCKETS
from app.models.task import PRIORITIES, STATUSES
from app.models.token import SCOPE_READ, SCOPE_WRITE
from app.services import articles as articles_service
from app.services import attachments as attachments_service
from app.services import books as books_service
from app.services import changelog as changelog_service
from app.services import checklists as checklists_service
from app.services import conversations as conversations_service
from app.services import dependencies as dependencies_service
from app.services import idempotency as idempotency_service
from app.services import notifications as notifications_service
from app.services import organisations as organisations_service
from app.services import planner as planner_service
from app.services import projects as projects_service
from app.services import reminders as reminders_service
from app.services import richtext, time_tracking
from app.services import search as search_service
from app.services import sparks as sparks_service
from app.services import tags as tags_service
from app.services import tasks as tasks_service
from app.services.oauth import OAuthTokenVerifier
from app.storage import s3

# Verifies both credential shapes (a personal access token, or an OAuth
# access token — see services/oauth.py) at the transport layer. `main.py`
# imports this same instance to wire it into the ASGI middleware stack
# around this module's `/mcp` mount, which is what turns a missing/bad
# token into a real 401 before any tool call runs.
token_verifier = OAuthTokenVerifier()

mcp = MCPServer(
    name="ayeayecaptain",
    instructions=(
        "Project and task management, plus a per-organisation knowledge base "
        "of books and articles. Every call acts as the person whose access "
        "token is in use and can only reach what they can reach.\n\n"
        "Start with `organisations` — almost everything else needs an "
        "organisation id. Task ids are UUIDs and are stable; quote them back "
        "when the person refers to 'that task'.\n\n"
        "Statuses are todo, in_progress, review, on_hold and blocker. "
        "Open/closed is a separate field: a task can be closed at any status, "
        "and there is no 'done' status. Priorities run critical, urgent, "
        "high, normal, low, very_low.\n\n"
        "A knowledge-base article is born a private draft that only its "
        "owner can see — `publish_article` is what makes it visible to "
        "anyone the book is shared with."
    ),
    token_verifier=token_verifier,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(settings.site_url),
        resource_server_url=AnyHttpUrl(f"{settings.site_url}/mcp"),
        # Read-vs-write is _require_write's job, per tool — not a blanket
        # scope requirement to reach the server at all.
        required_scopes=[],
    ),
)


class Denied(ToolError):
    """A refusal the caller should read: "no such organisation", "not a member",
    "this credential is read-only".

    **`ToolError`, not `Exception`.** The SDK draws exactly this line: a
    `ToolError` is a failure the tool saw coming, and its message reaches the
    client in the `is_error` result; anything else is a crash, and the model
    gets the bare string `Error executing tool <name>` with the real text kept
    on the server — deliberately, so an unhandled exception cannot leak
    internals. Every refusal here is the former, and while `Denied` was a
    plain `Exception` every one of them arrived as that bare string: a person
    told only that something failed, with the one sentence saying what to do
    about it discarded on the way out. It read like an SDK fault and was
    written up as one in the menu bar client, which substituted a guess
    ("your token may be read-only") because it had nothing else to show.
    """


class _Principal:
    """What the verified credential is, regardless of which shape it was.

    `.scope` is the shim that lets `_require_write` stay the same whether a
    personal access token or an OAuth access token got us here — see
    `models/token.py`'s `SCOPE_READ`/`SCOPE_WRITE`.

    `.via` is its display name: what somebody called the token on the account
    screen, or the client name an OAuth app registered with. It is what a
    write records as having acted on the person's behalf, so a comment posted
    by an assistant says so instead of reading as though its owner typed it.
    None if the credential somehow carries no name — attribution is a nicety
    on top of a write, never a reason to refuse one.
    """

    def __init__(self, scope: str, via: str | None = None) -> None:
        self.scope = scope
        self.via = via


async def _caller(ctx: Context) -> tuple[User, _Principal]:
    """Who is asking. Both credential shapes are already verified at the
    transport layer (`token_verifier`, wired into `main.py`'s auth
    middleware) — a missing or bad token never reaches here, it was already
    refused with a 401 before this tool call started. This just resolves
    the already-verified principal to a `User` row.
    """
    access_token = get_access_token()
    if access_token is None or access_token.subject is None:
        # Defensive: the transport layer should have refused this already.
        raise Denied(
            "No valid access token. Create one under Account → Access tokens "
            "and send it as `Authorization: Bearer ayc_…`, or connect via OAuth."
        )
    async with SessionLocal() as db:
        user = await db.get(User, uuid.UUID(access_token.subject))
    if user is None:
        raise Denied("No valid access token.")
    scope = SCOPE_WRITE if SCOPE_WRITE in access_token.scopes else SCOPE_READ
    # RFC 8693's `act` — the party acting on behalf of the subject — put
    # there by `OAuthTokenVerifier` for both credential shapes. Read
    # defensively: `claims` is an SDK field any future verifier could leave
    # empty, and a missing name must cost a write nothing.
    actor = (access_token.claims or {}).get("act") or {}
    via = actor.get("name") if isinstance(actor, dict) else None
    return user, _Principal(scope, via=via if isinstance(via, str) else None)


async def _org(db, user: User, organisation_id: str):
    """An organisation context, or a refusal that doesn't confirm it exists."""
    try:
        oid = uuid.UUID(organisation_id)
    except ValueError as exc:
        raise Denied("That is not an organisation id.") from exc
    try:
        return await organisations_service.context_for(db, oid, user)
    except Exception as exc:
        # 404-not-403 all the way out here too: a refusal must not confirm
        # that an organisation exists.
        raise Denied("No such organisation, or you are not a member of it.") from exc


async def _project_names(db, org, user: User) -> dict:
    """Names for the project column. Only the ones the caller can see, which
    is the point of going through the service rather than reading the table."""
    rows = await projects_service.list_visible(db, org, user.id, include_archived=True)
    return {project.id: project.name for project, _ in rows}


def _one_line(task, project_names: dict) -> str:
    """One task, one line. Dense on purpose — a hundred of these go into a
    context window, and JSON would spend most of it on punctuation."""
    bits = [
        f"[{task.id}]",
        task.title,
        f"status={task.status}",
        f"priority={task.priority}",
    ]
    if task.project_id:
        bits.append(f"project={project_names.get(task.project_id, '?')}")
    if task.due_on:
        bits.append(f"due={task.due_on}")
    if task.closed_at:
        bits.append("closed")
    return " | ".join(bits)


MAX_THREAD = 40
"""How many comments `task` reads back, newest kept.

A cap rather than the whole thread, because a long-running task's discussion
would otherwise crowd out everything else in the answer — and the recent end
is the end that says where the work got to. `task` states the real total
whenever it truncates: a caller that believes it has everything and doesn't
is the failure this cap would otherwise introduce, the same reason `/tasks`
sends `X-Total-Count` and the changelog tool says what its page is a page of.
"""


def _edge_line(edge: dependencies_service.DependencyEdge) -> str:
    """One dependency, from the reader's own point of view.

    `edge.task is None` is a real answer rather than an error: task access
    has six routes in, so the far end of an edge can be perfectly invisible
    to somebody who can see this end of it. Naming it would leak exactly
    what `effective_task_level` refuses to.
    """
    if edge.task is None:
        return f"[{edge.other_task_id}] — a task you can't see"
    other = edge.task
    return (
        f"[{other.id}] {other.title} "
        f"(status={other.status}, {'closed' if other.closed_at else 'open'})"
    )


async def _claim_key(db, user: User, key: str | None, tool: str):
    """Take an idempotency key, or hand back what it produced last time.

    Returns `(claim, existing_id)`; both are None when no key was supplied,
    which is the ordinary case and must stay free. `services/idempotency.py`
    holds the reasoning — this only turns its two exceptions into refusals
    the model can read, the same job `_refusal` does for HTTP ones.
    """
    if not key or not key.strip():
        return None, None
    try:
        held = await idempotency_service.claim(db, user.id, key, tool)
    except idempotency_service.InProgress as exc:
        raise Denied(
            "A call with that idempotency key is already running. Wait a moment "
            "and ask again with the same key — do not retry without one, which "
            "is how the duplicate you are avoiding gets created."
        ) from exc
    except idempotency_service.KeyReused as exc:
        raise Denied(str(exc)) from exc
    return held, held.existing_id


async def _release_key(db, held) -> None:
    """Hand a claim back after the work raised. A no-op when no key was
    supplied, so callers need no branch of their own."""
    if held is not None:
        await idempotency_service.release(db, held)


def _refusal(exc: HTTPException) -> Denied:
    """A service's `HTTPException` as a refusal the model can actually read.

    Services raise 403/404/409/422 carrying a sentence that says what went
    wrong — "that would create a dependency cycle", "you have read-only
    access to this task". An `HTTPException` escaping a tool is an
    *unhandled* exception as far as the SDK is concerned, and its text is
    deliberately withheld (see `Denied`), so without this the caller is told
    only `Error executing tool add_dependency` and has nothing to act on.
    """
    return Denied(str(exc.detail))


# --- reading ---------------------------------------------------------------------


@mcp.tool()
async def organisations(ctx: Context) -> str:
    """List the organisations you belong to. Start here: most other tools need
    an organisation id."""
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        rows = await organisations_service.list_for_user(db, user)
    if not rows:
        return "You are not a member of any organisation."
    return "\n".join(f"[{org.id}] {org.name} (you are {role})" for org, role in rows)


@mcp.tool()
async def list_projects(
    ctx: Context,
    organisation_id: Annotated[str, Field(description="From `organisations`.")],
    include_archived: bool = False,
) -> str:
    """Projects you can see, with their ids — what `project_id` on
    `create_task` and `update_task` wants. A project is private to its owner
    until shared, so this is your list, not the organisation's."""
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        rows = await projects_service.list_visible(
            db, org, user.id, include_archived=include_archived
        )
    if not rows:
        return "No projects you can see yet."
    lines = []
    for project, level in rows:
        bits = [f"[{project.id}]", project.name, f"access={level}"]
        if project.archived_at:
            bits.append("archived")
        lines.append(" | ".join(bits))
    return "\n".join(lines)


@mcp.tool()
async def list_members(
    ctx: Context,
    organisation_id: Annotated[str, Field(description="From `organisations`.")],
) -> str:
    """Who is in this organisation, by email — which is what `owner_email`
    and `action_required_email` want.

    Only people who have actually joined. An outstanding invitation is a
    person who cannot own a task or be asked to act on one yet, so listing
    them here would only offer a choice every write tool then refuses.
    """
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        rows = await organisations_service.list_members(db, org.organisation.id)
    lines = [
        " | ".join(
            [person.email, person.display_name or person.email, f"role={member.role}"]
            + (["you"] if person.id == user.id else [])
        )
        for member, person, _invited_by in rows
        if member.status == MEMBER_STATUS_ACTIVE and person is not None
    ]
    if not lines:
        return "Nobody has joined this organisation yet."
    return "\n".join(lines)


@mcp.tool()
async def list_tasks(
    ctx: Context,
    organisation_id: Annotated[str, Field(description="From `organisations`.")],
    status: Annotated[
        str | None, Field(description=f"One of: {', '.join(STATUSES)}.")
    ] = None,
    priority: Annotated[
        str | None, Field(description=f"One of: {', '.join(PRIORITIES)}.")
    ] = None,
    mine_only: Annotated[
        bool, Field(description="Only tasks you own or have been asked to act on.")
    ] = False,
    include_closed: bool = False,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> str:
    """Tasks you can see, newest activity first. This is the 'what needs doing'
    tool: with no filters it returns everything open."""
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        rows, total = await tasks_service.list_page(
            db,
            org,
            user,
            limit=limit,
            offset=0,
            include_closed=include_closed,
            status=status,
            priority=priority,
            # ORs owner against action-required, which is what this tool has
            # always claimed to do — it used to pass `owner_user_id` alone,
            # so a task somebody had asked you to act on was excluded from
            # "only tasks you own or have been asked to act on". Same
            # question the dashboard's Critical and Urgent cards ask.
            mine_user_id=user.id if mine_only else None,
            sort="updated_at",
            descending=True,
        )
        names = await _project_names(db, org, user)
    if not rows:
        return "Nothing matches."
    header = f"{len(rows)} of {total} task(s):"
    return header + "\n" + "\n".join(_one_line(task, names) for task, _ in rows)


@mcp.tool()
async def search(
    ctx: Context,
    organisation_id: str,
    query: Annotated[
        str,
        Field(description="Typo-tolerant; matches titles, descriptions and tags."),
    ],
) -> str:
    """Find tasks, projects and knowledge-base articles by text. Use this
    when the person names something rather than giving an id. A private
    article only turns up here for its own owner, same as everywhere else."""
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        hits = await search_service.search(db, org, user.id, q=query, limit=10)
    if not hits:
        return f"Nothing matches {query!r}."
    return "\n".join(
        f"[{h.id}] {h.kind}: {h.title}" + (f" — {h.subtitle}" if h.subtitle else "")
        for h in hits
    )


@mcp.tool()
async def task(ctx: Context, organisation_id: str, task_id: str) -> str:
    """Everything about one task: what it says, what it is waiting on, its
    checklists, its files, its comments and its history.

    **Read this before picking work back up.** A task's comment thread is
    where its state actually lives — the decisions taken, the corrections,
    what is waiting on a person — so a task read without it looks like a
    task nobody has started, and the honest move after that is to begin
    again rather than continue. The thread is capped here, and whenever it
    is the real total is stated: an answer that has been truncated must
    never read as a complete one.
    """
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        t = tctx.task
        events = await tasks_service.list_events(db, t.id)
        tags = (await tags_service.for_tasks(db, [t.id])).get(t.id, [])
        depends_on, blocks = await dependencies_service.list_dependencies(db, org, user, t.id)
        checklists = await checklists_service.for_task(db, t.id)
        # `create=False`, the default: *reading* a task must not bring a
        # thread into existence. `conversation` is None until somebody
        # comments, and both readers below take that.
        thread = await conversations_service.for_task(db, org, user, t.id)
        messages = await conversations_service.list_messages(db, thread.conversation)
        files = await attachments_service.for_task(
            db, t, thread.conversation.id if thread.conversation else None
        )

        lines = [
            f"{t.title}  [{t.id}]",
            f"status={t.status} priority={t.priority} "
            f"{'closed' if t.closed_at else 'open'} your access={tctx.level}",
        ]
        if t.due_on:
            lines.append(f"due {t.due_on}")
        if tags:
            lines.append("tags: " + ", ".join(tag.name for tag in tags))
        if t.description:
            # The stripped column, so the model reads prose rather than markup.
            lines.append("\n" + (t.description_text or "").strip())

        if depends_on or blocks:
            lines.append("")
            lines += [f"waiting on: {_edge_line(e)}" for e in depends_on]
            lines += [f"blocking: {_edge_line(e)}" for e in blocks]

        for checklist in checklists:
            done = sum(1 for item in checklist.items if item.done_at)
            lines.append(
                f"\nchecklist {checklist.title} "
                f"[{checklist.id}] — {done}/{len(checklist.items)} done"
            )
            lines += [
                f"  [{'x' if item.done_at else ' '}] {item.text}  [{item.id}]"
                for item in checklist.items
            ]

        # A removed comment has had its body cleared by `remove()`, so there
        # is nothing of the person's own words left to read back — left out
        # entirely rather than shown as a tombstone, the same call
        # `conversations.for_tasks` makes for the data export.
        live = [(m, u) for m, u in messages if m.deleted_at is None]
        if live:
            shown = live[-MAX_THREAD:]
            counted = (
                f"the last {len(shown)} of {len(live)}"
                if len(shown) < len(live)
                else f"{len(live)}"
            )
            lines.append(f"\ncomments ({counted}, oldest first):")
            for message, author in shown:
                who = author.email if author else "someone since removed"
                # Attribution, not authorship — see `models/conversation.py`.
                # Worth reading back so an assistant can tell its own earlier
                # notes from what a colleague actually typed.
                via = f" via {message.via}" if message.via else ""
                edited = " (edited)" if message.edited_at else ""
                lines.append(f"  {message.created_at:%Y-%m-%d %H:%M} {who}{via}{edited}:")
                lines += [f"    {line}" for line in message.body.strip().splitlines()]

        if files:
            lines.append("\nfiles:")
            lines += [f"  {f.filename} ({f.content_type}, {f.size_bytes} bytes)" for f in files]

        if events:
            lines.append("\nhistory (oldest first):")
            lines += [f"  {e.created_at:%Y-%m-%d %H:%M} {e.kind}" for e, _ in events[-20:]]
    return "\n".join(lines)


@mcp.tool()
async def task_versions(ctx: Context, organisation_id: str, task_id: str) -> str:
    """Earlier versions of a task's title and description, newest first.

    Every version a save replaced, for "what did this say before somebody
    overwrote it". Read-only — restoring one is deliberately not a tool: it
    silently replaces text somebody is working on, and the person asking is
    better served by the words back in front of them than by an assistant
    picking a version for them. Copy the one they want into `update_task`
    if that is what they actually ask for.
    """
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        revisions = await tasks_service.list_revisions(db, tctx.task.id)
        if not revisions:
            return "Nothing has been saved over on this task yet."
        lines = [f"Earlier versions of {tctx.task.title}  [{tctx.task.id}]", ""]
        for revision, who in revisions:
            lines.append(
                f"{revision.created_at:%Y-%m-%d %H:%M} — replaced by "
                f"{who.email if who else 'someone since removed'}"
            )
            lines.append(f"  title: {revision.title}")
            # Stripped of markup, the same reason `task` above reads
            # `description_text` rather than the stored HTML — there is no
            # generated column here (history isn't searched), so this is
            # `richtext`'s own converter doing the same job on demand.
            body = richtext.to_plain_text(revision.description or "").strip()
            lines.append(f"  description: {body or '(none)'}")
            lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def activity(
    ctx: Context,
    organisation_id: str,
    days: Annotated[int, Field(ge=1, le=90, description="How far back to look.")] = 7,
    mine_only: Annotated[
        bool, Field(description="Only tasks you own or have been asked to act on.")
    ] = False,
) -> str:
    """What changed recently — the tool for 'what did we get done last week'.

    Reports on *activity*, which includes comments, files and logged time, not
    only tasks whose status moved.
    """
    user, _ = await _caller(ctx)
    since = datetime.now(UTC) - timedelta(days=days)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        rows, _ = await tasks_service.list_page(
            db,
            org,
            user,
            limit=200,
            offset=0,
            include_closed=True,
            # Same OR as `list_tasks` above, and worded the same way — two
            # tools with one parameter name meaning two different things is
            # the kind of difference nobody discovers deliberately.
            mine_user_id=user.id if mine_only else None,
            sort="updated_at",
            descending=True,
        )
        recent = [(t, lvl) for t, lvl in rows if t.updated_at and t.updated_at >= since]
        names = await _project_names(db, org, user)
    if not recent:
        return f"Nothing has changed in the last {days} day(s)."
    closed = [t for t, _ in recent if t.closed_at and t.closed_at >= since]
    lines = [f"{len(recent)} task(s) touched in the last {days} day(s); {len(closed)} closed."]
    lines += [_one_line(t, names) for t, _ in recent]
    return "\n".join(lines)


@mcp.tool()
async def my_reminders(ctx: Context) -> str:
    """Your reminders, across every organisation. Yours alone — nobody else's
    are visible to anybody."""
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        rows = (await db.execute(reminders_service.mine_stmt(user_id=user.id))).all()
        today = reminders_service.today_for(user)
    if not rows:
        return "No reminders."
    return "\n".join(
        f"{r.remind_on}"
        f"{' (due)' if reminders_service.is_overdue(r.remind_on, today=today) else ''} "
        f"{r.note or t.title} [{t.id}]"
        for r, t in rows
    )


@mcp.tool()
async def notifications(
    ctx: Context,
    unread_only: bool = True,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> str:
    """Your notification inbox, across every organisation — the same list and
    the same count the bell in the web app shows.

    Deliberately not organisation-scoped, unlike almost everything else here.
    A notification is addressed to a person, not filed in a place: some carry
    an organisation and some don't, and a count that disagreed with the bell
    would be a second, quieter answer to the same question.
    """
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        rows = await notifications_service.list_for_user(
            db, user, unread_only=unread_only, limit=limit
        )
        unread = await notifications_service.unread_count(db, user)
    # The count leads, on its own line, and is stated even when nothing is
    # listed: it is the answer to "how many", which is a different question
    # from "which ones" and the only one some callers are asking.
    header = f"{unread} unread"
    if not rows:
        return header + "." if unread == 0 else header + ", none listed."
    lines = [header + ":"]
    for row in rows:
        bits = [f"[{row.id}]", row.kind, row.title]
        if row.read_at:
            bits.append("read")
        lines.append(" | ".join(bits))
    return "\n".join(lines)


def _book_line(book, level: str) -> str:
    bits = [f"[{book.id}]", book.name, f"access={level}"]
    if book.archived_at:
        bits.append("archived")
    return " | ".join(bits)


@mcp.tool()
async def list_books(
    ctx: Context,
    organisation_id: str,
    include_archived: bool = False,
) -> str:
    """Books in the knowledge base you can see. A book is private to its
    owner until shared, the same rule a project follows."""
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        rows = await books_service.list_visible(
            db, org, user.id, include_archived=include_archived
        )
    if not rows:
        return "No books you can see yet."
    return "\n".join(_book_line(book, level) for book, level in rows)


@mcp.tool()
async def list_articles(ctx: Context, organisation_id: str, book_id: str) -> str:
    """Articles in one book — the table of contents. Your own private drafts
    are included; anyone else's simply don't appear."""
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            bctx = await books_service.context_for(db, org, uuid.UUID(book_id), user.id)
        except Exception as exc:
            raise Denied("No such book, or you can't see it.") from exc
        rows = await articles_service.list_for_book(db, org, bctx.book.id, user.id)
    if not rows:
        return f"Nothing in {bctx.book.name} yet."
    lines = [f"{bctx.book.name}:"]
    for article, level, rev in rows:
        title = (rev.title if rev else "") or "Untitled"
        state = "private draft" if article.is_private else "published"
        lines.append(f"[{article.id}] {title} ({state}) access={level}")
    return "\n".join(lines)


@mcp.tool()
async def read_article(ctx: Context, organisation_id: str, article_id: str) -> str:
    """Everything about one article: its current text, and whether it's
    published."""
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            actx = await articles_service.context_for(db, org, uuid.UUID(article_id), user.id)
        except Exception as exc:
            raise Denied("No such article, or you can't see it.") from exc
        rev = await articles_service.latest_revision(db, actx.article.id)
        book = await db.get(Book, actx.article.book_id)
    title = (rev.title if rev else "") or "Untitled"
    state = "private draft — only you can see this" if actx.article.is_private else "published"
    lines = [
        f"{title}  [{actx.article.id}]",
        f"book={book.name if book else '?'} {state} your access={actx.level}",
    ]
    if rev and rev.body_text:
        # The stripped column, so the model reads prose rather than markup —
        # the identical reasoning `task`'s own tool has for `description_text`.
        lines.append("\n" + rev.body_text.strip())
    return "\n".join(lines)


# --- writing ------------------------------------------------------------------------


@mcp.tool()
async def create_task(
    ctx: Context,
    organisation_id: str,
    title: str,
    description: Annotated[
        str | None,
        Field(description="Markdown (headings, bold, lists, links) or plain text."),
    ] = None,
    project_id: Annotated[str | None, Field(description="Omit for a loose task.")] = None,
    owner_email: Annotated[
        str | None,
        Field(description="Who owns it. Defaults to you. Must be a member already."),
    ] = None,
    action_required_email: Annotated[
        str | None, Field(description="Who is being asked to act. They are notified.")
    ] = None,
    priority: str = "normal",
    due_on: Annotated[str | None, Field(description="YYYY-MM-DD.")] = None,
    planner_bucket: Annotated[
        str | None,
        Field(
            description="Put it straight on your own planner board. "
            f"One of: {', '.join(PLANNER_BUCKETS)}."
        ),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Field(
            description="Any string of your own. Send the SAME one if you retry "
            "this call after a timeout, and the task will not be created twice."
        ),
    ] = None,
) -> str:
    """Create a task, optionally for somebody else.

    Naming a person by email rather than id, because that is what a person
    says out loud. They must already be a member of the organisation — this
    will not invite anybody.

    `planner_bucket` is **yours**, not the owner's, even when you are
    creating this for somebody else: a planner is one person's plan for
    their own week (see models/planner.py), and putting work on a colleague's
    board because you filed a ticket for them is not a thing to do quietly.

    **If a call times out, retry it with the same `idempotency_key`.** A
    timeout says nothing about whether the task was created, and calling
    again without a key is how one request becomes two tasks.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        # Checked before anything is claimed or written. It used to be
        # validated *after* `create`, which left a stray task behind every
        # time somebody guessed a bucket name wrong — refusing and creating
        # at the same time is the worst of both.
        if planner_bucket and planner_bucket not in PLANNER_BUCKETS:
            raise Denied(
                f"{planner_bucket!r} is not a planner bucket. "
                f"One of: {', '.join(PLANNER_BUCKETS)}."
            )
        held, already = await _claim_key(db, user, idempotency_key, "create_task")
        if already is not None:
            # The first attempt landed after all. Answering with its id is
            # the whole point — the caller retried precisely because it
            # could not tell.
            return f"Already created [{already}] under that idempotency key."
        try:
            owner = await _member_by_email(db, org, owner_email)
            acting = await _member_by_email(db, org, action_required_email)
            created = await tasks_service.create(
                db,
                org,
                user,
                title=title,
                # Markdown in, always — an assistant writes **bold**, not
                # tags. A plain sentence with no markdown syntax converts to
                # itself wrapped in a single <p>, so this is never a worse
                # outcome than the old plain-text path.
                description=richtext.from_markdown(description) if description else None,
                project_id=uuid.UUID(project_id) if project_id else None,
                priority=priority,
                owner_user_id=owner,
                action_required_user_id=acting,
                due_on=date.fromisoformat(due_on) if due_on else None,
            )
        except HTTPException as exc:
            # Nothing was created, so the key must not stay claimed —
            # somebody who sent a bad argument, read the refusal and fixed it
            # would otherwise be told their own failed call was still
            # running. And the refusal has to be readable to be fixable:
            # without `_refusal`, "priority must be one of …" arrives as the
            # bare "Error executing tool create_task".
            await _release_key(db, held)
            raise _refusal(exc) from exc
        except Exception:
            await _release_key(db, held)
            raise

        if held is not None:
            # **The moment the task exists, the key is answered** — and
            # before the placement below, deliberately. Recording after it
            # would mean a failed placement released the key on a task that
            # had already committed, and the next retry would file a second
            # one: exactly the duplicate this argument exists to prevent.
            await idempotency_service.record(db, held, created.id)

        if planner_bucket:
            # Appended to the end of the bucket — `position=None`. Same
            # bargain the task screen's own bucket picker makes: fetching a
            # whole planner board to work out a midpoint, in order to place
            # one task somebody has not looked at yet, would be a strange
            # trade.
            await planner_service.place(
                db,
                target_user_id=user.id,
                target_org_role=org.role,
                org_id=org.organisation.id,
                task_id=created.id,
                bucket=planner_bucket,
            )
    return f"Created [{created.id}] {created.title}"


@mcp.tool()
async def update_task(
    ctx: Context,
    organisation_id: str,
    task_id: str,
    title: Annotated[str | None, Field(description="Omit to leave the title unchanged.")] = None,
    description: Annotated[
        str | None,
        Field(
            description="Markdown or plain text. Omit to leave it unchanged; "
            "pass an empty string to clear it."
        ),
    ] = None,
    project_id: Annotated[
        str | None,
        Field(
            description="Move it here. Pass an empty string to make it a loose task; "
            "omit to leave it where it is."
        ),
    ] = None,
    owner_email: Annotated[
        str | None,
        Field(
            description="Hand it to somebody else. Must already be a member of the organisation."
        ),
    ] = None,
    status: str | None = None,
    priority: str | None = None,
    due_on: Annotated[
        str | None, Field(description="YYYY-MM-DD. Pass an empty string to clear it.")
    ] = None,
    action_required_email: Annotated[
        str | None,
        Field(description="Who is being asked to act. Pass an empty string to clear it."),
    ] = None,
) -> str:
    """Change a task. Only the fields you pass are touched."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    fields: dict = {}
    if title is not None:
        fields["title"] = title
    if description is not None:
        # Markdown in, always, matching create_task — an empty string clears
        # the description rather than converting to an empty <p>.
        fields["description"] = richtext.from_markdown(description) if description else None
    if status is not None:
        fields["status"] = status
    if priority is not None:
        fields["priority"] = priority
    if due_on is not None:
        fields["due_on"] = date.fromisoformat(due_on) if due_on else None
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        if action_required_email is not None:
            fields["action_required_user_id"] = await _member_by_email(
                db, org, action_required_email
            )
        if project_id is not None:
            fields["project_id"] = uuid.UUID(project_id) if project_id else None
        # Never sent as an explicit None: a task always has an owner, and
        # unlike the other fields here there is no "clear" reading of one.
        if owner_email:
            fields["owner_user_id"] = await _member_by_email(db, org, owner_email)
        if not fields:
            return "Nothing to change."
        updated = await tasks_service.update(db, tctx, org, user, fields=fields)
    return f"Updated [{updated.id}] {updated.title}"


@mcp.tool()
async def close_task(ctx: Context, organisation_id: str, task_id: str) -> str:
    """Close a task. Only the owner — or an organisation admin — may; status
    and open/closed are separate fields, so a task can be closed from any
    status. Everyone else sees the identical refusal the web app's own
    missing button implies."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        task = await tasks_service.set_open(db, tctx, org, user, closed=True)
    return f"Closed [{task.id}] {task.title}"


@mcp.tool()
async def reopen_task(ctx: Context, organisation_id: str, task_id: str) -> str:
    """Reopen a closed task. Same owner-or-admin rule as closing."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        task = await tasks_service.set_open(db, tctx, org, user, closed=False)
    return f"Reopened [{task.id}] {task.title}"


@mcp.tool()
async def comment(
    ctx: Context,
    organisation_id: str,
    task_id: str,
    body: str,
    idempotency_key: Annotated[
        str | None,
        Field(
            description="Any string of your own. Send the SAME one if you retry "
            "this call after a timeout, and the comment will not be posted twice."
        ),
    ] = None,
) -> str:
    """Add a comment to a task, as you. Everyone who can see the task sees it.

    **Posted under your own name, and marked as having come through this
    credential** — the thread shows "via {the token's name}" beside it. So
    there is no need to prefix what you write with your own name to make the
    source clear; the product records that itself, and a prefix typed into
    the body would be a convention only you remember to keep.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        held, already = await _claim_key(db, user, idempotency_key, "comment")
        if already is not None:
            return "Already posted under that idempotency key."
        try:
            thread = await conversations_service.for_task(
                db, org, user, uuid.UUID(task_id), create=True
            )
            posted = await conversations_service.post(
                db, org, thread, user, body=body, via=tok.via
            )
        except HTTPException as exc:
            # Nothing was posted, so the key goes back — see `create_task`.
            await _release_key(db, held)
            # Services here say real things — "that comment is too long",
            # "you can't comment on this" — and flattening all of them into
            # the sentence below told somebody with a 10,001-character
            # comment that their task did not exist.
            raise _refusal(exc) from exc
        except Exception as exc:
            await _release_key(db, held)
            raise Denied("No such task, or you can't comment on it.") from exc
        if held is not None:
            await idempotency_service.record(db, held, posted.id)
    return "Posted." if not tok.via else f"Posted, attributed to you via {tok.via}."


@mcp.tool()
async def tag_task(
    ctx: Context,
    organisation_id: str,
    task_id: str,
    tag: Annotated[str, Field(description="e.g. billing. Created if it's the first use.")],
) -> str:
    """Apply a tag to a task, as you. Get-or-create by name, the same as the
    web app's picker — typing a tag that already exists reuses it rather
    than making a twin. Needs write on the task, like any other edit."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        try:
            tctx.require(
                tasks_service.can_edit(tctx.level), "you have read-only access to this task"
            )
        except HTTPException as exc:
            # Otherwise the one sentence saying why arrives as the bare
            # string "Error executing tool …" — see `_refusal`.
            raise _refusal(exc) from exc
        applied = await tags_service.get_or_create(db, org, user, name=tag)
        await tags_service.apply(db, tctx.task, applied)
        await tasks_service.announce(db, tctx.task, "tagged")
        current = (await tags_service.for_tasks(db, [tctx.task.id])).get(tctx.task.id, [])
    return f"Tagged [{tctx.task.id}] {tctx.task.title}: " + ", ".join(t.name for t in current)


@mcp.tool()
async def untag_task(ctx: Context, organisation_id: str, task_id: str, tag: str) -> str:
    """Take a tag off a task, by name. The tag itself survives — it's shared
    vocabulary — only this one tasking of it goes. Needs write on the task."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        try:
            tctx.require(
                tasks_service.can_edit(tctx.level), "you have read-only access to this task"
            )
        except HTTPException as exc:
            # Otherwise the one sentence saying why arrives as the bare
            # string "Error executing tool …" — see `_refusal`.
            raise _refusal(exc) from exc
        existing = await tags_service.find_by_name(db, org, tag)
        if existing is None:
            raise Denied(f"No tag named {tag!r} in this organisation.")
        await tags_service.unapply(db, tctx.task, existing.id)
        await tasks_service.announce(db, tctx.task, "untagged")
    return f"Untagged [{tctx.task.id}] {tctx.task.title}: removed {existing.name!r}"


@mcp.tool()
async def add_dependency(
    ctx: Context,
    organisation_id: str,
    task_id: str,
    depends_on_task_id: Annotated[
        str,
        Field(description="What it is waiting on. You have to be able to open that one too."),
    ],
) -> str:
    """Record that one task is waiting on another. Reads left to right:
    `task_id` depends on `depends_on_task_id`.

    Use this instead of typing an id into a comment. It is what makes "what
    is blocked, and on whom?" answerable by reading a task rather than by
    reading its prose — `task` reports both directions, so the other task
    learns it is blocking this one with nothing further to record.

    **Informational, and there is deliberately no enforcement to find.**
    Closing a task with open dependencies still works; the point is
    visibility, not a gate. The graph does stay acyclic — an edge that would
    close a loop is refused rather than quietly accepted. Needs write on the
    task being edited.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        try:
            other = uuid.UUID(depends_on_task_id)
        except ValueError as exc:
            raise Denied("That is not a task id.") from exc
        try:
            # Resolves the other task through `tasks_service.context_for`
            # itself — rule 1 of `services/dependencies.py`, and the reason
            # there is no second access check written here.
            await dependencies_service.add_dependency(
                db, tctx, org, user, depends_on_task_id=other
            )
        except HTTPException as exc:
            raise _refusal(exc) from exc
    return f"[{tctx.task.id}] {tctx.task.title} is now waiting on [{other}]."


@mcp.tool()
async def remove_dependency(
    ctx: Context, organisation_id: str, task_id: str, depends_on_task_id: str
) -> str:
    """Stop recording that `task_id` is waiting on `depends_on_task_id`.

    Named by the two tasks rather than by the link's own id, because those
    are the two ids you already have. Needs write on the task being edited.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        try:
            other = uuid.UUID(depends_on_task_id)
        except ValueError as exc:
            raise Denied("That is not a task id.") from exc
        depends_on, _ = await dependencies_service.list_dependencies(db, org, user, tctx.task.id)
        edge = next((e for e in depends_on if e.other_task_id == other), None)
        if edge is None:
            raise Denied("This task is not waiting on that one.")
        try:
            await dependencies_service.remove_dependency(db, tctx, user, edge.dependency_id)
        except HTTPException as exc:
            raise _refusal(exc) from exc
    return f"[{tctx.task.id}] {tctx.task.title} is no longer waiting on [{other}]."


@mcp.tool()
async def add_checklist(
    ctx: Context,
    organisation_id: str,
    task_id: str,
    title: Annotated[str, Field(description="e.g. 'Before we deploy'.")],
    items: Annotated[
        list[str] | None,
        Field(description="Optional first items, in order. More later with add_checklist_item."),
    ] = None,
) -> str:
    """Put a checklist on a task, with its items if you have them.

    **Prefer this to writing the steps into a description.** An item has its
    own state, so what is outstanding is something you can read back and
    report precisely, and a person can tick one off from their phone without
    editing prose. A list of steps in a description is none of those things.

    A task can carry more than one — "packing list" and "before we ship" are
    two lists, not two sections of one. Shared task content, not a personal
    record: everyone who can see the task sees the same boxes, and anyone
    with write can tick them. Needs write on the task.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        try:
            tctx.require(
                tasks_service.can_edit(tctx.level), "you have read-only access to this task"
            )
            checklist = await checklists_service.add_checklist(db, tctx.task, title=title)
            added = [
                # A blank line in a pasted list is not an item, and the
                # service would 422 on it — losing every item after it as
                # well as the blank one.
                await checklists_service.add_item(db, checklist, text=text)
                for text in (items or [])
                if text.strip()
            ]
        except HTTPException as exc:
            raise _refusal(exc) from exc
        await tasks_service.announce(db, tctx.task, "checklist_added")
    lines = [f"Added checklist {checklist.title!r} [{checklist.id}] to {tctx.task.title}."]
    lines += [f"  [ ] {item.text}  [{item.id}]" for item in added]
    return "\n".join(lines)


@mcp.tool()
async def add_checklist_item(
    ctx: Context,
    organisation_id: str,
    task_id: str,
    checklist_id: Annotated[str, Field(description="From `task` or from `add_checklist`.")],
    text: str,
) -> str:
    """Add one item to a checklist that already exists. Needs write on the task."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        try:
            tctx.require(
                tasks_service.can_edit(tctx.level), "you have read-only access to this task"
            )
            # Scoped to this task, so a checklist id belonging to another one
            # is a 404 rather than a cross-task write.
            checklist = await checklists_service.get_checklist_or_404(
                db, tctx.task.id, uuid.UUID(checklist_id)
            )
            item = await checklists_service.add_item(db, checklist, text=text)
        except HTTPException as exc:
            raise _refusal(exc) from exc
        except ValueError as exc:
            raise Denied("That is not a checklist id.") from exc
        await tasks_service.announce(db, tctx.task, "checklist_item_added")
    return f"Added to {checklist.title!r}: [ ] {item.text}  [{item.id}]"


@mcp.tool()
async def check_item(
    ctx: Context,
    organisation_id: str,
    task_id: str,
    item_id: Annotated[str, Field(description="From `task`'s checklist section.")],
    done: Annotated[bool, Field(description="False unticks it again.")] = True,
) -> str:
    """Tick a checklist item off, or untick it.

    Found by id across every checklist on the task, so the id `task` printed
    beside the item is the only one you need. Needs write on the task:
    ticking a box changes content everybody shares, unlike logging your own
    time against a task you can only read.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        try:
            wanted = uuid.UUID(item_id)
        except ValueError as exc:
            raise Denied("That is not a checklist item id.") from exc
        try:
            tctx.require(
                tasks_service.can_edit(tctx.level), "you have read-only access to this task"
            )
            # `for_task` eager-loads items, so this walk touches no lazy
            # relationship — see `checklists.get_checklist_or_404`'s own
            # docstring for what happens when one does.
            checklists = await checklists_service.for_task(db, tctx.task.id)
            found = next(
                ((c, i) for c in checklists for i in c.items if i.id == wanted),
                None,
            )
            if found is None:
                raise Denied("No checklist item with that id on this task.")
            checklist, item = found
            item = await checklists_service.update_item(db, item, fields={"done": done})
        except HTTPException as exc:
            raise _refusal(exc) from exc
        await tasks_service.announce(db, tctx.task, "checklist_item_toggled")
        outstanding = sum(1 for i in checklist.items if i.done_at is None)
    return (
        f"{'Ticked' if done else 'Unticked'} {item.text!r} in {checklist.title!r}. "
        f"{outstanding} left on that list."
    )


@mcp.tool()
async def attach_file(
    ctx: Context,
    organisation_id: str,
    task_id: str,
    filename: Annotated[str, Field(description="e.g. screenshot.png")],
    content_type: Annotated[
        str, Field(description="MIME type, e.g. image/png. Codec parameters are stripped.")
    ],
    content_base64: Annotated[str, Field(description="The file's bytes, base64-encoded.")],
) -> str:
    """Attach a file to a task's Files panel, as you.

    The bytes travel in this call, unlike the browser: a browser uploads
    straight to storage and the API never sees the bytes, because a phone
    video shouldn't occupy a worker for two minutes. An assistant has no
    browser and no direct route to the bucket, so this is the one place in
    the product where a file passes through the API — deliberately, and only
    here. Keep it to things you'd actually paste into a chat (a screenshot, a
    short recording, a PDF); base64 costs about a third more than the file's
    own size, both over the wire and in this conversation's context.

    Same rules as everywhere else a file lands: the type has to be one this
    product accepts, there's a size ceiling, and you need write access on the
    task — attaching changes what the task *is*, which is a stricter bar than
    commenting on it.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise Denied("That doesn't look like valid base64.") from exc
    if not raw:
        raise Denied("That file is empty.")
    if len(raw) > settings.attachment_max_bytes:
        limit = settings.attachment_max_bytes // (1024 * 1024)
        raise Denied(f"That file is larger than {limit}MB.")

    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        try:
            tctx.require(
                tasks_service.can_edit(tctx.level), "you have read-only access to this task"
            )
        except HTTPException as exc:
            # Otherwise the one sentence saying why arrives as the bare
            # string "Error executing tool …" — see `_refusal`.
            raise _refusal(exc) from exc

        attachment, _upload_url = await attachments_service.create(
            db, user, filename=filename, content_type=content_type, task=tctx.task
        )
        # Steps 2 and 3 of the usual handshake, done server-side: write the
        # bytes ourselves rather than handing back a presigned URL nobody here
        # can PUT to, then run the same confirm the browser path runs — the
        # real size and the real content-type win over whatever was declared.
        await s3.put_object_bytes(attachment.storage_key, raw, attachment.content_type)
        ready = await attachments_service.confirm(db, attachment, user)
        await tasks_service.announce(db, tctx.task, "file_added")
    return (
        f"Attached [{ready.id}] {ready.filename} ({ready.size_bytes} bytes) "
        f"to [{tctx.task.id}] {tctx.task.title}"
    )


@mcp.tool()
async def create_book(
    ctx: Context,
    organisation_id: str,
    name: str,
    description: Annotated[str | None, Field(description="Optional.")] = None,
) -> str:
    """Create a book. You own it, and to begin with nobody else can see it —
    not even the rest of the organisation. Sharing it is a web-only action,
    from its Access panel."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        bctx = await books_service.create(
            db, org, name=name, description=description, user=user
        )
    return f"Created [{bctx.book.id}] {bctx.book.name}"


@mcp.tool()
async def create_article(
    ctx: Context,
    organisation_id: str,
    book_id: str,
    title: str = "",
) -> str:
    """Start a new article in a book. Born as your own private draft —
    nobody else, not even an organisation admin, sees it until you publish
    it with `publish_article`. Needs write access on the book."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            bctx = await books_service.context_for(db, org, uuid.UUID(book_id), user.id)
        except Exception as exc:
            raise Denied("No such book, or you can't see it.") from exc
        article, revision = await articles_service.create(db, bctx, user, title=title)
    return (
        f"Created [{article.id}] {revision.title or 'Untitled'} "
        f"in {bctx.book.name} — private draft"
    )


@mcp.tool()
async def edit_article(
    ctx: Context,
    organisation_id: str,
    article_id: str,
    title: Annotated[
        str | None, Field(description="Omit to leave the title unchanged.")
    ] = None,
    body: Annotated[
        str | None,
        Field(
            description="Markdown (headings, bold, lists, links) or plain text. "
            "Omit to leave the body unchanged."
        ),
    ] = None,
) -> str:
    """Edit an article's title and/or body, as an editing session — the
    identical mechanics the web editor uses. Reopening within half an hour of
    your own last edit continues that same session; longer than that, or
    somebody else's edit in between, starts a fresh revision and freezes the
    old one into history. Needs write access on the article.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    if title is None and body is None:
        return "Nothing to change."
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            actx = await articles_service.context_for(db, org, uuid.UUID(article_id), user.id)
        except Exception as exc:
            raise Denied("No such article, or you can't see it.") from exc
        revision = await articles_service.start_editing_session(db, actx, user)
        saved = await articles_service.autosave_revision(
            db,
            actx,
            revision,
            title=title if title is not None else revision.title,
            # Converted only when it's the fresh value from this call —
            # `revision.body` (the fallback when `body` is omitted) is
            # already-stored HTML from a previous session and must not be
            # run through the markdown parser a second time.
            body=richtext.from_markdown(body) if body is not None else revision.body,
        )
    return f"Saved [{actx.article.id}] {saved.title or 'Untitled'}"


@mcp.tool()
async def publish_article(ctx: Context, organisation_id: str, article_id: str) -> str:
    """Publish an article — the only thing that makes it visible to anyone
    the book is shared with. Owner-only, the same `can_hide`-shaped rule a
    task's own hide/unhide follows."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            actx = await articles_service.context_for(db, org, uuid.UUID(article_id), user.id)
        except Exception as exc:
            raise Denied("No such article, or you can't see it.") from exc
        await articles_service.set_private(db, actx, user, is_private=False)
    return f"Published [{actx.article.id}]"


@mcp.tool()
async def unpublish_article(ctx: Context, organisation_id: str, article_id: str) -> str:
    """Make a published article a private draft again — back to only you.
    Owner-only."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            actx = await articles_service.context_for(db, org, uuid.UUID(article_id), user.id)
        except Exception as exc:
            raise Denied("No such article, or you can't see it.") from exc
        await articles_service.set_private(db, actx, user, is_private=True)
    return f"Made [{actx.article.id}] private again"


@mcp.tool()
async def attach_article_file(
    ctx: Context,
    organisation_id: str,
    article_id: str,
    filename: Annotated[str, Field(description="e.g. diagram.png")],
    content_type: Annotated[
        str, Field(description="MIME type, e.g. image/png. Codec parameters are stripped.")
    ],
    content_base64: Annotated[str, Field(description="The file's bytes, base64-encoded.")],
) -> str:
    """Attach a file to an article, as you — the same deliberate exception
    `attach_file` documents for tasks: the bytes travel in this call because
    an assistant has no browser and no direct route to storage. Keep it to
    things you'd actually paste into a chat; base64 costs about a third more
    than the file's own size, both over the wire and in this conversation's
    context.

    Lands on the article's current editing session, opened or continued the
    same way `edit_article` does — an old revision in history keeps whatever
    was attached to it at the time. Needs write access on the article.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise Denied("That doesn't look like valid base64.") from exc
    if not raw:
        raise Denied("That file is empty.")
    if len(raw) > settings.attachment_max_bytes:
        limit = settings.attachment_max_bytes // (1024 * 1024)
        raise Denied(f"That file is larger than {limit}MB.")

    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            actx = await articles_service.context_for(db, org, uuid.UUID(article_id), user.id)
        except Exception as exc:
            raise Denied("No such article, or you can't see it.") from exc
        revision = await articles_service.start_editing_session(db, actx, user)

        attachment, _upload_url = await attachments_service.create(
            db, user, filename=filename, content_type=content_type, article_revision=revision
        )
        # Steps 2 and 3 of the usual handshake, done server-side — see
        # `attach_file`'s own docstring for why this is the one place a
        # file's bytes pass through the API at all.
        await s3.put_object_bytes(attachment.storage_key, raw, attachment.content_type)
        ready = await attachments_service.confirm(db, attachment, user)
    return (
        f"Attached [{ready.id}] {ready.filename} ({ready.size_bytes} bytes) "
        f"to [{actx.article.id}]"
    )


@mcp.tool()
async def create_reminder(
    ctx: Context,
    organisation_id: str,
    remind_on: Annotated[str, Field(description="YYYY-MM-DD.")],
    task_id: Annotated[
        str | None, Field(description="Anchor it to a task. Omit for a standalone reminder.")
    ] = None,
    title: Annotated[
        str | None,
        Field(description="Required for a standalone reminder (no task_id); ignored otherwise."),
    ] = None,
    note: Annotated[str | None, Field(description="Optional detail.")] = None,
) -> str:
    """Set a reminder for yourself — anchored to a task, or standalone.
    Yours alone; nobody else, ever, sees it."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    if not task_id and not title:
        raise Denied("A standalone reminder needs a title; a task-anchored one needs task_id.")
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        if task_id:
            try:
                tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
            except Exception as exc:
                raise Denied("No such task, or you can't see it.") from exc
            row = await reminders_service.create(
                db, tctx.task, user, remind_on=date.fromisoformat(remind_on), note=note
            )
            return f"Reminder set on [{tctx.task.id}] {tctx.task.title} for {row.remind_on}"
        row = await reminders_service.create_standalone(
            db, org, user, remind_on=date.fromisoformat(remind_on), title=title, note=note
        )
    return f"Reminder set: {row.title} for {row.remind_on}"


@mcp.tool()
async def update_reminder(
    ctx: Context,
    reminder_id: str,
    remind_on: Annotated[
        str | None, Field(description="YYYY-MM-DD. Omit to leave unchanged.")
    ] = None,
    title: Annotated[
        str | None, Field(description="Only meaningful for a standalone reminder.")
    ] = None,
    note: str | None = None,
    done: Annotated[bool | None, Field(description="Mark it done, or undone.")] = None,
) -> str:
    """Move, re-word, or mark a reminder done. Yours alone."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    fields: dict = {}
    if remind_on is not None:
        fields["remind_on"] = date.fromisoformat(remind_on)
    if title is not None:
        fields["title"] = title
    if note is not None:
        fields["note"] = note
    if done is not None:
        fields["done"] = done
    if not fields:
        return "Nothing to change."
    async with SessionLocal() as db:
        try:
            row = await reminders_service.get_or_404(db, uuid.UUID(reminder_id), user)
        except Exception as exc:
            raise Denied("No such reminder.") from exc
        updated = await reminders_service.update_one(db, row, user, fields=fields)
    what = updated.title or updated.note or updated.id
    return f"Updated reminder: {what} for {updated.remind_on}"


@mcp.tool()
async def changelog(
    ctx: Context,
    organisation_id: str,
    query: Annotated[
        str | None,
        Field(description="Optional text to narrow by. Typo-tolerant, same matcher as `search`."),
    ] = None,
    limit: Annotated[int, Field(gt=0, le=200, description="How many entries.")] = 20,
) -> str:
    """The organisation's changelog: a dated record of what happened — a
    version lift, a config change, a supplier switched. Newest first, by the
    date the thing happened rather than the date somebody typed it in.

    Read by every member of the organisation; there is no per-entry
    visibility to resolve. Use `record_change` to add one.
    """
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        rows, total = await changelog_service.list_page(
            db, org, limit=limit, offset=0, q=query or ""
        )
    if not rows:
        return "Nothing in the changelog." if not query else f"Nothing matches {query!r}."
    lines = [
        # The date first, because that is what a log is read by. One line per
        # entry, description collapsed — same density as `_one_line` for a
        # task, and for the same reason.
        f"[{entry.id}] {entry.happened_on} | {' '.join(entry.description.split())[:160]}"
        + (f" | by {author.display_name or author.email}" if author else "")
        for entry, author in rows
    ]
    # Says what this is a page *of*, the same honesty the REST list keeps
    # with `X-Total-Count` — a caller that believes it has everything and
    # doesn't is the failure this avoids.
    if total > len(rows):
        lines.append(f"({len(rows)} of {total} — ask for a larger limit, or narrow with a query.)")
    return "\n".join(lines)


@mcp.tool()
async def record_change(
    ctx: Context,
    organisation_id: str,
    description: Annotated[str, Field(description="What happened. Plain text, not markdown.")],
    happened_on: Annotated[
        str | None,
        Field(description="The date it happened, YYYY-MM-DD. Defaults to your today."),
    ] = None,
) -> str:
    """Add an entry to the organisation's changelog. Any member may.

    **`happened_on` is the date the thing happened, not today by
    necessity** — Tuesday's version lift is routinely recorded on Thursday,
    and filing it under Thursday is the mistake this field exists to avoid.
    If the person says when, pass it; if they don't, leave it out and it
    takes your own today rather than the server's.

    Plain text, deliberately: unlike `create_task`'s description this is
    never rendered as HTML, so markdown syntax would show up literally.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    when: date | None = None
    if happened_on:
        try:
            when = date.fromisoformat(happened_on)
        except ValueError as exc:
            # Anticipated, so it says so — an unhandled ValueError would
            # reach the client as the bare "Error executing tool" string.
            raise Denied("The date must be YYYY-MM-DD.") from exc
    # Pre-validated here rather than left to the service, for `create_spark`'s
    # own reason: `clean_description` raises a 422, which the SDK treats as a
    # crash and withholds the text of. Anticipated, so it says so.
    if not description.strip():
        raise Denied("A changelog entry needs a description.")
    if len(description.strip()) > MAX_CHANGELOG_DESCRIPTION:
        raise Denied(
            f"That description is too long (limit {MAX_CHANGELOG_DESCRIPTION} characters). "
            "It is refused rather than cut, because half an entry says something else."
        )
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        entry = await changelog_service.create(
            db, org, user, description=description, happened_on=when
        )
    return f"Recorded [{entry.id}] {entry.happened_on}: {' '.join(entry.description.split())[:160]}"


@mcp.tool()
async def create_spark(
    ctx: Context,
    body: Annotated[str, Field(description="One field. A thought, a link, a note to self.")],
) -> str:
    """Capture a spark: a stray thought, not yet a task. Yours alone —
    nobody else, not even an organisation admin, ever sees it.

    Takes no organisation, like `my_reminders` and `notifications`: the
    point of a capture tool is catching a thought regardless of which
    organisation happens to be open when it strikes, and a spark carries no
    `organisation_id` at all.

    Use this rather than `create_task` when there is nothing to do yet.
    A task is work somebody is accountable for; a spark is a line in a
    notebook, reviewed and turned into something else — or deleted — later
    on the `/sparks` screen.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    if not body.strip():
        # The service raises a 422 for this, which the SDK would take as a
        # crash and withhold the text of. Anticipated, so it says so.
        raise Denied("A spark needs something in it.")
    async with SessionLocal() as db:
        row = await sparks_service.create(db, user, body=body)
    # One line, whatever was captured: a spark has no title to report back
    # instead, and the body is short by construction.
    return f"Saved [{row.id}] {row.body.splitlines()[0][:120]}"


@mcp.tool()
async def start_timer(ctx: Context, organisation_id: str, task_id: str) -> str:
    """Start timing this task, as you. Starting stops whatever timer you
    already had running elsewhere — switching tasks is the normal case, not
    an error. `read` on the task is enough: time is a record of what you
    did."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            entry, stopped = await time_tracking.start(db, org, user, uuid.UUID(task_id))
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
    line = f"Timer started on [{entry.task_id}]"
    if stopped:
        line += f" (stopped the one running on [{stopped.task_id}])"
    return line


@mcp.tool()
async def running_timer(ctx: Context) -> str:
    """What you are timing right now, in any organisation, or nothing.

    Takes no organisation, like `notifications` and `my_reminders`, and for
    the same reason those don't: there is **one running timer per person
    across the whole installation** — a database constraint, not a
    convention — so "which organisation" is an answer this gives rather than
    a question it asks. A timer started yesterday in one organisation has to
    be findable today from another, or you discover it on Monday.

    `read` is enough. Knowing what your own clock is on is not a write.
    """
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        running = await time_tracking.running_with_task(db, user)
    if running is None:
        return "Nothing is running."
    entry, task = running
    elapsed = time_tracking.duration_seconds(entry.started_at, None, now=datetime.now(UTC))
    # The task's id first, in brackets, like every other row here — and the
    # organisation named as `organisation_id=` rather than `org=` so the
    # value can be handed straight back to any of the tools that ask for one,
    # which is the next thing a caller does with it (`stop_timer` needs none,
    # but `task` and `update_task` both do).
    bits = [
        f"[{task.id}]",
        task.title,
        f"organisation_id={task.organisation_id}",
        f"elapsed={time_tracking.format_duration(elapsed)}",
        f"started={entry.started_at.isoformat()}",
    ]
    return " | ".join(bits)


@mcp.tool()
async def stop_timer(ctx: Context) -> str:
    """Stop whatever timer is currently running, in any organisation.
    Idempotent — nothing running is not an error."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        entry = await time_tracking.stop(db, user)
    return f"Stopped timer on [{entry.task_id}]" if entry else "Nothing was running."


@mcp.tool()
async def log_time(
    ctx: Context,
    organisation_id: str,
    task_id: str,
    minutes: Annotated[int, Field(gt=0, le=24 * 60, description="How long, in minutes.")],
    note: Annotated[str | None, Field(description="Optional detail.")] = None,
) -> str:
    """Record time already spent on a task — for work already done, not a
    live timer. `read` on the task is enough."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            entry = await time_tracking.log_manual(
                db, org, user, uuid.UUID(task_id), minutes=minutes, note=note
            )
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
    return f"Logged {minutes}m on [{entry.task_id}]"


def _require_write(principal: _Principal) -> None:
    """The one place a read-only credential is turned away — same rule,
    same wording, `tokens_service.require_write` already states for a
    personal access token; inlined here since `_Principal` is what every
    tool actually holds now, regardless of which credential shape verified
    it."""
    if principal.scope != SCOPE_WRITE:
        raise Denied(
            "This credential is read-only. Create a token with write access, or "
            "authorize with write scope, if you want the assistant to change anything."
        )


async def _member_by_email(db, org, email: str | None) -> uuid.UUID | None:
    """Resolve a colleague's email to their id, refusing outsiders.

    Deliberately not "invite them if they're missing": an assistant quietly
    adding people to an organisation is not a thing anybody asked for.
    """
    if not email:
        return None
    from sqlalchemy import select

    from app.models import OrganisationMember
    from app.models.organisation import STATUS_ACTIVE

    row = (
        await db.execute(
            select(User.id)
            .join(OrganisationMember, OrganisationMember.user_id == User.id)
            .where(
                User.email == email.strip().lower(),
                OrganisationMember.organisation_id == org.organisation.id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise Denied(f"{email} is not a member of that organisation.")
    return row


__all__ = ["mcp"]
