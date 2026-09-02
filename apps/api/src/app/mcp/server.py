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

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

# **`mcp.server.mcpserver.context`, not `mcp.server.context`.** There are two
# classes called Context in this SDK, and the tool decorator only recognises
# this one — the other is accepted by the type checker and then fails at
# registration with a Pydantic schema error about IsInstanceSchema, which says
# nothing at all about the actual mistake.
from mcp.server.mcpserver.context import Context
from pydantic import AnyHttpUrl, Field

from app.core.config import settings
from app.db import SessionLocal
from app.models import User
from app.models.task import PRIORITIES, STATUSES
from app.models.token import SCOPE_READ, SCOPE_WRITE
from app.services import attachments as attachments_service
from app.services import organisations as organisations_service
from app.services import projects as projects_service
from app.services import reminders as reminders_service
from app.services import search as search_service
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
        "Project and task management. Every call acts as the person whose "
        "access token is in use and can only reach what they can reach.\n\n"
        "Start with `organisations` — almost everything else needs an "
        "organisation id. Task ids are UUIDs and are stable; quote them back "
        "when the person refers to 'that task'.\n\n"
        "Statuses are todo, in_progress, review, on_hold and blocker. "
        "Open/closed is a separate field: a task can be closed at any status, "
        "and there is no 'done' status. Priorities run critical, urgent, "
        "high, normal, low, very_low."
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


class Denied(Exception):
    """Turned into a tool error rather than a 500."""


class _Principal:
    """A `.scope` shim so `_require_write` needs no changes regardless of
    whether the verified credential was a personal access token or an OAuth
    access token — see `models/token.py`'s `SCOPE_READ`/`SCOPE_WRITE`."""

    def __init__(self, scope: str) -> None:
        self.scope = scope


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
    return user, _Principal(scope)


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
            owner_user_id=user.id if mine_only else None,
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
    """Find tasks and projects by text. Use this when the person names
    something rather than giving an id."""
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
    """Everything about one task, including its history."""
    user, _ = await _caller(ctx)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            tctx = await tasks_service.context_for(db, org, uuid.UUID(task_id), user)
        except Exception as exc:
            raise Denied("No such task, or you can't see it.") from exc
        events = await tasks_service.list_events(db, tctx.task.id)
        tags = (await tags_service.for_tasks(db, [tctx.task.id])).get(tctx.task.id, [])
        t = tctx.task
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
        if events:
            lines.append("\nhistory (oldest first):")
            lines += [f"  {e.created_at:%Y-%m-%d %H:%M} {e.kind}" for e, _ in events[-20:]]
    return "\n".join(lines)


@mcp.tool()
async def activity(
    ctx: Context,
    organisation_id: str,
    days: Annotated[int, Field(ge=1, le=90, description="How far back to look.")] = 7,
    mine_only: bool = False,
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
            owner_user_id=user.id if mine_only else None,
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


# --- writing ------------------------------------------------------------------------


@mcp.tool()
async def create_task(
    ctx: Context,
    organisation_id: str,
    title: str,
    description: Annotated[str | None, Field(description="Plain text is fine.")] = None,
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
) -> str:
    """Create a task, optionally for somebody else.

    Naming a person by email rather than id, because that is what a person
    says out loud. They must already be a member of the organisation — this
    will not invite anybody.
    """
    user, tok = await _caller(ctx)
    _require_write(tok)
    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        owner = await _member_by_email(db, org, owner_email)
        acting = await _member_by_email(db, org, action_required_email)
        created = await tasks_service.create(
            db,
            org,
            user,
            title=title,
            description=description,
            project_id=uuid.UUID(project_id) if project_id else None,
            priority=priority,
            owner_user_id=owner,
            action_required_user_id=acting,
            due_on=date.fromisoformat(due_on) if due_on else None,
        )
    return f"Created [{created.id}] {created.title}"


@mcp.tool()
async def update_task(
    ctx: Context,
    organisation_id: str,
    task_id: str,
    status: str | None = None,
    priority: str | None = None,
    due_on: str | None = None,
    action_required_email: str | None = None,
) -> str:
    """Change a task. Only the fields you pass are touched."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    fields: dict = {}
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
        if not fields:
            return "Nothing to change."
        updated = await tasks_service.update(db, tctx, org, user, fields=fields)
    return f"Updated [{updated.id}] {updated.title}"


@mcp.tool()
async def comment(ctx: Context, organisation_id: str, task_id: str, body: str) -> str:
    """Add a comment to a task, as you. Everyone who can see the task sees it."""
    user, tok = await _caller(ctx)
    _require_write(tok)
    from app.services import conversations as conversations_service

    async with SessionLocal() as db:
        org = await _org(db, user, organisation_id)
        try:
            thread = await conversations_service.for_task(
                db, org, user, uuid.UUID(task_id), create=True
            )
            await conversations_service.post(db, org, thread, user, body=body)
        except Exception as exc:
            raise Denied("No such task, or you can't comment on it.") from exc
    return "Posted."


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
        tctx.require(tasks_service.can_edit(tctx.level), "you have read-only access to this task")

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
