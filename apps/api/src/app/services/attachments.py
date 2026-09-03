"""Files, and the three-step upload handshake.

A file is anchored to **a task or a conversation**. Both live in one table
because the task's Files panel shows both: a file dropped into a reply is
exactly as much "a file on this task" as one added from the panel, and
splitting them means hunting through a thread for the survey PDF.

The bytes go **browser → storage directly** and never pass through the API.
That is the whole design — a phone video shouldn't occupy a worker for two
minutes — and it forces the shape:

1. **`POST .../attachments`** — check access, validate the declared type, write
   a `pending` row, return a presigned PUT.
2. **the browser PUTs to storage.** The API isn't involved.
3. **`POST .../attachments/{id}/confirm`** — HEAD the object to learn what
   *really* landed, enforce the size limit against the **real** size, flip the
   row to `ready`.

**Step 3 is the only point at which the API can inspect an upload.** A client
that declares `image/png` in step 1 and uploads 400MB of something else is
caught there and nowhere else. A client that never confirms leaves a `pending`
row, which nothing ever renders.

Attachments exist **before** the comment they belong to: you attach, then send.
So `message_id` is nullable, and binding is scoped to `message_id IS NULL` and
to the conversation — an id can't be reused, and it can't be borrowed from
another thread.
"""

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import ArticleRevision, Attachment, Conversation, Message, Task, User
from app.models.conversation import ALLOWED_TYPES, STATUS_PENDING, STATUS_READY
from app.storage import s3

logger = logging.getLogger("app.services.attachments")

# How long a staged-but-unsent attachment survives before the next upload in
# the same thread sweeps it. Generous: someone can pick a file, get
# interrupted, and come back.
STALE_AFTER = timedelta(hours=6)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def clean_filename(name: str) -> str:
    """A display name that is safe to echo back.

    **Never used to build the storage key.** The key is a UUID: two people
    uploading `photo.jpg` must not collide, and a filename is attacker input
    that would otherwise reach a path.
    """
    name = _SAFE_NAME.sub("_", (name or "").strip())[-120:].lstrip("._-")
    return name or "attachment"


def storage_key(anchor: str, anchor_id: uuid.UUID, attachment_id: uuid.UUID, filename: str) -> str:
    """`<anchor>/<id>/<attachment>/<name>`.

    The name is on the end for the benefit of anyone looking in the bucket; the
    uniqueness comes entirely from the ids before it.
    """
    return f"{anchor}/{anchor_id}/{attachment_id}/{clean_filename(filename)}"


def thumbnail_key(storage_key_: str) -> str:
    """Beside the original, so deleting the prefix removes both."""
    return f"{storage_key_}.thumb.jpg"


def is_allowed_type(content_type: str) -> bool:
    return content_type in ALLOWED_TYPES


def normalise_content_type(content_type: str) -> str:
    """Strip codec parameters.

    **This is the voice-note trap, and it applies to everything.** A browser
    reports `audio/webm;codecs=opus`; the presigned signature covers
    Content-Type *byte for byte*, so the client must send back exactly what was
    signed. Normalising here — and having the client send the bare type — is
    what keeps the two in step. Chrome and Firefox produce webm, Safari mp4.
    """
    return (content_type or "").split(";")[0].strip().lower()


async def create(
    db: AsyncSession,
    user: User,
    *,
    filename: str,
    content_type: str,
    conversation: Conversation | None = None,
    task: Task | None = None,
    article_revision: ArticleRevision | None = None,
) -> tuple[Attachment, str]:
    """Step 1. Returns the row and the URL to PUT to.

    Anchored to exactly one of a conversation (a comment attachment, staged
    before the comment exists), a task (added straight from the Files panel),
    or an article revision (an inline image or a standalone file added while
    that revision is the mutable "current" one — see `services/articles.py`).
    """
    anchors = [conversation, task, article_revision]
    if sum(a is not None for a in anchors) != 1:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="an attachment belongs to exactly one thing",
        )

    content_type = normalise_content_type(content_type)
    if not is_allowed_type(content_type):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{content_type or 'that kind of file'} can't be attached",
        )

    if conversation is not None:
        # Only comment attachments can be abandoned mid-compose; a task file
        # is confirmed and done.
        await sweep_stale(db, conversation, user)

    if conversation is not None:
        anchor, anchor_id = "comments", conversation.id
    elif task is not None:
        anchor, anchor_id = "tasks", task.id
    else:
        anchor, anchor_id = "article_revisions", article_revision.id
    attachment = Attachment(
        conversation_id=conversation.id if conversation else None,
        task_id=task.id if task else None,
        article_revision_id=article_revision.id if article_revision else None,
        user_id=user.id,
        filename=clean_filename(filename),
        content_type=content_type,
        storage_key="",  # needs the id, which the database assigns
        status=STATUS_PENDING,
    )
    db.add(attachment)
    await db.flush()
    attachment.storage_key = storage_key(anchor, anchor_id, attachment.id, filename)
    await db.commit()
    await db.refresh(attachment)

    return attachment, s3.presigned_put(attachment.storage_key, content_type)


async def confirm(
    db: AsyncSession, attachment: Attachment, user: User
) -> Attachment:
    """Step 3. The only look the API gets at what was actually uploaded."""
    if attachment.user_id != user.id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="that isn't your upload",
        )
    if attachment.status == STATUS_READY:
        # Double-clicked, or a retry after a dropped response.
        return attachment

    head = await s3.head_object(attachment.storage_key)
    if head is None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="the upload didn't arrive — try again",
        )

    size = int(head.get("ContentLength") or 0)
    if size <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="that file is empty"
        )
    if size > settings.attachment_max_bytes:
        # Enforced against the REAL object, not the client's claim. The bytes
        # are already in the bucket, so they have to be removed here.
        await s3.delete_object(attachment.storage_key)
        await db.delete(attachment)
        await db.commit()
        limit = settings.attachment_max_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"that file is larger than {limit}MB",
        )

    # What actually landed wins over what was declared — a client can put any
    # Content-Type on the object, and this is where the two are reconciled.
    landed = normalise_content_type(head.get("ContentType") or attachment.content_type)
    if is_allowed_type(landed):
        attachment.content_type = landed

    attachment.size_bytes = size
    attachment.status = STATUS_READY
    await db.commit()
    await db.refresh(attachment)

    if attachment.content_type.startswith("image/"):
        # Queued, not done here: resizing a 12MP photo is CPU work that has no
        # business on a request thread. The UI falls back to the full-size
        # object until the job lands, so a worker that is down costs bandwidth
        # rather than a broken image.
        try:
            from app.tasks.thumbnails import make_thumbnail

            await make_thumbnail.kiq(str(attachment.id))
        except Exception as exc:
            logger.warning("could not queue a thumbnail for %s: %s", attachment.id, exc)

    return attachment


async def for_task(
    db: AsyncSession, task: Task, conversation_id: uuid.UUID | None
) -> list[Attachment]:
    """Every file on a task: added directly, **and** posted in its comments.

    One list because that is the question people ask — "where's the survey
    PDF" — and splitting it by how the file arrived means hunting through a
    thread. The caller marks the comment-posted ones.

    One statement: an OR over the two anchors rather than two queries merged in
    Python, so ordering is the database's job.
    """
    clauses = [Attachment.task_id == task.id]
    if conversation_id is not None:
        # Only *sent* comment attachments. A file someone staged and never
        # posted is not on the task.
        clauses.append(
            (Attachment.conversation_id == conversation_id) & Attachment.message_id.isnot(None)
        )
    from sqlalchemy import or_ as _or

    return list(
        (
            await db.execute(
                select(Attachment)
                .where(_or(*clauses), Attachment.status == STATUS_READY)
                .order_by(Attachment.id.desc())
            )
        )
        .scalars()
        .all()
    )


async def for_tasks(
    db: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Attachment]]:
    """Every attachment across many tasks, in one statement — added directly
    *or* posted in comments, the same OR-over-both-anchors shape `for_task()`
    already uses for one. Built for the data export, which would otherwise be
    N+1 deep across however many tasks are in scope; mirrors `for_messages()`'s
    batched-by-ids shape in this same file.

    A comment-posted attachment has no `task_id` of its own — it's anchored to
    the conversation instead — so the grouping key is
    `COALESCE(Attachment.task_id, Conversation.task_id)`, not a plain column.
    """
    if not task_ids:
        return {}
    task_col = func.coalesce(Attachment.task_id, Conversation.task_id).label("task_id")
    rows = (
        await db.execute(
            select(Attachment, task_col)
            .outerjoin(Conversation, Conversation.id == Attachment.conversation_id)
            .where(
                or_(
                    Attachment.task_id.in_(task_ids),
                    and_(
                        Conversation.task_id.in_(task_ids), Attachment.message_id.isnot(None)
                    ),
                ),
                Attachment.status == STATUS_READY,
            )
            .order_by(Attachment.id)
        )
    ).all()
    grouped: dict[uuid.UUID, list[Attachment]] = {}
    for attachment, task_id in rows:
        grouped.setdefault(task_id, []).append(attachment)
    return grouped


async def delete(db: AsyncSession, attachment: Attachment) -> None:
    """Remove the row and the bytes, thumbnail included."""
    await s3.delete_object(attachment.storage_key)
    if attachment.thumbnail_key:
        await s3.delete_object(attachment.thumbnail_key)
    await db.delete(attachment)
    await db.commit()


async def sweep_stale(db: AsyncSession, conversation: Conversation, user: User) -> int:
    """Drop this person's abandoned uploads in this thread.

    Swept on the next upload rather than by a scheduled job: it is the moment
    somebody is demonstrably present, it needs no extra moving part, and the
    cost is bounded by how many files one person staged and abandoned.
    """
    cutoff = datetime.now(UTC) - STALE_AFTER
    stale = (
        (
            await db.execute(
                select(Attachment).where(
                    Attachment.conversation_id == conversation.id,
                    Attachment.user_id == user.id,
                    Attachment.message_id.is_(None),
                    Attachment.created_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    for attachment in stale:
        await s3.delete_object(attachment.storage_key)
        await db.delete(attachment)
    if stale:
        await db.commit()
        logger.info("swept %d abandoned upload(s)", len(stale))
    return len(stale)


async def bind_to_message(
    db: AsyncSession,
    conversation: Conversation,
    message: Message,
    user: User,
    attachment_ids: list[uuid.UUID],
) -> list[Attachment]:
    """Attach staged uploads to the comment being sent.

    Scoped to this conversation, this person, `message_id IS NULL` and
    `status = 'ready'`. Every one of those matters: without them an id could be
    borrowed from another thread, stolen from someone else, reused on a second
    comment, or bound while the bytes were never confirmed to exist.
    """
    if not attachment_ids:
        return []
    rows = (
        (
            await db.execute(
                select(Attachment).where(
                    Attachment.id.in_(attachment_ids),
                    Attachment.conversation_id == conversation.id,
                    Attachment.user_id == user.id,
                    Attachment.message_id.is_(None),
                    Attachment.status == STATUS_READY,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.message_id = message.id
    await db.commit()
    return list(rows)


async def get(
    db: AsyncSession, conversation: Conversation, attachment_id: uuid.UUID
) -> Attachment:
    row = (
        await db.execute(
            select(Attachment).where(
                Attachment.id == attachment_id,
                Attachment.conversation_id == conversation.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="attachment not found"
        )
    return row


async def for_messages(
    db: AsyncSession, message_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Attachment]]:
    """Every attachment across a page of comments, in one query.

    One lookup for the whole thread rather than one per comment — the same
    discipline as every other list in this codebase.
    """
    if not message_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(Attachment)
                .where(
                    Attachment.message_id.in_(message_ids),
                    Attachment.status == STATUS_READY,
                )
                .order_by(Attachment.id)
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[uuid.UUID, list[Attachment]] = {}
    for row in rows:
        grouped.setdefault(row.message_id, []).append(row)  # type: ignore[arg-type]
    return grouped


async def for_article_revision(db: AsyncSession, revision_id: uuid.UUID) -> list[Attachment]:
    """Standalone files attached while this exact revision was the mutable
    "current" one — the Files panel, scoped to the revision being viewed. A
    fresh editing session starts with none; an old revision in history shows
    exactly what was on it at the time. Unlike a task's Files panel, there is
    no OR-over-two-anchors here — a comment can't attach to an article."""
    return list(
        (
            await db.execute(
                select(Attachment)
                .where(
                    Attachment.article_revision_id == revision_id,
                    Attachment.status == STATUS_READY,
                )
                .order_by(Attachment.id.desc())
            )
        )
        .scalars()
        .all()
    )


async def for_article_revisions(
    db: AsyncSession, revision_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Attachment]]:
    """The batched form of `for_article_revision`, the same one-query-per-page
    discipline `for_tasks` already follows."""
    if not revision_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(Attachment)
                .where(
                    Attachment.article_revision_id.in_(revision_ids),
                    Attachment.status == STATUS_READY,
                )
                .order_by(Attachment.id)
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[uuid.UUID, list[Attachment]] = {}
    for row in rows:
        grouped.setdefault(row.article_revision_id, []).append(row)  # type: ignore[arg-type]
    return grouped


async def image_urls_for_article(
    db: AsyncSession, article_id: uuid.UUID, wanted: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Fresh presigned URLs for inline images referenced by an article body.

    Scoped to attachments across **any revision of this article**, not just
    the one being rendered — a revision's body is copied forward from the
    previous one, so an inline image reference can point at an attachment a
    different, older revision actually owns (`services/articles.py`'s own
    docstring explains why). `richtext.render()` already tolerates an id that
    resolves to nothing, so this needs no change there.
    """
    if not wanted:
        return {}
    rows = (
        (
            await db.execute(
                select(Attachment)
                .join(ArticleRevision, ArticleRevision.id == Attachment.article_revision_id)
                .where(Attachment.id.in_(wanted), ArticleRevision.article_id == article_id)
            )
        )
        .scalars()
        .all()
    )
    return {row.id: view_url(row) for row in rows}


def thumbnail_url(attachment: Attachment) -> str | None:
    """The small version, or None if there isn't one yet.

    None is a real answer, not an error: the job may not have run, or the file
    isn't an image. The UI falls back to the original.
    """
    if not attachment.thumbnail_key:
        return None
    return s3.presigned_get(attachment.thumbnail_key)


def view_url(attachment: Attachment) -> str:
    """Minted fresh at read time, never stored.

    A presigned URL expires, so caching one in the database or sending it over
    the realtime channel would hand out links that are dead by the time anyone
    clicks them.
    """
    return s3.presigned_get(attachment.storage_key, filename=attachment.filename)
