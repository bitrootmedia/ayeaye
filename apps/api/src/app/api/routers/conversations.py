"""Comment threads, and the socket that keeps them live."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from supertokens_python.recipe.session.asyncio import get_session_without_request_response

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.db import SessionLocal
from app.models import Message, User
from app.realtime.connections import manager
from app.schemas.structure import PersonOut
from app.services import attachments as attachments_service
from app.services import conversations as conversations_service
from app.services import users as users_service

logger = logging.getLogger("app.api.conversations")

router = APIRouter(prefix="/organisations/{org_id}", tags=["conversations"])
ws_router = APIRouter(tags=["realtime"])


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    # Staged uploads to bind to this comment. They already exist (confirmed in
    # step 3 of the handshake); sending is what gives them a home.
    attachment_ids: list[str] = Field(default_factory=list)


class AttachmentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    # None until the worker has made one, or for anything that isn't an image.
    thumbnail_url: str | None = None
    # Minted fresh at read time — a presigned URL expires, so a stored one is a
    # dead link waiting to happen.
    url: str


class UploadTicket(BaseModel):
    attachment: AttachmentOut
    # PUT the bytes here, with exactly this Content-Type: SigV4 covers the
    # header byte for byte.
    upload_url: str
    content_type: str


class MessageOut(BaseModel):
    id: str
    author: PersonOut | None
    body: str
    attachments: list[AttachmentOut] = []
    created_at: str
    edited_at: str | None
    # Soft-deleted. The row stays so the thread still reads in order; the UI
    # shows a tombstone rather than a hole.
    deleted: bool
    mine: bool


class AttachmentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    # The browser reports `audio/webm;codecs=opus`; the server normalises to
    # the bare type and signs THAT, so the client must send back exactly what
    # comes home in `content_type`.
    content_type: str = Field(min_length=1, max_length=120)


class ThreadOut(BaseModel):
    messages: list[MessageOut]
    # Resolved server-side. The UI hides the composer rather than showing one
    # that 403s.
    can_post: bool
    unread: int


def _attachment_out(attachment) -> AttachmentOut:
    return AttachmentOut(
        id=str(attachment.id),
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        url=attachments_service.view_url(attachment),
        thumbnail_url=attachments_service.thumbnail_url(attachment),
    )


def _message_out(
    message: Message, author: User | None, *, me: uuid.UUID, files: list | None = None
) -> MessageOut:
    return MessageOut(
        id=str(message.id),
        attachments=[_attachment_out(a) for a in (files or [])],
        author=(
            PersonOut(id=str(author.id), email=author.email, display_name=author.display_name)
            if author
            else None
        ),
        body=message.body,
        created_at=message.created_at.isoformat(),
        edited_at=message.edited_at.isoformat() if message.edited_at else None,
        deleted=message.deleted_at is not None,
        mine=message.user_id == me,
    )


async def _thread(db, ctx, user, *, task_id=None, project_id=None, create=False):
    if task_id is not None:
        return await conversations_service.for_task(db, ctx, user, task_id, create=create)
    return await conversations_service.for_project(db, ctx, user, project_id, create=create)


async def _thread_out(db, thread, user) -> ThreadOut:
    rows = await conversations_service.list_messages(db, thread.conversation)
    # One query for the whole thread's attachments, not one per comment.
    files = await attachments_service.for_messages(db, [m.id for m, _ in rows])
    return ThreadOut(
        messages=[
            _message_out(m, a, me=user.id, files=files.get(m.id)) for m, a in rows
        ],
        can_post=thread.can_post,
        unread=await conversations_service.unread_count(db, thread.conversation, user.id),
    )


# --- tasks ---------------------------------------------------------------------


@router.get("/tasks/{task_id}/comments", response_model=ThreadOut)
async def task_comments(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """The comment thread on a task.

    404s exactly when the task does — a thread has no visibility of its own.
    Reading it marks it read, because a thread you are looking at is a thread
    you have seen.
    """
    thread = await _thread(db, ctx, user, task_id=task_id)
    out = await _thread_out(db, thread, user)
    await conversations_service.mark_read(db, thread.conversation, user)
    return out


@router.post(
    "/tasks/{task_id}/comments", response_model=MessageOut, status_code=status.HTTP_201_CREATED
)
async def comment_on_task(
    task_id: uuid.UUID, body: MessageIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    thread = await _thread(db, ctx, user, task_id=task_id, create=True)
    return await _post(db, ctx, thread, user, body)


# --- projects ---------------------------------------------------------------------


@router.get("/projects/{project_id}/comments", response_model=ThreadOut)
async def project_comments(
    project_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    thread = await _thread(db, ctx, user, project_id=project_id)
    out = await _thread_out(db, thread, user)
    await conversations_service.mark_read(db, thread.conversation, user)
    return out


@router.post(
    "/projects/{project_id}/comments",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def comment_on_project(
    project_id: uuid.UUID, body: MessageIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    thread = await _thread(db, ctx, user, project_id=project_id, create=True)
    return await _post(db, ctx, thread, user, body)


async def _post(db, ctx, thread, user, body: MessageIn) -> MessageOut:
    message = await conversations_service.post(db, ctx, thread, user, body=body.body)
    files = await attachments_service.bind_to_message(
        db,
        thread.conversation,
        message,
        user,
        [uuid.UUID(i) for i in body.attachment_ids],
    )
    return _message_out(message, user, me=user.id, files=files)


# --- attachments: the three-step handshake ----------------------------------


@router.post(
    "/tasks/{task_id}/attachments",
    response_model=UploadTicket,
    status_code=status.HTTP_201_CREATED,
)
async def stage_task_attachment(
    task_id: uuid.UUID,
    body: AttachmentIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """Step 1 for a task thread: a ticket to upload one file.

    The bytes then go browser → storage directly and never touch the API. Come
    back to `/attachments/{id}/confirm` afterwards — that is the only point at
    which what really landed can be checked.
    """
    thread = await _thread(db, ctx, user, task_id=task_id, create=True)
    return await _stage(db, thread, user, body)


@router.post(
    "/projects/{project_id}/attachments",
    response_model=UploadTicket,
    status_code=status.HTTP_201_CREATED,
)
async def stage_project_attachment(
    project_id: uuid.UUID,
    body: AttachmentIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    thread = await _thread(db, ctx, user, project_id=project_id, create=True)
    return await _stage(db, thread, user, body)


async def _stage(db, thread, user, body: "AttachmentIn") -> UploadTicket:
    if not thread.can_post:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="you can't comment on this"
        )
    attachment, upload_url = await attachments_service.create(
        db,
        user,
        conversation=thread.conversation,
        filename=body.filename,
        content_type=body.content_type,
    )
    return UploadTicket(
        attachment=AttachmentOut(
            id=str(attachment.id),
            filename=attachment.filename,
            content_type=attachment.content_type,
            size_bytes=0,
            url="",
            thumbnail_url=None,
        ),
        upload_url=upload_url,
        content_type=attachment.content_type,
    )


@router.post("/attachments/{attachment_id}/confirm", response_model=AttachmentOut)
async def confirm_attachment(
    attachment_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Step 3. HEADs the object, enforces the size limit against the real
    bytes, and makes the attachment usable."""
    from sqlalchemy import select

    from app.models import Attachment

    attachment = (
        await db.execute(select(Attachment).where(Attachment.id == attachment_id))
    ).scalar_one_or_none()
    if attachment is None:
        raise _not_found()

    # Re-check the anchor rather than trusting the id: holding an attachment id
    # must never be access. Both kinds route back through the same visibility
    # rules as everything else.
    await _anchor_of(db, ctx, user, attachment)
    return _attachment_out(await attachments_service.confirm(db, attachment, user))


async def _anchor_of(db, ctx, user, attachment):
    """Resolve and access-check whatever this attachment hangs off."""
    from app.models import Conversation
    from app.services import tasks as tasks_service


    if attachment.task_id is not None:
        return await tasks_service.context_for(db, ctx, attachment.task_id, user)
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == attachment.conversation_id,
                Conversation.organisation_id == ctx.organisation.id,
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise _not_found()
    return await _thread(
        db, ctx, user, task_id=conversation.task_id, project_id=conversation.project_id
    )


# --- editing your own -------------------------------------------------------------


@router.patch("/comments/{message_id}", response_model=MessageOut)
async def edit_comment(
    message_id: uuid.UUID,
    body: MessageIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    message, thread = await _own_message(db, ctx, user, message_id)
    updated = await conversations_service.edit(db, ctx, message, user, body=body.body)
    del thread
    return _message_out(updated, user, me=user.id)


@router.delete("/comments/{message_id}", response_model=MessageOut)
async def delete_comment(
    message_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Soft delete — the response is the tombstone, not a 204, so the client
    can render it in place without refetching the thread."""
    message, thread = await _own_message(db, ctx, user, message_id)
    removed = await conversations_service.remove(db, ctx, message, user)
    del thread
    return _message_out(removed, user, me=user.id)


async def _own_message(db, ctx, user, message_id: uuid.UUID):
    """Find a message, re-checking access to its anchor.

    Going back through the anchor rather than trusting the message id is the
    point: otherwise anyone with a comment id could edit it, and ids leak.
    """
    from app.models import Conversation

    row = (
        await db.execute(
            select(Message, Conversation)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.id == message_id, Conversation.organisation_id == ctx.organisation.id)
        )
    ).first()
    if row is None:
        raise _not_found()
    message, conversation = row
    thread = await _thread(
        db,
        ctx,
        user,
        task_id=conversation.task_id,
        project_id=conversation.project_id,
    )
    return message, thread


async def _handle_watch(ws: WebSocket, raw: str, user_id: str) -> None:
    """Register interest in one thread, **after checking access to it**.

    Verified here rather than at dispatch time so the check happens once per
    thread opened, not once per message per socket. Safe because the event
    carries no content: if access is revoked in between, the refetch it
    triggers 404s, which is the right answer.
    """
    import json

    try:
        payload = json.loads(raw)
        target = payload.get("watch")
        if not target:
            return
        kind, anchor_id = target["kind"], uuid.UUID(target["id"])
    except Exception:
        return
    if kind not in ("task", "project"):
        return

    async with SessionLocal() as db:
        user = await users_service.get_or_create_by_local_id(db, uuid.UUID(user_id))
        if user is None:
            return
        try:
            if kind == "task":
                await _visible_task(db, user, anchor_id)
            else:
                await _visible_project(db, user, anchor_id)
        except Exception:
            # No access, or it's gone. Silently ignored: telling a socket
            # which ids exist is exactly the leak 404-not-403 avoids.
            return

    manager.watch(f"{kind}:{anchor_id}", ws)


async def _visible_task(db, user, task_id: uuid.UUID):
    """Access check for a task, resolved from the task's own organisation.

    The socket has no organisation in its path, so the membership has to be
    looked up from the anchor rather than handed in.
    """
    from sqlalchemy import select

    from app.models import Task
    from app.services import organisations as orgs_service
    from app.services import tasks as tasks_service

    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
    ctx = await orgs_service.context_for(db, task.organisation_id, user)
    return await tasks_service.context_for(db, ctx, task_id, user)


async def _visible_project(db, user, project_id: uuid.UUID):
    from sqlalchemy import select

    from app.models import Project
    from app.services import organisations as orgs_service
    from app.services import projects as projects_service

    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one()
    ctx = await orgs_service.context_for(db, project.organisation_id, user)
    return await projects_service.context_for(db, ctx, project_id, user.id)


def _not_found():
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="comment not found")


# --- the socket ---------------------------------------------------------------------


@ws_router.websocket("/ws")
async def realtime(ws: WebSocket):
    """Live updates.

    **Authenticated by the session cookie**, which single-origin buys us for
    free: the SPA, the API and this socket share a host, so the browser sends
    the cookie with the upgrade request. The reference project had to pass an
    access token as a query parameter — where it lands in server logs and
    browser history — precisely because its apps were on other origins.

    The socket is a notification channel and nothing more. It never carries
    message bodies; the client refetches over HTTP, so there is one
    authorisation path for content rather than two.
    """
    token = ws.cookies.get("sAccessToken")
    if not token:
        await ws.close(code=4401)
        return
    try:
        session = await get_session_without_request_response(token)
        if session is None:
            raise ValueError("no session")
        supertokens_id = session.get_user_id()
    except Exception:
        await ws.close(code=4401)
        return

    # Map to our own user id — that is what everything else keys on, and what
    # the publisher puts in `user_ids`.
    async with SessionLocal() as db:
        user = await users_service.get_or_create(db, supertokens_user_id=supertokens_id)
        user_id = str(user.id)

    await manager.connect(user_id, ws)
    try:
        while True:
            # The client sends `{"watch": {"kind": "task", "id": "…"}}` when it
            # opens a thread. That is what lets someone reading along get live
            # updates without having a *stake* worth notifying them about —
            # the two audiences are different and used to be conflated.
            raw = await ws.receive_text()
            await _handle_watch(ws, raw, user_id)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - transport-level noise
        logger.info("socket closed: %s", exc)
    finally:
        manager.disconnect(user_id, ws)
