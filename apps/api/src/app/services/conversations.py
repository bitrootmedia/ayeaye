"""Comment threads on tasks and projects, and the chats that share their
machinery.

Direct and group chats (`services/chats.py`) are the same conversations with
no anchor: everything below holds for them too, with **membership** standing
in for "who can see the anchor" in rule 1 and as the audience in rule 4. Two
differences are deliberate: an organisation admin cannot edit or remove
somebody else's words in a chat (they cannot even see it), and a muted thread
raises nothing but mentions.

Four rules:

1. **A thread has no access rules of its own.** Who can see it is who can see
   its anchor — the task or the project it hangs off. One rule rather than two,
   and revoking access to a task revokes its discussion with it.

2. **`read` is enough to post.** A comment is a contribution, not a change to
   the work. The commonest reason to share something read-only is to get
   somebody's input, and a viewer who can't say "this is blocked on the survey"
   is a viewer who emails you instead. Editing and deleting stay with the
   author (or an organisation admin).

3. **A thread is created on first use**, not when the task is. Most tasks never
   get a comment, and a row per task that nobody ever writes to is a row per
   task to migrate later.

4. **One notification per unread run.** A new comment raises a notification
   only when the recipient has nothing unread in that thread already —
   otherwise a back-and-forth is one notification and one email per line, which
   is how an inbox becomes something nobody reads.

5. **Naming somebody is the one thing that skips rule 4.** An `@mention` is a
   direct address, and "you already have unread messages in that thread" is
   exactly the case where they still need telling — it is why the author typed
   a name rather than just posting. Its own kind (`KIND_COMMENT_MENTION`), and
   never a second notification on top of the ordinary one: whoever is named
   gets the mention instead. Who *can* be named is who can see the anchor,
   resolved in `services/mentions.py`.

Who gets notified is deliberately **not** "everyone who can see it": org admins
can see everything, and drowning them is not a feature. It is the people with
a stake — the task's owner, whoever is being asked to act, and anyone who has
already spoken in the thread — minus the author.
"""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    ConversationMember,
    Message,
    MessageRead,
    Project,
    Task,
    User,
)
from app.models.conversation import (
    CHAT_KINDS,
    KIND_DIRECT,
    KIND_GROUP,
    KIND_PROJECT,
    KIND_TASK,
)
from app.models.notification import (
    KIND_COMMENT_MENTION,
    KIND_DIRECT_MESSAGE,
    KIND_TASK_SHARED,
)
from app.realtime import events
from app.services import access
from app.services import mentions as mentions_service
from app.services import notifications as notifications_service
from app.services import projects as projects_service
from app.services import tasks as tasks_service
from app.services.organisations import OrgContext

MAX_BODY = 10_000


@dataclass(frozen=True)
class ThreadContext:
    """A conversation plus what the caller may do with it."""

    conversation: Conversation
    # The anchor's title, for notification text and the UI header.
    anchor_title: str
    anchor_kind: str  # "task" | "project" | "direct" | "group"
    can_post: bool

    @property
    def is_chat(self) -> bool:
        return self.anchor_kind in CHAT_KINDS


def _clean(body: str, *, allow_empty: bool = False) -> str:
    body = (body or "").strip()
    if not body and allow_empty:
        return ""
    if not body:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="say something"
        )
    if len(body) > MAX_BODY:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="that comment is too long",
        )
    return body


async def for_task(
    db: AsyncSession, ctx: OrgContext, user: User, task_id: uuid.UUID, *, create: bool = False
) -> ThreadContext:
    """The thread on a task. 404s exactly when the task does."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    conversation = await _find_or_create(
        db, ctx, create=create, task_id=task_id, project_id=None
    )
    return ThreadContext(
        conversation=conversation,
        anchor_title=tctx.task.title,
        anchor_kind="task",
        # Rule 2: seeing it is enough to say something about it.
        can_post=access.can_read(tctx.level),
    )


async def for_project(
    db: AsyncSession, ctx: OrgContext, user: User, project_id: uuid.UUID, *, create: bool = False
) -> ThreadContext:
    pctx = await projects_service.context_for(db, ctx, project_id, user.id)
    conversation = await _find_or_create(
        db, ctx, create=create, task_id=None, project_id=project_id
    )
    return ThreadContext(
        conversation=conversation,
        anchor_title=pctx.project.name,
        anchor_kind="project",
        can_post=access.can_read(pctx.level),
    )


async def for_chat(
    db: AsyncSession, ctx: OrgContext, user: User, conversation: Conversation
) -> ThreadContext:
    """A direct or group chat. 404s unless you are in it — **an organisation
    admin included**, which is the one place their see-everything route
    stops. The 404 rather than a 403 is the usual rule: whether a DM exists
    between two other people is itself not yours to learn."""
    member = (
        await db.execute(
            select(ConversationMember.id).where(
                ConversationMember.conversation_id == conversation.id,
                ConversationMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if member is None or conversation.organisation_id != ctx.organisation.id:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="chat not found")
    return ThreadContext(
        conversation=conversation,
        anchor_title=conversation.title or "",
        anchor_kind=conversation.kind,
        can_post=True,
    )


async def for_conversation(
    db: AsyncSession, ctx: OrgContext, user: User, conversation_id: uuid.UUID
) -> ThreadContext:
    """Any conversation by its own id, through whichever rule governs it.

    The id is never the access: a task thread goes back through the task, a
    chat through its members, exactly as if it had been reached by its anchor.
    """
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.organisation_id == ctx.organisation.id,
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="chat not found")
    if conversation.kind in CHAT_KINDS:
        return await for_chat(db, ctx, user, conversation)
    if conversation.task_id is not None:
        return await for_task(db, ctx, user, conversation.task_id)
    return await for_project(db, ctx, user, conversation.project_id)


async def _find_or_create(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    create: bool,
    task_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
) -> Conversation:
    """Rule 3: created lazily, on the first comment.

    The `IntegrityError` branch is the real case, not a defensive one: two
    people opening a task and commenting at the same moment both find nothing
    and both insert. The partial unique index decides, and the loser re-reads.
    """
    where = Conversation.task_id == task_id if task_id else Conversation.project_id == project_id
    found = (await db.execute(select(Conversation).where(where))).scalar_one_or_none()
    if found is not None or not create:
        return found  # type: ignore[return-value]

    conversation = Conversation(
        organisation_id=ctx.organisation.id,
        task_id=task_id,
        project_id=project_id,
        kind=KIND_TASK if task_id else KIND_PROJECT,
    )
    db.add(conversation)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return (await db.execute(select(Conversation).where(where))).scalar_one()
    await db.refresh(conversation)
    return conversation


async def list_messages(
    db: AsyncSession,
    conversation: Conversation | None,
    *,
    before: uuid.UUID | None = None,
    limit: int | None = None,
) -> list[tuple[Message, User | None]]:
    """Oldest first — a conversation reads as a conversation, not a feed.

    With `limit`, the newest `limit` messages older than `before` (still
    returned oldest first): a chat opens at the bottom and pages upwards.
    Without it, the whole thread, which is what a task's comments have always
    been. UUIDv7 ids sort by time, so `before` is a message id, not a date.
    """
    if conversation is None:
        return []
    stmt = (
        select(Message, User)
        .outerjoin(User, User.id == Message.user_id)
        .where(Message.conversation_id == conversation.id)
    )
    if before is not None:
        stmt = stmt.where(Message.id < before)
    if limit is None:
        rows = (await db.execute(stmt.order_by(Message.id))).all()
    else:
        newest = await db.execute(stmt.order_by(Message.id.desc()).limit(limit))
        rows = list(reversed(newest.all()))
    return [(m, u) for m, u in rows]


async def replied_to(
    db: AsyncSession, message_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[Message, User | None]]:
    """The messages these quote, with their authors — one statement for a
    page of replies, not one per bubble."""
    ids = [i for i in message_ids if i is not None]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Message, User)
            .outerjoin(User, User.id == Message.user_id)
            .where(Message.id.in_(ids))
        )
    ).all()
    return {m.id: (m, u) for m, u in rows}


async def for_tasks(
    db: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[Message, User | None]]]:
    """Every comment across many tasks' threads, in one statement — oldest
    first within each. The batched-by-ids sibling `list_messages` doesn't
    need: built for the data export, which would otherwise open one
    conversation's thread at a time across however many tasks are in scope.

    Removed comments are left out entirely rather than shown as a tombstone
    — `remove()` already clears the body to "", so there is nothing of the
    person's own words left to export.
    """
    if not task_ids:
        return {}
    rows = (
        await db.execute(
            select(Conversation.task_id, Message, User)
            .join(Message, Message.conversation_id == Conversation.id)
            .outerjoin(User, User.id == Message.user_id)
            .where(Conversation.task_id.in_(task_ids), Message.deleted_at.is_(None))
            .order_by(Conversation.task_id, Message.id)
        )
    ).all()
    grouped: dict[uuid.UUID, list[tuple[Message, User | None]]] = {}
    for task_id, message, user in rows:
        grouped.setdefault(task_id, []).append((message, user))
    return grouped


async def post(
    db: AsyncSession,
    ctx: OrgContext,
    thread: ThreadContext,
    user: User,
    *,
    body: str,
    via: str | None = None,
    reply_to: uuid.UUID | None = None,
    allow_empty: bool = False,
) -> Message:
    """`via` names whatever acted on the author's behalf — a personal access
    token or an OAuth client, by the name its owner gave it. It is
    attribution, not authorship: `user_id` is still whose comment this is.
    Defaults to None, which is what the web app sends and what every row
    written before this existed holds.

    `allow_empty` is for a message that is only files — a photo with no
    caption. The caller must already have checked there are files to bind;
    an empty body with nothing attached is still "say something"."""
    if not thread.can_post:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="you can't comment on this",
        )
    if reply_to is not None:
        # Quoting is only within the same thread: a reply pointing into a
        # conversation you can't see would render somebody else's words.
        quoted = (
            await db.execute(
                select(Message.id).where(
                    Message.id == reply_to, Message.conversation_id == thread.conversation.id
                )
            )
        ).scalar_one_or_none()
        if quoted is None:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="that message isn't in this conversation",
            )
    message = Message(
        conversation_id=thread.conversation.id,
        user_id=user.id,
        body=_clean(body, allow_empty=allow_empty),
        via=via,
        reply_to_message_id=reply_to,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    await db.execute(
        update(Conversation)
        .where(Conversation.id == thread.conversation.id)
        .values(last_message_at=message.created_at)
    )
    await db.commit()
    await db.refresh(message)

    # Your own comment is read by definition — otherwise posting would leave
    # you with an unread badge for something you just wrote.
    await mark_read(db, thread.conversation, user, upto=message.created_at)

    recipients = await _interested(db, thread, exclude=user.id)
    mentioned = await _mentioned(db, ctx, thread, message.body, exclude=user.id)
    # Everyone with a stake now has the thread in their chat list, read or
    # not — that is how a comment on your task reaches you there.
    await enlist(db, thread.conversation, [*recipients, *mentioned])
    await _announce(db, ctx, thread, message, user, recipients, mentioned)
    return message


async def enlist(db: AsyncSession, conversation: Conversation, user_ids) -> None:
    """Put this thread in these people's chat lists, without touching how far
    they've read. Idempotent, and it un-archives nothing: an archived thread
    comes back by having something newer than its `archived_at`, which the
    list checks, not by having its row rewritten here."""
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return
    await db.execute(
        pg_insert(MessageRead)
        .values([{"conversation_id": conversation.id, "user_id": uid} for uid in ids])
        .on_conflict_do_nothing(constraint="uq_message_reads")
    )
    await db.commit()


async def _candidates(
    db: AsyncSession, ctx: OrgContext, thread: ThreadContext
) -> list[mentions_service.Mentionable]:
    """Who could be named in this thread: everyone who can see its anchor.

    Task threads only. A project thread has no candidate builder and its
    composer offers no names either, so the affordance is absent rather than
    present and silently doing nothing — `services/mentions.py` says what the
    sibling function would be.

    Fetched once even where it's used twice (an edit compares the old body
    against the new), because it is four queries rather than one.

    A chat's candidates are its members — the same "who can see it" answer.
    """
    if thread.is_chat:
        rows = (
            await db.execute(
                select(User)
                .join(ConversationMember, ConversationMember.user_id == User.id)
                .where(ConversationMember.conversation_id == thread.conversation.id)
            )
        ).scalars().all()
        return [mentions_service.Mentionable(user=u, level="read") for u in rows]
    if thread.conversation.task_id is None:
        return []
    task = (
        await db.execute(select(Task).where(Task.id == thread.conversation.task_id))
    ).scalar_one_or_none()
    if task is None:
        return []
    return await mentions_service.for_task(db, ctx.organisation.id, task)


async def _mentioned(
    db: AsyncSession,
    ctx: OrgContext,
    thread: ThreadContext,
    body: str,
    *,
    exclude: uuid.UUID,
) -> list[uuid.UUID]:
    """Who this comment names, minus its author."""
    candidates = await _candidates(db, ctx, thread)
    return mentions_service.resolve(body, candidates, exclude=exclude)


async def _interested(
    db: AsyncSession, thread: ThreadContext, *, exclude: uuid.UUID | None
) -> list[uuid.UUID]:
    """Who has a stake in this thread.

    The task's owner, whoever is being asked to act on it, and anyone who has
    already spoken. **Not** everyone who could see it: organisation admins can
    see everything, and a product that mails them every comment in the company
    is one where they turn notifications off.
    """
    people: set[uuid.UUID] = set()

    if thread.is_chat:
        # A chat's stake-holders are simply its members.
        people.update(
            (
                await db.execute(
                    select(ConversationMember.user_id).where(
                        ConversationMember.conversation_id == thread.conversation.id
                    )
                )
            ).scalars().all()
        )
    elif thread.conversation.task_id is not None:
        task = (
            await db.execute(select(Task).where(Task.id == thread.conversation.task_id))
        ).scalar_one_or_none()
        if task is not None:
            people.add(task.owner_user_id)
            if task.action_required_user_id:
                people.add(task.action_required_user_id)
    elif thread.conversation.project_id is not None:
        project = (
            await db.execute(select(Project).where(Project.id == thread.conversation.project_id))
        ).scalar_one_or_none()
        if project is not None:
            people.add(project.owner_user_id)

    speakers = (
        (
            await db.execute(
                select(Message.user_id)
                .where(
                    Message.conversation_id == thread.conversation.id,
                    Message.user_id.isnot(None),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    people.update(speakers)
    people.discard(exclude)
    return list(people)


def _link(ctx: OrgContext, thread: ThreadContext) -> str:
    """Where a notification about this thread points: the anchor's own
    screen. A thread has no page of its own, which is the whole of rule 1 —
    except a chat, whose page is the chat."""
    if thread.is_chat:
        return f"/orgs/{ctx.organisation.id}/chats/{thread.conversation.id}"
    if thread.conversation.task_id:
        return f"/orgs/{ctx.organisation.id}/tasks/{thread.conversation.task_id}"
    return f"/orgs/{ctx.organisation.id}/projects/{thread.conversation.project_id}"


async def _announce(
    db: AsyncSession,
    ctx: OrgContext,
    thread: ThreadContext,
    message: Message,
    author: User,
    recipients: list[uuid.UUID],
    mentioned: list[uuid.UUID] | None = None,
) -> None:
    """Push it live, and notify whoever isn't already behind.

    `mentioned` is rule 5: those people hear about it regardless of what they
    already have unread, and are not also told the ordinary way.
    """
    mentioned = mentioned or []
    link = _link(ctx, thread)

    # A comment is activity on the task, so it counts as the task changing:
    # `updated_at` is "last activity", and the list view sorts by it. Done
    # before the message event so a client refetching either way sees the new
    # stamp. Project threads have no task to touch.
    if thread.conversation.task_id:
        from sqlalchemy import select as _select

        from app.models import Task as _Task
        from app.services import tasks as tasks_service

        task = (
            await db.execute(_select(_Task).where(_Task.id == thread.conversation.task_id))
        ).scalar_one_or_none()
        if task is not None:
            await tasks_service.announce(db, task, "commented")

    # Live first: everyone with the thread open sees it appear, including the
    # author's other tabs.
    await events.publish_message(
        conversation_id=str(thread.conversation.id),
        message_id=str(message.id),
        # Anyone named is on this list too: they may have the thread open
        # already, and an event they never receive is a screen that only
        # moves on its next refetch.
        user_ids=[str(uid) for uid in {*recipients, *mentioned, author.id}],
        anchor=_anchor(thread),
        organisation_id=str(ctx.organisation.id),
    )

    who = author.display_name or author.email or "Someone"
    muted = set(
        (
            await db.execute(
                select(MessageRead.user_id).where(
                    MessageRead.conversation_id == thread.conversation.id,
                    MessageRead.muted.is_(True),
                )
            )
        ).scalars().all()
    )
    where = f"“{thread.anchor_title}”" if thread.anchor_title else "a chat"

    # Rule 5, and it runs first so the loop below can skip these people: one
    # comment naming the task's owner is one notification, the specific one.
    for recipient in mentioned:
        await notifications_service.notify(
            db,
            user_id=recipient,
            kind=KIND_COMMENT_MENTION,
            title=f"{who} mentioned you in {where}",
            link_path=link,
            organisation_id=ctx.organisation.id,
        )

    for recipient in recipients:
        # A mute silences everything but being named.
        if recipient in mentioned or recipient in muted:
            continue
        # Rule 4. Two unread messages in one thread is one notification; the
        # alternative is an email per line of a conversation.
        if await unread_count(db, thread.conversation, recipient) > 1:
            continue
        if thread.anchor_kind == KIND_DIRECT:
            kind, title = KIND_DIRECT_MESSAGE, f"{who} sent you a message"
        elif thread.anchor_kind == KIND_GROUP:
            kind, title = KIND_DIRECT_MESSAGE, f"{who} wrote in {where}"
        else:
            kind = KIND_TASK_SHARED if thread.anchor_kind == "task" else "project_shared"
            title = f"{who} commented on {where}"
        await notifications_service.notify(
            db,
            user_id=recipient,
            kind=kind,
            title=title,
            link_path=link,
            organisation_id=ctx.organisation.id,
        )


def _anchor(thread: ThreadContext) -> dict:
    """What a message event says it's about: the task or project for a
    comment, the chat itself for a chat — which is also the watch key a
    screen with it open registered."""
    if thread.is_chat:
        return {"kind": "chat", "id": str(thread.conversation.id)}
    anchor_id = thread.conversation.task_id or thread.conversation.project_id
    return {"kind": thread.anchor_kind, "id": str(anchor_id)}


async def unread_count(
    db: AsyncSession, conversation: Conversation | None, user_id: uuid.UUID
) -> int:
    """How many messages this person hasn't seen, ignoring their own."""
    if conversation is None:
        return 0
    cursor = (
        await db.execute(
            select(MessageRead.last_read_at).where(
                MessageRead.conversation_id == conversation.id,
                MessageRead.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    stmt = select(func.count()).select_from(Message).where(
        Message.conversation_id == conversation.id,
        Message.deleted_at.is_(None),
        or_(Message.user_id != user_id, Message.user_id.is_(None)),
    )
    if cursor is not None:
        stmt = stmt.where(Message.created_at > cursor)
    return (await db.execute(stmt)).scalar_one()


def unread_expression(conversation_id_col, cursor_col, user_id: uuid.UUID):
    """`unread_count` as a correlated subquery, for a list of threads at once.

    The same three conditions — not removed, not yours, newer than your
    cursor (or everything, with no cursor) — so the badge on a chat and the
    count inside it can't disagree.
    """
    return (
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conversation_id_col,
            Message.deleted_at.is_(None),
            or_(Message.user_id != user_id, Message.user_id.is_(None)),
            or_(cursor_col.is_(None), Message.created_at > cursor_col),
        )
        .scalar_subquery()
    )


async def mark_read(
    db: AsyncSession, conversation: Conversation | None, user: User, *, upto=None
) -> None:
    """Move this person's cursor to the newest message.

    Set from the **message's own timestamp**, never `now()`: if the API's clock
    runs ahead of the database's, a `now()` cursor would mark a message read
    before it was written.
    """
    if conversation is None:
        return
    newest = upto or (
        await db.execute(
            select(func.max(Message.created_at)).where(
                Message.conversation_id == conversation.id
            )
        )
    ).scalar_one_or_none()
    if newest is None:
        return

    row = (
        await db.execute(
            select(MessageRead).where(
                MessageRead.conversation_id == conversation.id, MessageRead.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            MessageRead(conversation_id=conversation.id, user_id=user.id, last_read_at=newest)
        )
    elif row.last_read_at is None or row.last_read_at < newest:
        row.last_read_at = newest
    else:
        return
    try:
        await db.commit()
    except IntegrityError:
        # Two tabs marking read at once. The cursor is idempotent, so whichever
        # won is fine.
        await db.rollback()


async def get_message(db: AsyncSession, conversation: Conversation, message_id: uuid.UUID):
    message = (
        await db.execute(
            select(Message).where(
                Message.id == message_id, Message.conversation_id == conversation.id
            )
        )
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="comment not found")
    return message


def can_modify(
    *, author_id: uuid.UUID | None, actor_id: uuid.UUID, org_role: str, chat: bool = False
) -> bool:
    """Your own words, or an organisation admin's override.

    The task's owner is deliberately not on this list: owning the work does not
    make you the editor of what other people said about it. **Nor is an admin,
    in a chat** — they cannot see it, so they cannot have an override in it.
    """
    if chat:
        return author_id == actor_id
    return author_id == actor_id or access.administers_organisation(org_role)


async def edit(
    db: AsyncSession,
    ctx: OrgContext,
    message: Message,
    user: User,
    *,
    body: str,
    thread: ThreadContext | None = None,
) -> Message:
    """Rewrite your own words.

    `thread` is optional only because a caller without one can't resolve
    mentions; every route here has one already, having needed it to re-check
    access to the anchor. Given it, **a name the edit added is notified and a
    name that was already there is not** — "I forgot to @ them" is a real
    thing people do, and re-notifying on every save would make fixing a typo
    a second nudge. See rule 5.
    """
    chat = thread is not None and thread.is_chat
    if not can_modify(author_id=message.user_id, actor_id=user.id, org_role=ctx.role, chat=chat):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN, detail="you can only edit your own comments"
        )
    if message.deleted_at is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="that comment was removed"
        )
    was = message.body
    message.body = _clean(body)
    message.edited_at = func.now()
    await db.commit()
    await db.refresh(message)

    if thread is not None:
        await _changed(ctx, thread, message, user, db)
        candidates = await _candidates(db, ctx, thread)
        before = set(mentions_service.resolve(was, candidates, exclude=user.id))
        now = mentions_service.resolve(message.body, candidates, exclude=user.id)
        who = user.display_name or user.email or "Someone"
        for recipient in now:
            if recipient in before:
                continue
            await notifications_service.notify(
                db,
                user_id=recipient,
                kind=KIND_COMMENT_MENTION,
                title=(
                    f"{who} mentioned you in “{thread.anchor_title}”"
                    if thread.anchor_title
                    else f"{who} mentioned you in a chat"
                ),
                link_path=_link(ctx, thread),
                organisation_id=ctx.organisation.id,
            )
    return message


async def remove(
    db: AsyncSession,
    ctx: OrgContext,
    message: Message,
    user: User,
    *,
    thread: ThreadContext | None = None,
) -> Message:
    """Soft delete.

    A hole in a thread people have already read and replied to is worse than a
    tombstone — "this comment was removed" is honest, and the replies still
    make sense.
    """
    chat = thread is not None and thread.is_chat
    if not can_modify(author_id=message.user_id, actor_id=user.id, org_role=ctx.role, chat=chat):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="you can only remove your own comments",
        )
    message.deleted_at = func.now()
    message.body = ""
    await db.commit()
    await db.refresh(message)
    if thread is not None:
        await _changed(ctx, thread, message, user, db)
    return message


async def _changed(
    ctx: OrgContext, thread: ThreadContext, message: Message, actor: User, db: AsyncSession
) -> None:
    """An existing message was edited or removed. Everybody with the thread
    listed or open refetches — the chat list's preview may have been this
    very message. No content, as ever."""
    people = await _interested(db, thread, exclude=None)
    await events.publish_message(
        conversation_id=str(thread.conversation.id),
        message_id=str(message.id),
        user_ids=[str(uid) for uid in {*people, actor.id}],
        anchor=_anchor(thread),
        organisation_id=str(ctx.organisation.id),
    )
