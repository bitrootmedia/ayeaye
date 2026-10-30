"""Chats: the list of every conversation you're in, DMs and groups, and
who's online. The rules are in `services/chats.py`.

A chat is addressed by its **conversation id** whatever kind it is, so one
screen opens a DM, a group or a task's comments the same way. Each route
still resolves access through the rule that governs that kind
(`conversations.for_conversation`) — the id is never the access.
"""

import uuid

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.api.routers.conversations import (
    AttachmentIn,
    MessageIn,
    MessageOut,
    UploadTicket,
    _message_out,
    _post,
    _stage,
)
from app.models import OrganisationMember, User
from app.models.organisation import STATUS_ACTIVE
from app.schemas.structure import PersonOut
from app.services import attachments as attachments_service
from app.services import chats as chats_service
from app.services import conversations as conversations_service
from app.services import online as online_service

router = APIRouter(prefix="/organisations/{org_id}", tags=["chats"])

PREVIEW_CHARS = 200
PAGE = 50


class MemberOut(PersonOut):
    online: bool = False
    last_seen_at: str | None = None


class TaskRef(BaseModel):
    id: str
    status: str
    priority: str
    closed: bool
    project_id: str | None


class LastMessageOut(BaseModel):
    id: str
    author: PersonOut | None
    # Trimmed — a preview, not the message.
    body: str
    created_at: str
    deleted: bool
    mine: bool
    attachments: int


class ChatOut(BaseModel):
    id: str
    kind: str  # task | project | direct | group
    title: str
    task: TaskRef | None = None
    project_id: str | None = None
    # Direct and group chats only; a thread's audience is the anchor's.
    members: list[MemberOut] = []
    created_by: str | None = None
    last_message: LastMessageOut | None = None
    last_message_at: str | None
    unread: int
    pinned: bool
    muted: bool
    archived: bool
    can_post: bool


class UnreadOut(BaseModel):
    chats: int
    messages: int


class DirectIn(BaseModel):
    user_id: uuid.UUID


class GroupIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    user_ids: list[uuid.UUID] = Field(default_factory=list)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class MembersIn(BaseModel):
    user_ids: list[uuid.UUID] = Field(min_length=1)


class StateIn(BaseModel):
    pinned: bool | None = None
    muted: bool | None = None
    archived: bool | None = None


class PageOut(BaseModel):
    messages: list[MessageOut]
    can_post: bool
    unread: int
    # Whether there's anything older than the first message here.
    has_more: bool


class ReadIn(BaseModel):
    # Up to and including this message; the newest if left out.
    message_id: uuid.UUID | None = None


class PresenceOut(BaseModel):
    user_id: str
    online: bool
    last_seen_at: str | None


async def _chats_out(db, user: User, rows: list[chats_service.ChatRow]) -> list[ChatOut]:
    """A page of rows, with everything the list shows, in a fixed number of
    statements however long the page is."""
    ids = [r.conversation.id for r in rows]
    lasts = await chats_service.last_messages(db, ids)
    members = await chats_service.members_of(db, ids)
    files = await attachments_service.for_messages(db, [m.id for m, _ in lasts.values()])
    people = {u.id for us in members.values() for u in us}
    presence = await online_service.status(list(people))

    out = []
    for r in rows:
        c = r.conversation
        who = members.get(c.id, [])
        last = lasts.get(c.id)
        out.append(
            ChatOut(
                id=str(c.id),
                kind=c.kind,
                title=chats_service.display_title(r, who, user.id),
                task=(
                    TaskRef(
                        id=str(r.task.id),
                        status=r.task.status,
                        priority=r.task.priority,
                        closed=r.task.closed_at is not None,
                        project_id=str(r.task.project_id) if r.task.project_id else None,
                    )
                    if r.task is not None
                    else None
                ),
                project_id=str(c.project_id) if c.project_id else None,
                members=[
                    MemberOut(
                        id=str(u.id),
                        email=u.email,
                        display_name=u.display_name,
                        online=presence.get(u.id, (False, None))[0],
                        last_seen_at=chats_service.stamp(presence.get(u.id, (False, None))[1]),
                    )
                    for u in who
                ],
                created_by=str(c.created_by_user_id) if c.created_by_user_id else None,
                last_message=(
                    LastMessageOut(
                        id=str(last[0].id),
                        author=(
                            PersonOut(
                                id=str(last[1].id),
                                email=last[1].email,
                                display_name=last[1].display_name,
                            )
                            if last[1]
                            else None
                        ),
                        body=last[0].body[:PREVIEW_CHARS],
                        created_at=last[0].created_at.isoformat(),
                        deleted=last[0].deleted_at is not None,
                        mine=last[0].user_id == user.id,
                        attachments=len(files.get(last[0].id, [])),
                    )
                    if last
                    else None
                ),
                last_message_at=chats_service.stamp(c.last_message_at),
                unread=r.unread,
                pinned=r.pinned,
                muted=r.muted,
                archived=r.archived,
                can_post=r.can_post,
            )
        )
    return out


async def _one(db, ctx, user, conversation_id: uuid.UUID) -> ChatOut:
    row = await chats_service.one(db, ctx, user, conversation_id)
    return (await _chats_out(db, user, [row]))[0]


@router.get("/chats", response_model=list[ChatOut])
async def list_chats(
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    response: Response,
    filter: str = "all",
    q: str | None = None,
    limit: int = PAGE,
    offset: int = 0,
):
    """Your chats: pinned first, then newest. A page, with the size of the
    whole in `X-Total-Count`. An unknown filter is "all", like an unknown
    sort key elsewhere — it comes from a URL."""
    rows, total = await chats_service.list_chats(
        db,
        ctx,
        user,
        filter=filter if filter in chats_service.FILTERS else "all",
        q=q,
        limit=max(1, min(limit, 200)),
        offset=max(0, offset),
    )
    response.headers["X-Total-Count"] = str(total)
    return await _chats_out(db, user, rows)


@router.get("/chats/unread", response_model=UnreadOut)
async def unread(ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    chats, messages = await chats_service.unread_totals(db, ctx, user)
    return UnreadOut(chats=chats, messages=messages)


@router.post("/chats/direct", response_model=ChatOut)
async def open_direct(body: DirectIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Find or create your DM with somebody (yourself: saved messages)."""
    conversation = await chats_service.open_direct(db, ctx, user, body.user_id)
    return await _one(db, ctx, user, conversation.id)


@router.post("/chats/groups", response_model=ChatOut, status_code=status.HTTP_201_CREATED)
async def create_group(body: GroupIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    conversation = await chats_service.create_group(
        db, ctx, user, title=body.title, user_ids=body.user_ids
    )
    return await _one(db, ctx, user, conversation.id)


@router.post("/tasks/{task_id}/chat", response_model=ChatOut)
async def task_chat(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """The chat behind a task's comments — "open in Chats" from a task."""
    conversation = await chats_service.for_task_thread(db, ctx, user, task_id)
    return await _one(db, ctx, user, conversation.id)


@router.get("/chats/{conversation_id}", response_model=ChatOut)
async def get_chat(conversation_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    return await _one(db, ctx, user, conversation_id)


@router.patch("/chats/{conversation_id}", response_model=ChatOut)
async def rename_chat(
    conversation_id: uuid.UUID, body: RenameIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    thread = await conversations_service.for_conversation(db, ctx, user, conversation_id)
    await chats_service.rename(db, ctx, thread, title=body.title)
    return await _one(db, ctx, user, conversation_id)


@router.post("/chats/{conversation_id}/members", response_model=ChatOut)
async def add_members(
    conversation_id: uuid.UUID, body: MembersIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    thread = await conversations_service.for_conversation(db, ctx, user, conversation_id)
    await chats_service.add_members(db, ctx, thread, body.user_ids)
    return await _one(db, ctx, user, conversation_id)


@router.delete(
    "/chats/{conversation_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """Leave (your own id) or remove somebody. 204 with no body: leaving
    loses you the chat, and re-reading it to build a response would 404 on a
    change that already succeeded — the project hand-over lesson."""
    thread = await conversations_service.for_conversation(db, ctx, user, conversation_id)
    await chats_service.remove_member(db, ctx, thread, user, user_id)


@router.put("/chats/{conversation_id}/state", response_model=ChatOut)
async def set_state(
    conversation_id: uuid.UUID, body: StateIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    thread = await conversations_service.for_conversation(db, ctx, user, conversation_id)
    await chats_service.set_state(
        db,
        thread.conversation,
        user,
        pinned=body.pinned,
        muted=body.muted,
        archived=body.archived,
    )
    return await _one(db, ctx, user, conversation_id)


@router.get("/chats/{conversation_id}/messages", response_model=PageOut)
async def messages(
    conversation_id: uuid.UUID,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    before: uuid.UUID | None = None,
    limit: int = PAGE,
):
    """The newest page, or the page before `before`, oldest first within it.

    Reading the newest page doesn't mark anything read on its own — a chat
    window decides that (`POST .../read`) once the messages are actually on
    screen, which a background tab's refetch is not.
    """
    thread = await conversations_service.for_conversation(db, ctx, user, conversation_id)
    limit = max(1, min(limit, 200))
    rows = await conversations_service.list_messages(
        db, thread.conversation, before=before, limit=limit + 1
    )
    has_more = len(rows) > limit
    rows = rows[-limit:]
    files = await attachments_service.for_messages(db, [m.id for m, _ in rows])
    quotes = await conversations_service.replied_to(db, [m.reply_to_message_id for m, _ in rows])
    return PageOut(
        messages=[
            _message_out(
                m, a, me=user.id, files=files.get(m.id), quoted=quotes.get(m.reply_to_message_id)
            )
            for m, a in rows
        ],
        can_post=thread.can_post,
        unread=await conversations_service.unread_count(db, thread.conversation, user.id),
        has_more=has_more,
    )


@router.post(
    "/chats/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def send(
    conversation_id: uuid.UUID, body: MessageIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Post into any chat — including a task's thread, where it is exactly a
    comment. `action_required_user_id` is a task screen's affordance and is
    ignored here; change it from the task."""
    thread = await conversations_service.for_conversation(db, ctx, user, conversation_id)
    return await _post(db, ctx, thread, user, body)


@router.post("/chats/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    conversation_id: uuid.UUID, body: ReadIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    thread = await conversations_service.for_conversation(db, ctx, user, conversation_id)
    upto = None
    if body.message_id is not None:
        message = await conversations_service.get_message(db, thread.conversation, body.message_id)
        upto = message.created_at
    await conversations_service.mark_read(db, thread.conversation, user, upto=upto)


@router.post(
    "/chats/{conversation_id}/attachments",
    response_model=UploadTicket,
    status_code=status.HTTP_201_CREATED,
)
async def stage_attachment(
    conversation_id: uuid.UUID,
    body: AttachmentIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """Step 1 of the upload handshake, for any chat. Steps 2 and 3 are the
    same as a comment's: PUT to storage, then `/attachments/{id}/confirm`."""
    thread = await conversations_service.for_conversation(db, ctx, user, conversation_id)
    return await _stage(db, thread, user, body)


@router.get("/presence", response_model=list[PresenceOut])
async def presence(ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Who in this organisation is online now, and when everyone else was
    last seen. Membership is the whole rule, like the People list."""
    del user
    ids = (
        await db.execute(
            select(OrganisationMember.user_id).where(
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalars().all()
    status_by = await online_service.status(list(ids))
    return [
        PresenceOut(
            user_id=str(uid),
            online=status_by[uid][0],
            last_seen_at=chats_service.stamp(status_by[uid][1]),
        )
        for uid in ids
    ]
