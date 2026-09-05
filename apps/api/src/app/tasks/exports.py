"""Building a data export, and sweeping away ones that are done being
useful.

Runs in the worker because an organisation-wide export can mean hundreds of
tasks and their attachments — building that inline would risk an HTTP
timeout and hold a request open for no reason when this container exists
for exactly this shape of work. Read `services/exports.py`'s own docstring
for the two rules that govern this table: privacy (every read filters on
the requester) and autodelete (a grace window after a confirmed download,
a longer ceiling for one nobody ever downloads).
"""

import html as html_lib
import logging
import re
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Export, Project, Tag, Task, User
from app.models.export import STATUS_FAILED, STATUS_READY
from app.models.notification import KIND_EXPORT_READY
from app.services import access
from app.services import attachments as attachments_service
from app.services import checklists as checklists_service
from app.services import conversations as conversations_service
from app.services import exports as exports_service
from app.services import notifications as notifications_service
from app.services import organisations as organisations_service
from app.services import tags as tags_service
from app.services.organisations import OrgContext, slugify
from app.storage import s3
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.exports")


def _task_folder(task: Task) -> str:
    """Collision-safe without a second lookup — the same idea
    `organisations.slugify` already serves for a URL stem, plus the first 8
    characters of the task's own id, which is enough entropy that two tasks
    slugifying to the same stem still land in different folders.

    Checked *before* calling `slugify`, not after: a title of nothing but
    punctuation (`"!!!"`) has no alphanumeric character for `slugify` to
    keep either, and its own fallback for that case is `"org"` — the right
    word for a URL stem with no organisation name, the wrong one for a
    folder with no readable task title. `"untitled"` is decided here
    instead of leaking that fallback into a context it wasn't written for.
    """
    stem = slugify(task.title) if re.search(r"[a-z0-9]", task.title.lower()) else "untitled"
    return f"{stem}-{str(task.id)[:8]}"


def _description_text(html: str | None) -> str:
    """A readable, multi-line rendering of a task's description for
    `task.md` — deliberately **not** `richtext.to_plain_text()`, which
    collapses everything to one line for a search snippet and would turn a
    multi-paragraph description into a wall of text here. Scoped to this
    module only: the shared single-line contract other callers (search)
    depend on is left untouched.
    """
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<li[^>]*>", "- ", text)
    text = re.sub(r"</(p|h2|h3|li|blockquote)>|<hr\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    lines = [line.rstrip() for line in text.splitlines()]
    # Collapse runs of blank lines the tag-stripping above tends to leave.
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def _task_markdown(
    task: Task,
    *,
    project_name: str | None,
    users: dict[uuid.UUID, User],
    tags: list[Tag],
    comments: list,
    checklists: list,
) -> str:
    def who(user_id: uuid.UUID | None) -> str:
        if user_id is None:
            return "—"
        user = users.get(user_id)
        return (user.display_name or user.email) if user else "—"

    lines = [f"# {task.title}", ""]
    lines.append(f"Status: {task.status} ({'closed' if task.closed_at else 'open'})")
    lines.append(f"Priority: {task.priority}")
    lines.append(f"Owner: {who(task.owner_user_id)}")
    if task.action_required_user_id:
        lines.append(f"Action required: {who(task.action_required_user_id)}")
    lines.append(f"Project: {project_name or 'none'}")
    if tags:
        lines.append(f"Tags: {', '.join(t.name for t in tags)}")
    lines.append(f"Due: {task.due_on.isoformat() if task.due_on else 'none'}")
    lines.append(f"Created: {task.created_at.isoformat()}")
    lines.append(f"Updated: {task.updated_at.isoformat()}")
    if task.closed_at:
        lines.append(f"Closed: {task.closed_at.isoformat()} by {who(task.closed_by_user_id)}")

    description = _description_text(task.description)
    if description:
        lines += ["", "## Description", "", description]

    if checklists:
        lines += ["", "## Checklists"]
        for checklist in checklists:
            lines += ["", f"### {checklist.title}"]
            for item in checklist.items:
                box = "x" if item.done_at else " "
                lines.append(f"- [{box}] {item.text}")

    if comments:
        lines += ["", "## Comments", ""]
        for message, author in comments:
            name = (author.display_name or author.email) if author else "—"
            lines.append(f"**{name}** ({message.created_at.isoformat()}):")
            lines.append(message.body)
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _attachment_entry_name(attachment) -> str:
    """Two attachments on the same task can share a display filename (two
    people both attach `photo.jpg`) — the short id prefix is what keeps the
    zip from silently overwriting one on extract, which a `filename` alone
    can't guarantee."""
    return f"{str(attachment.id)[:8]}-{attachment.filename}"


async def _visible_tasks(
    db, ctx: OrgContext, user: User, project_id: uuid.UUID | None
) -> list[Task]:
    """Every task the requester can see, in scope — closed and off-board
    tasks included, since a "take your data" export leaving those out would
    be silently incomplete. A thin wrapper over `access.visible_tasks_stmt`
    rather than `services.tasks.list_visible`, only to pin the
    `include_closed`/`include_off_board` flags this one caller needs, which
    the ordinary task list endpoint defaults off.
    """
    rows = (
        await db.execute(
            access.visible_tasks_stmt(
                user_id=user.id,
                org_id=ctx.organisation.id,
                org_role=ctx.role,
                project_id=project_id,
                include_closed=True,
                include_off_board=True,
            )
        )
    ).all()
    return [task for task, _level in rows]


def _export_link_path(export: Export) -> str:
    """Where the Export card that started this build lives — there's no
    dedicated exports screen to deep-link into instead."""
    if export.project_id:
        return f"/orgs/{export.organisation_id}/projects/{export.project_id}"
    return f"/orgs/{export.organisation_id}/people"


@broker.task
async def build_export(export_id: str) -> None:
    eid = uuid.UUID(export_id)

    async with SessionLocal() as db:
        export = (await db.execute(select(Export).where(Export.id == eid))).scalar_one_or_none()
        if export is None:
            return
        requester = (
            await db.execute(select(User).where(User.id == export.requested_by_user_id))
        ).scalar_one_or_none()
        if requester is None:
            export.status = STATUS_FAILED
            export.error = "the requester's account no longer exists"
            await db.commit()
            return

        try:
            ctx = await organisations_service.context_for(db, export.organisation_id, requester)

            project_name = None
            if export.project_id is not None:
                project = (
                    await db.execute(select(Project).where(Project.id == export.project_id))
                ).scalar_one_or_none()
                project_name = project.name if project else None

            tasks = await _visible_tasks(db, ctx, requester, export.project_id)
            task_ids = [task.id for task in tasks]

            attachments_by_task = await attachments_service.for_tasks(db, task_ids)
            comments_by_task = await conversations_service.for_tasks(db, task_ids)
            tags_by_task = await tags_service.for_tasks(db, task_ids)

            # A task-level grant can reach further than its project's own —
            # so this resolves every project a *task* points at, not
            # "projects this caller can see," the same reasoning the task
            # screen's own breadcrumb already documents.
            referenced_project_ids = {t.project_id for t in tasks if t.project_id}
            projects_by_id: dict[uuid.UUID, str] = {}
            if referenced_project_ids:
                found_projects = (
                    await db.execute(select(Project).where(Project.id.in_(referenced_project_ids)))
                ).scalars()
                projects_by_id = {p.id: p.name for p in found_projects}

            referenced_user_ids = {
                uid
                for t in tasks
                for uid in (t.owner_user_id, t.action_required_user_id, t.closed_by_user_id)
                if uid
            }
            users_by_id: dict[uuid.UUID, User] = {}
            if referenced_user_ids:
                found_users = (
                    await db.execute(select(User).where(User.id.in_(referenced_user_ids)))
                ).scalars()
                users_by_id = {u.id: u for u in found_users}

            with tempfile.TemporaryDirectory() as tmp:
                zip_path = Path(tmp) / "export.zip"
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for task in tasks:
                        checklists = await checklists_service.for_task(db, task.id)
                        folder = _task_folder(task)
                        if export.project_id is None:
                            group = (
                                projects_by_id.get(task.project_id) if task.project_id else None
                            )
                            folder = f"{slugify(group) if group else 'no-project'}/{folder}"

                        markdown = _task_markdown(
                            task,
                            project_name=projects_by_id.get(task.project_id)
                            if task.project_id
                            else None,
                            users=users_by_id,
                            tags=tags_by_task.get(task.id, []),
                            comments=comments_by_task.get(task.id, []),
                            checklists=checklists,
                        )
                        zf.writestr(f"{folder}/task.md", markdown)

                        for attachment in attachments_by_task.get(task.id, []):
                            raw = await s3.get_object_bytes(attachment.storage_key)
                            if raw is None:
                                continue
                            zf.writestr(
                                f"{folder}/attachments/{_attachment_entry_name(attachment)}", raw
                            )

                data = zip_path.read_bytes()

            key = f"exports/{export.organisation_id}/{export.id}.zip"
            await s3.put_object_bytes(key, data, "application/zip")

            export.status = STATUS_READY
            export.storage_key = key
            export.file_size = len(data)
            export.completed_at = datetime.now(UTC)
            await db.commit()

            await notifications_service.notify(
                db,
                user_id=requester.id,
                kind=KIND_EXPORT_READY,
                title=f"Your export of {project_name or 'your organisation'} is ready",
                body="Download it from the Export card where you started it.",
                link_path=_export_link_path(export),
                organisation_id=export.organisation_id,
            )
        except Exception as exc:  # pragma: no cover - defensive, mirrors thumbnails.py
            logger.warning("export %s failed: %s", export_id, exc)
            export.status = STATUS_FAILED
            export.error = str(exc)[:2000]
            await db.commit()

            await notifications_service.notify(
                db,
                user_id=requester.id,
                kind=KIND_EXPORT_READY,
                title="Your export couldn't be built",
                body="Something went wrong while preparing it. Try again, or ask an admin.",
                link_path=_export_link_path(export),
                organisation_id=export.organisation_id,
            )


@broker.task(schedule=[{"cron": "45 * * * *"}])
async def sweep_expired_exports() -> None:
    async with SessionLocal() as db:
        keys = await exports_service.claim_expired(db)
    for key in keys:
        await s3.delete_object(key)
