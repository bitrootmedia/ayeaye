"""Data exports — thin: the two rules (privacy, autodelete) live in
`services/exports.py` and `models/export.py`. Membership in the
organisation (`CurrentOrg`) is enough to *request* one; every read after
that filters on the requester, with no admin override — see the service
module's own docstring.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.services import exports as exports_service

router = APIRouter(prefix="/organisations/{org_id}/exports", tags=["exports"])


class ExportCreate(BaseModel):
    # None means the whole organisation.
    project_id: str | None = None


class ExportOut(BaseModel):
    id: str
    project_id: str | None
    status: str
    file_size: int | None
    created_at: datetime
    completed_at: datetime | None


class ExportDownload(BaseModel):
    download_url: str


def _out(export) -> ExportOut:
    return ExportOut(
        id=str(export.id),
        project_id=str(export.project_id) if export.project_id else None,
        status=export.status,
        file_size=export.file_size,
        created_at=export.created_at,
        completed_at=export.completed_at,
    )


@router.post("", response_model=ExportOut, status_code=201)
async def create_export(body: ExportCreate, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    project_id = uuid.UUID(body.project_id) if body.project_id else None
    export = await exports_service.create(db, ctx, user, project_id)
    return _out(export)


@router.get("", response_model=list[ExportOut])
async def list_exports(ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Your own export history in this organisation — never anyone else's."""
    return [_out(e) for e in await exports_service.mine(db, ctx, user)]


@router.get("/{export_id}", response_model=ExportOut)
async def get_export(export_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    export = await exports_service.get_owned_or_404(db, ctx, user, export_id)
    return _out(export)


@router.get("/{export_id}/download", response_model=ExportDownload)
async def download_export(export_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    export = await exports_service.get_owned_or_404(db, ctx, user, export_id)
    url = await exports_service.download_url(db, export)
    return ExportDownload(download_url=url)
