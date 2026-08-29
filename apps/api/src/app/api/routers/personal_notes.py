"""The notepad — free-form personal notes, scoped to an organisation.

Thin: the one rule ("only the author, ever") lives in
`services/personal_notes.py`. Membership in the organisation (`CurrentOrg`)
is the only gate — there is no sharing, so there is nothing else to check.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models.personal_note import MAX_TITLE_LENGTH
from app.services import personal_notes as notes_service

router = APIRouter(prefix="/organisations/{org_id}", tags=["personal-notes"])


class PersonalNoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    body: str = ""


class PersonalNoteUpdate(BaseModel):
    title: str | None = None
    body: str | None = None


class PersonalNoteOut(BaseModel):
    id: str
    title: str
    body: str
    created_at: datetime
    updated_at: datetime


def _out(note) -> PersonalNoteOut:
    return PersonalNoteOut(
        id=str(note.id),
        title=note.title,
        body=note.body,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.get("/notes", response_model=list[PersonalNoteOut])
async def list_notes(ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Yours alone, most recently updated first."""
    rows = (await db.execute(notes_service.mine_stmt(user_id=user.id, ctx=ctx))).scalars().all()
    return [_out(n) for n in rows]


@router.post("/notes", response_model=PersonalNoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(body: PersonalNoteIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    note = await notes_service.create(db, ctx, user, title=body.title, body=body.body)
    return _out(note)


@router.patch("/notes/{note_id}", response_model=PersonalNoteOut)
async def update_note(
    note_id: uuid.UUID, body: PersonalNoteUpdate, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    note = await notes_service.get_or_404(db, ctx, note_id, user)
    note = await notes_service.update_one(db, note, fields=body.model_dump(exclude_unset=True))
    return _out(note)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    note = await notes_service.get_or_404(db, ctx, note_id, user)
    await notes_service.remove(db, note)
