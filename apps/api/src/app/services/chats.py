"""Chats: direct messages, groups, and the one list of every conversation.

A chat is a `conversations` row with no anchor (see `models/conversation.py`)
and the rest — messages, attachments, voice notes, mentions, unread cursors,
realtime — is `services/conversations.py`, unchanged. This module adds what
having no anchor needs, and the list.

Five rules:

1. **Membership is a chat's whole access rule, and an organisation admin is
   not a member of anybody's DM.** The admin route that opens every task
   stops here, the same promise a private note makes. Seeing, posting,
   watching and editing all go through `conversation_members`; nothing
   consults the org role.

2. **One DM per pair of people per organisation.** `direct_key` is the two
   ids sorted, under a unique index, so "open a chat with Sam" is
   find-or-create and two people doing it at once still end up in one
   thread. A DM with yourself is your saved messages.

3. **The chat list is your threads, not every thread you could open.** A
   task or project thread is listed when you have a `message_reads` row in
   it — you read it, wrote in it, or were given a stake (owner, asked to
   act, named). Listing every visible thread would hand an org admin the
   whole company. Every listed row still goes through the anchor's access
   expression in the same statement, so a thread you lost access to drops
   out however many rows point at it.

4. **Pinned, muted and archived are yours alone**, on your `message_reads`
   row. Archived means "out of the list until something newer arrives",
   which is checked against `last_message_at` at read time, so a new message
   brings it back without anybody rewriting your row.

5. **A chat with nothing in it is listed only for whoever started it.**
   Opening a DM to look at it must not put an empty conversation in the
   other person's list.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import and_, case, exists, func, literal, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    Conversation,
    ConversationMember,
    Message,
    MessageRead,
    OrganisationMember,
    Project,
    Task,
    User,
)
from app.models.conversation import CHAT_KINDS, KIND_DIRECT, KIND_GROUP, KIND_PROJECT, KIND_TASK
from app.models.organisation import STATUS_ACTIVE
from app.realtime import events
from app.services import access
from app.services import conversations as conversations_service
from app.services.conversations import ThreadContext
from app.services.organisations import OrgContext

FILTERS = ("all", "unread", "direct", "groups", "tasks", "projects", "archived")
MAX_GROUP = 200
MAX_TITLE = 120


def direct_key(a: uuid.UUID, b: uuid.UUID) -> str:
    """Rule 2: the pair, order-free. Two UUIDs as hex are 64 characters plus
    the colon, inside the column's 80."""
    first, second = sorted((a.hex, b.hex))
    return f"{first}:{second}"


async def _active_members(
    db: AsyncSession, ctx: OrgContext, user_ids: set[uuid.UUID]
) -> set[uuid.UUID]:
    found = (
        await db.execute(
            select(OrganisationMember.user_id).where(
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.user_id.in_(user_ids),
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalars().all()
    return set(found)


async def _require_members(db: AsyncSession, ctx: OrgContext, user_ids: set[uuid.UUID]) -> None:
    """Everybody named must be an active member of this organisation. A
    stranger reads as 404, like anything else you can't see."""
    if user_ids - await _active_members(db, ctx, user_ids):
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="person not found")


async def open_direct(
    db: AsyncSession, ctx: OrgContext, user: User, other_id: uuid.UUID
) -> Conversation:
    """Find or create the DM between you and them (rule 2)."""
    await _require_members(db, ctx, {other_id})
    key = direct_key(user.id, other_id)
    where = and_(
        Conversation.organisation_id == ctx.organisation.id, Conversation.direct_key == key
    )
    found = (await db.execute(select(Conversation).where(where))).scalar_one_or_none()
    if found is not None:
        return found

    conversation = Conversation(
        organisation_id=ctx.organisation.id,
        kind=KIND_DIRECT,
        direct_key=key,
        created_by_user_id=user.id,
    )
    db.add(conversation)
    try:
        await db.flush()
        for uid in {user.id, other_id}:
            db.add(ConversationMember(conversation_id=conversation.id, user_id=uid))
        await db.commit()
    except IntegrityError:
        # Both of you opened it at the same moment. The unique index decided.
        await db.rollback()
        return (await db.execute(select(Conversation).where(where))).scalar_one()
    await db.refresh(conversation)
    return conversation


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="give it a name"
        )
    return title[:MAX_TITLE]


async def create_group(
    db: AsyncSession, ctx: OrgContext, user: User, *, title: str, user_ids: list[uuid.UUID]
) -> Conversation:
    people = {user.id, *user_ids}
    if len(people) > MAX_GROUP:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="that's too many people"
        )
    await _require_members(db, ctx, people)
    conversation = Conversation(
        organisation_id=ctx.organisation.id,
        kind=KIND_GROUP,
        title=_clean_title(title),
        created_by_user_id=user.id,
    )
    db.add(conversation)
    await db.flush()
    for uid in people:
        db.add(ConversationMember(conversation_id=conversation.id, user_id=uid))
    await db.commit()
    await db.refresh(conversation)
    await _ping(ctx, conversation, people)
    return conversation


def _group_only(thread: ThreadContext) -> None:
    if thread.anchor_kind != KIND_GROUP:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="only a group can do that"
        )


async def rename(
    db: AsyncSession, ctx: OrgContext, thread: ThreadContext, *, title: str
) -> Conversation:
    """Any member can rename a group — it's a shared label, like Telegram."""
    _group_only(thread)
    thread.conversation.title = _clean_title(title)
    await db.commit()
    await db.refresh(thread.conversation)
    await _ping(ctx, thread.conversation, await member_ids(db, thread.conversation.id))
    return thread.conversation


async def add_members(
    db: AsyncSession, ctx: OrgContext, thread: ThreadContext, user_ids: list[uuid.UUID]
) -> None:
    """Any member can bring somebody in. They see the history: a group is a
    room, and walking into one doesn't blank the whiteboard."""
    _group_only(thread)
    existing = await member_ids(db, thread.conversation.id)
    new = set(user_ids) - existing
    if not new:
        return
    if len(existing) + len(new) > MAX_GROUP:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="that's too many people"
        )
    await _require_members(db, ctx, new)
    for uid in new:
        db.add(ConversationMember(conversation_id=thread.conversation.id, user_id=uid))
    await db.commit()
    await _ping(ctx, thread.conversation, existing | new)


async def remove_member(
    db: AsyncSession, ctx: OrgContext, thread: ThreadContext, user: User, target: uuid.UUID
) -> None:
    """Leave, or — if you started the group — remove somebody else.

    Leaving takes your `message_reads` row with it, so the group stops being
    listed for you even though your old messages stay in it.
    """
    _group_only(thread)
    if target != user.id and thread.conversation.created_by_user_id != user.id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="only whoever started the group can remove people",
        )
    before = await member_ids(db, thread.conversation.id)
    row = (
        await db.execute(
            select(ConversationMember).where(
                ConversationMember.conversation_id == thread.conversation.id,
                ConversationMember.user_id == target,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="person not found")
    await db.delete(row)
    cursor = (
        await db.execute(
            select(MessageRead).where(
                MessageRead.conversation_id == thread.conversation.id,
                MessageRead.user_id == target,
            )
        )
    ).scalar_one_or_none()
    if cursor is not None:
        await db.delete(cursor)
    await db.commit()
    await _ping(ctx, thread.conversation, before)


async def member_ids(db: AsyncSession, conversation_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        (
            await db.execute(
                select(ConversationMember.user_id).where(
                    ConversationMember.conversation_id == conversation_id
                )
            )
        ).scalars().all()
    )


async def _ping(ctx: OrgContext, conversation: Conversation, user_ids) -> None:
    """A chat changed shape (created, renamed, someone came or went). Same
    content-free event a message raises, so the same client code refetches."""
    await events.publish_message(
        conversation_id=str(conversation.id),
        message_id="",
        user_ids=[str(uid) for uid in user_ids],
        anchor={"kind": "chat", "id": str(conversation.id)},
        organisation_id=str(ctx.organisation.id),
    )


async def set_state(
    db: AsyncSession,
    conversation: Conversation,
    user: User,
    *,
    pinned: bool | None = None,
    muted: bool | None = None,
    archived: bool | None = None,
) -> MessageRead:
    """Rule 4. `None` leaves a flag as it is. Pinning a task thread you've
    never opened is also how you follow it — the row is what lists it."""
    await conversations_service.enlist(db, conversation, [user.id])
    row = (
        await db.execute(
            select(MessageRead).where(
                MessageRead.conversation_id == conversation.id, MessageRead.user_id == user.id
            )
        )
    ).scalar_one()
    if pinned is not None:
        row.pinned_at = func.now() if pinned else None
    if muted is not None:
        row.muted = muted
    if archived is not None:
        # Archiving also unpins: a pinned row hidden from the list is a
        # contradiction you'd only find by unarchiving it.
        row.archived_at = func.now() if archived else None
        if archived:
            row.pinned_at = None
    await db.commit()
    await db.refresh(row)
    return row


# --- the list -------------------------------------------------------------------


@dataclass(frozen=True)
class ChatRow:
    conversation: Conversation
    task: Task | None
    project: Project | None
    unread: int
    pinned: bool
    muted: bool
    archived: bool
    can_post: bool


def _listed_stmt(ctx: OrgContext, user: User):
    """Every conversation in your list, with your state and unread count.

    Rule 3 in one statement: chats by membership, task and project threads
    by your row **and** the anchor's own access expression — the identical
    ones the task list and the project list use, so this can't drift from
    them. `can_post` is `read` for a thread (rule 2 of conversations) and
    membership for a chat, i.e. true for every row that survives.
    """
    me = user.id
    mr = aliased(MessageRead)
    task_level = access.task_level_expression(me, ctx.role)
    project_level = access.project_level_expression(me, ctx.role)
    is_member = exists(
        select(literal(1)).where(
            ConversationMember.conversation_id == Conversation.id,
            ConversationMember.user_id == me,
        )
    )
    unread = conversations_service.unread_expression(Conversation.id, mr.last_read_at, me)
    stmt = (
        select(
            Conversation,
            Task,
            Project,
            unread.label("unread"),
            mr.pinned_at,
            mr.muted,
            mr.archived_at,
        )
        .select_from(Conversation)
        .outerjoin(mr, and_(mr.conversation_id == Conversation.id, mr.user_id == me))
        .outerjoin(Task, Task.id == Conversation.task_id)
        .outerjoin(Project, Project.id == Conversation.project_id)
        .where(
            Conversation.organisation_id == ctx.organisation.id,
            or_(
                and_(
                    Conversation.kind == KIND_TASK,
                    mr.id.isnot(None),
                    task_level > access.NO_ACCESS,
                ),
                and_(
                    Conversation.kind == KIND_PROJECT,
                    mr.id.isnot(None),
                    project_level > access.NO_ACCESS,
                ),
                and_(Conversation.kind.in_(CHAT_KINDS), is_member),
            ),
            # Rule 5, and a thread row with nothing in it lists nothing.
            or_(
                Conversation.last_message_at.isnot(None),
                and_(Conversation.kind.in_(CHAT_KINDS), Conversation.created_by_user_id == me),
            ),
        )
    )
    return stmt, mr, unread


def _matching(q: str, user: User):
    """Search: the chat's name, a member's name, or anything said in it.

    "Saved messages" is a name made up at read time, so it is matched here
    by hand — otherwise the one chat whose title you can see is the one
    searching for it can't find."""
    like = f"%{q.strip()}%"
    saved = (
        Conversation.direct_key == direct_key(user.id, user.id)
        if q.strip().lower() in "saved messages"
        else literal(False)
    )
    other = aliased(User)
    cm = aliased(ConversationMember)
    return or_(
        saved,
        Task.title.ilike(like),
        Project.name.ilike(like),
        Conversation.title.ilike(like),
        exists(
            select(literal(1))
            .select_from(cm)
            .join(other, other.id == cm.user_id)
            .where(
                cm.conversation_id == Conversation.id,
                or_(other.display_name.ilike(like), other.email.ilike(like)),
            )
        ),
        exists(
            select(literal(1)).where(
                Message.conversation_id == Conversation.id,
                Message.deleted_at.is_(None),
                Message.body.ilike(like),
            )
        ),
    )


async def list_chats(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    *,
    filter: str = "all",
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ChatRow], int]:
    """Pinned first, then newest activity. A page, and the size of the whole."""
    stmt, mr, unread = _listed_stmt(ctx, user)
    not_archived = or_(
        mr.archived_at.is_(None), Conversation.last_message_at > mr.archived_at
    )
    if filter == "archived":
        stmt = stmt.where(~not_archived)
    else:
        stmt = stmt.where(not_archived)
    if filter == "unread":
        stmt = stmt.where(unread > 0)
    elif filter == "direct":
        stmt = stmt.where(Conversation.kind == KIND_DIRECT)
    elif filter == "groups":
        stmt = stmt.where(Conversation.kind == KIND_GROUP)
    elif filter == "tasks":
        stmt = stmt.where(Conversation.kind == KIND_TASK)
    elif filter == "projects":
        stmt = stmt.where(Conversation.kind == KIND_PROJECT)
    if q and q.strip():
        stmt = stmt.where(_matching(q, user))

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(
                case((mr.pinned_at.isnot(None), 0), else_=1),
                mr.pinned_at.desc(),
                func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(),
                Conversation.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [_row(r) for r in rows], total


def _row(r) -> ChatRow:
    conversation, task, project, unread, pinned_at, muted, archived_at = r
    return ChatRow(
        conversation=conversation,
        task=task,
        project=project,
        unread=unread,
        pinned=pinned_at is not None,
        muted=bool(muted),
        archived=archived_at is not None
        and (conversation.last_message_at is None or conversation.last_message_at <= archived_at),
        can_post=True,
    )


async def one(db: AsyncSession, ctx: OrgContext, user: User, conversation_id: uuid.UUID) -> ChatRow:
    """A single chat as the list would show it — for opening one by link,
    including a task thread that isn't in your list yet (you can see it, so
    you can open it; reading it is what lists it)."""
    thread = await conversations_service.for_conversation(db, ctx, user, conversation_id)
    stmt, mr, unread = _listed_stmt(ctx, user)
    found = (
        await db.execute(stmt.where(Conversation.id == conversation_id))
    ).first()
    if found is not None:
        return _row(found)
    # Visible but not listed: an empty chat somebody else opened, or a task
    # thread you've never read. Same shape, nothing personal on it yet.
    conversation = thread.conversation
    task = project = None
    if conversation.task_id:
        task = (await db.execute(select(Task).where(Task.id == conversation.task_id))).scalar_one()
    if conversation.project_id:
        project = (
            await db.execute(select(Project).where(Project.id == conversation.project_id))
        ).scalar_one()
    return ChatRow(
        conversation=conversation,
        task=task,
        project=project,
        unread=await conversations_service.unread_count(db, conversation, user.id),
        pinned=False,
        muted=False,
        archived=False,
        can_post=thread.can_post,
    )


async def for_task_thread(
    db: AsyncSession, ctx: OrgContext, user: User, task_id: uuid.UUID
) -> Conversation:
    """The conversation behind a task's comments, created if need be — so
    "open in Chats" works on a task nobody has commented on yet."""
    thread = await conversations_service.for_task(db, ctx, user, task_id, create=True)
    return thread.conversation


async def unread_totals(db: AsyncSession, ctx: OrgContext, user: User) -> tuple[int, int]:
    """`(chats with something unread, messages unread)` across your list,
    leaving out muted chats — the number on the rail."""
    stmt, mr, unread = _listed_stmt(ctx, user)
    stmt = stmt.where(
        unread > 0,
        mr.muted.isnot(True),
        or_(mr.archived_at.is_(None), Conversation.last_message_at > mr.archived_at),
    )
    sub = stmt.subquery()
    chats, messages = (
        await db.execute(select(func.count(), func.coalesce(func.sum(sub.c.unread), 0)))
    ).one()
    return int(chats), int(messages)


async def last_messages(
    db: AsyncSession, conversation_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[Message, User | None]]:
    """The newest message in each of these, in one statement. A removed one
    counts — the preview says so rather than skipping back to an older line
    that's no longer the latest thing that happened."""
    if not conversation_ids:
        return {}
    rows = (
        await db.execute(
            select(Message, User)
            .outerjoin(User, User.id == Message.user_id)
            .where(Message.conversation_id.in_(conversation_ids))
            .distinct(Message.conversation_id)
            .order_by(Message.conversation_id, Message.id.desc())
        )
    ).all()
    return {m.conversation_id: (m, u) for m, u in rows}


async def members_of(
    db: AsyncSession, conversation_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[User]]:
    if not conversation_ids:
        return {}
    rows = (
        await db.execute(
            select(ConversationMember.conversation_id, User)
            .join(User, User.id == ConversationMember.user_id)
            .where(ConversationMember.conversation_id.in_(conversation_ids))
            .order_by(ConversationMember.created_at)
        )
    ).all()
    out: dict[uuid.UUID, list[User]] = {}
    for cid, u in rows:
        out.setdefault(cid, []).append(u)
    return out


def display_title(row: ChatRow, members: list[User], me: uuid.UUID) -> str:
    """What the list calls a chat. A DM is named after the other person at
    read time, so renaming yourself renames it everywhere at once."""
    c = row.conversation
    if c.kind == KIND_TASK and row.task is not None:
        return row.task.title
    if c.kind == KIND_PROJECT and row.project is not None:
        return row.project.name
    if c.kind == KIND_DIRECT:
        others = [u for u in members if u.id != me]
        if not others:
            return "Saved messages"
        return others[0].display_name or others[0].email or "Someone"
    return c.title or "Group"


def stamp(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
