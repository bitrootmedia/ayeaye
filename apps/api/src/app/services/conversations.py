"""Comment threads on tasks and projects.

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

Who gets notified is deliberately **not** "everyone who can see it": org admins
can see everything, and drowning them is not a feature. It is the people with
a stake — the task's owner, whoever is being asked to act, and anyone who has
already spoken in the thread — minus the author.
"""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, MessageRead, Project, Task, User
from app.models.notification import KIND_TASK_SHARED
from app.realtime import events
from app.services import access
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
    anchor_kind: str  # "task" | "project"
    can_post: bool


def _clean(body: str) -> str:
    body = (body or "").strip()
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
        organisation_id=ctx.organisation.id, task_id=task_id, project_id=project_id
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
    db: AsyncSession, conversation: Conversation | None
) -> list[tuple[Message, User | None]]:
    """Oldest first — a conversation reads as a conversation, not a feed."""
    if conversation is None:
        return []
    rows = (
        await db.execute(
            select(Message, User)
            .outerjoin(User, User.id == Message.user_id)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id)
        )
    ).all()
    return [(m, u) for m, u in rows]


async def post(
    db: AsyncSession,
    ctx: OrgContext,
    thread: ThreadContext,
    user: User,
    *,
    body: str,
) -> Message:
    if not thread.can_post:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="you can't comment on this",
        )
    message = Message(conversation_id=thread.conversation.id, user_id=user.id, body=_clean(body))
    db.add(message)
    await db.commit()
    await db.refresh(message)

    # Your own comment is read by definition — otherwise posting would leave
    # you with an unread badge for something you just wrote.
    await mark_read(db, thread.conversation, user, upto=message.created_at)

    recipients = await _interested(db, thread, exclude=user.id)
    await _announce(db, ctx, thread, message, user, recipients)
    return message


async def _interested(
    db: AsyncSession, thread: ThreadContext, *, exclude: uuid.UUID
) -> list[uuid.UUID]:
    """Who has a stake in this thread.

    The task's owner, whoever is being asked to act on it, and anyone who has
    already spoken. **Not** everyone who could see it: organisation admins can
    see everything, and a product that mails them every comment in the company
    is one where they turn notifications off.
    """
    people: set[uuid.UUID] = set()

    if thread.conversation.task_id is not None:
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


async def _announce(
    db: AsyncSession,
    ctx: OrgContext,
    thread: ThreadContext,
    message: Message,
    author: User,
    recipients: list[uuid.UUID],
) -> None:
    """Push it live, and notify whoever isn't already behind."""
    link = (
        f"/orgs/{ctx.organisation.id}/tasks/{thread.conversation.task_id}"
        if thread.conversation.task_id
        else f"/orgs/{ctx.organisation.id}/projects/{thread.conversation.project_id}"
    )

    # Live first: everyone with the thread open sees it appear, including the
    # author's other tabs.
    anchor_id = thread.conversation.task_id or thread.conversation.project_id
    await events.publish_message(
        conversation_id=str(thread.conversation.id),
        message_id=str(message.id),
        user_ids=[str(uid) for uid in [*recipients, author.id]],
        anchor={"kind": thread.anchor_kind, "id": str(anchor_id)},
    )

    who = author.display_name or author.email or "Someone"
    for recipient in recipients:
        # Rule 4. Two unread messages in one thread is one notification; the
        # alternative is an email per line of a conversation.
        if await unread_count(db, thread.conversation, recipient) > 1:
            continue
        await notifications_service.notify(
            db,
            user_id=recipient,
            kind=KIND_TASK_SHARED if thread.anchor_kind == "task" else "project_shared",
            title=f"{who} commented on “{thread.anchor_title}”",
            link_path=link,
        )


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
    elif row.last_read_at < newest:
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


def can_modify(*, author_id: uuid.UUID | None, actor_id: uuid.UUID, org_role: str) -> bool:
    """Your own words, or an organisation admin's override.

    The task's owner is deliberately not on this list: owning the work does not
    make you the editor of what other people said about it.
    """
    return author_id == actor_id or access.administers_organisation(org_role)


async def edit(
    db: AsyncSession, ctx: OrgContext, message: Message, user: User, *, body: str
) -> Message:
    if not can_modify(author_id=message.user_id, actor_id=user.id, org_role=ctx.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN, detail="you can only edit your own comments"
        )
    if message.deleted_at is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="that comment was removed"
        )
    message.body = _clean(body)
    message.edited_at = func.now()
    await db.commit()
    await db.refresh(message)
    return message


async def remove(db: AsyncSession, ctx: OrgContext, message: Message, user: User) -> Message:
    """Soft delete.

    A hole in a thread people have already read and replied to is worse than a
    tombstone — "this comment was removed" is honest, and the replies still
    make sense.
    """
    if not can_modify(author_id=message.user_id, actor_id=user.id, org_role=ctx.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="you can only remove your own comments",
        )
    message.deleted_at = func.now()
    message.body = ""
    await db.commit()
    await db.refresh(message)
    return message
