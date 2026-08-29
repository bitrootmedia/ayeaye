"""The notepad. One rule, and it is the feature: only the author, ever.

Every statement here filters on `user_id == the caller`. Not "unless
they're an admin" — there is no branch, and there must not be one; see
`services/notes.py`'s identical rule for a private task note and
`models/personal_note.py` for why this one is a list where that one isn't.
"""

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PersonalNote, User
from app.models.personal_note import MAX_TITLE_LENGTH
from app.services.organisations import OrgContext


def mine_stmt(*, user_id: uuid.UUID, ctx: OrgContext) -> Select:
    """The caller's notes in this organisation, most recently updated first —
    the same "what have I been working on" ordering a notepad implies."""
    return (
        select(PersonalNote)
        .where(PersonalNote.organisation_id == ctx.organisation.id, PersonalNote.user_id == user_id)
        .order_by(PersonalNote.updated_at.desc())
    )


async def create(
    db: AsyncSession, ctx: OrgContext, user: User, *, title: str, body: str
) -> PersonalNote:
    title = (title or "").strip()[:MAX_TITLE_LENGTH]
    if not title:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a note needs a title"
        )
    note = PersonalNote(
        organisation_id=ctx.organisation.id, user_id=user.id, title=title, body=body or ""
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


async def get_or_404(
    db: AsyncSession, ctx: OrgContext, note_id: uuid.UUID, user: User
) -> PersonalNote:
    """Yours, in this organisation, or it doesn't exist — not 403. Somebody
    else's note is not something you are being told about, the same
    reasoning `services/notes.py` and `services/reminders.py` both use for
    their own `get_or_404`. Scoped to `ctx.organisation.id` too: without it,
    a note made in one organisation could be edited or deleted through a
    different organisation's URL by the same person, which is exactly the
    cross-organisation leak `mine_stmt` already guards the list against."""
    note = (
        await db.execute(
            select(PersonalNote).where(
                PersonalNote.id == note_id,
                PersonalNote.user_id == user.id,
                PersonalNote.organisation_id == ctx.organisation.id,
            )
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="note not found")
    return note


async def update_one(db: AsyncSession, note: PersonalNote, *, fields: dict) -> PersonalNote:
    if "title" in fields:
        title = (fields["title"] or "").strip()[:MAX_TITLE_LENGTH]
        if not title:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="a note needs a title",
            )
        note.title = title
    if "body" in fields:
        note.body = fields["body"] or ""
    await db.commit()
    await db.refresh(note)
    return note


async def remove(db: AsyncSession, note: PersonalNote) -> None:
    await db.delete(note)
    await db.commit()


__all__ = ["create", "get_or_404", "mine_stmt", "remove", "update_one"]
