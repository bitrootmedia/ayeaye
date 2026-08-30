"""Data export: create, list, and mint a download link for a ZIP.

Read `models/export.py`'s own docstring first — it states the two rules
that matter: **every read filters on the requester, with no admin
override** (the zip's contents are the requester's own visibility, not the
organisation's), and **autodelete after a confirmed download**, where
"confirmed" means the one honest signal a server can actually observe: the
person asked for the file.

Building the zip itself happens in the worker — see `tasks/exports.py`.
This module is the create/list/download surface around that table.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Export, User
from app.models.export import STATUS_EXPIRED, STATUS_READY
from app.services.organisations import OrgContext
from app.storage import s3

# Long enough for a large zip on a slow connection to finish downloading;
# short enough that "auto-delete" still means something.
GRACE_PERIOD = timedelta(minutes=5)
# An export nobody ever downloads still shouldn't sit in storage forever.
MAX_AGE = timedelta(days=7)


async def create(
    db: AsyncSession, ctx: OrgContext, user: User, project_id: uuid.UUID | None
) -> Export:
    """Queue a build. No permission check beyond organisation membership —
    exporting needs nothing more than *seeing* what goes in it, the same
    "read is enough" bar time-logging already uses."""
    if project_id is not None:
        # Imported here: services.projects imports services.access and this
        # module has no business being pulled in by every caller of
        # services.organisations, which OrgContext already comes from.
        from app.services import projects as projects_service

        # 404s if the project doesn't exist, belongs to another
        # organisation, or simply isn't shared with this caller — the same
        # answer `context_for` gives everywhere else.
        await projects_service.context_for(db, ctx, project_id, user.id)

    row = Export(
        organisation_id=ctx.organisation.id,
        project_id=project_id,
        requested_by_user_id=user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Imported here, not at module level: app.tasks.exports imports this
    # module too (to update the row it's building), and a top-level import
    # cycle is worse than one late import.
    from app.tasks.exports import build_export

    await build_export.kiq(str(row.id))
    return row


async def mine(db: AsyncSession, ctx: OrgContext, user: User) -> list[Export]:
    """Your own export history in this organisation — never anyone else's,
    not even an admin's. See the module docstring."""
    return list(
        (
            await db.execute(
                select(Export)
                .where(
                    Export.organisation_id == ctx.organisation.id,
                    Export.requested_by_user_id == user.id,
                )
                .order_by(Export.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def get_owned_or_404(
    db: AsyncSession, ctx: OrgContext, user: User, export_id: uuid.UUID
) -> Export:
    """Yours, or it doesn't exist. 404, not 403 — someone else's export is
    not something you are being told about."""
    row = (
        await db.execute(
            select(Export).where(
                Export.id == export_id,
                Export.organisation_id == ctx.organisation.id,
                Export.requested_by_user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="export not found")
    return row


async def download_url(db: AsyncSession, export: Export) -> str:
    """A fresh presigned URL, minted per call and never stored — the
    identical rule `attachments.view_url` already documents.

    Stamps `downloaded_at` the first time only: this is the "confirmed
    download" signal `sweep_expired_exports` (tasks/exports.py) acts on, so
    a second click just re-mints the URL without moving the clock — nobody
    can postpone deletion by downloading twice.
    """
    if export.status == STATUS_EXPIRED:
        raise HTTPException(
            status_code=http_status.HTTP_410_GONE, detail="this export has expired"
        )
    if export.status != STATUS_READY or export.storage_key is None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="this export isn't ready yet"
        )

    if export.downloaded_at is None:
        export.downloaded_at = datetime.now(UTC)
        await db.commit()

    return s3.presigned_get(export.storage_key, filename=f"export-{export.id}.zip")


async def claim_expired(db: AsyncSession) -> list[str]:
    """One conditional UPDATE that both selects and marks — the identical
    claim-not-select-then-update shape `reminders.claim` uses, so a
    scheduler restart or two schedulers racing can't both try to delete the
    same object. Returns the storage keys to delete; the caller
    (`sweep_expired_exports`) does the actual S3 call, since this function
    has no business reaching into storage itself.

    Two independent conditions merge into one claim: downloaded-and-past-
    grace, or never-downloaded-and-past-the-outer-ceiling.

    `storage_key` is cleared in a **second**, separate statement rather than
    the same one — `RETURNING` reflects the row *after* the update, so a
    single statement that both clears the key and returns it would hand
    back `NULL` every time, exactly the key the caller needs to delete the
    S3 object. The claim itself (the part that has to be race-safe) is
    entirely in the first statement; by the time the second one runs, only
    the winner holds these ids, so it needs no claim of its own.
    """
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            update(Export)
            .where(
                Export.status == STATUS_READY,
                Export.storage_key.isnot(None),
                (
                    (Export.downloaded_at.isnot(None))
                    & (Export.downloaded_at <= now - GRACE_PERIOD)
                )
                | ((Export.downloaded_at.is_(None)) & (Export.created_at <= now - MAX_AGE)),
            )
            .values(status=STATUS_EXPIRED)
            .returning(Export.id, Export.storage_key)
        )
    ).all()
    await db.commit()

    ids = [row[0] for row in rows]
    keys = [row[1] for row in rows if row[1]]
    if ids:
        await db.execute(update(Export).where(Export.id.in_(ids)).values(storage_key=None))
        await db.commit()
    return keys


__all__ = ["create", "mine", "get_owned_or_404", "download_url", "claim_expired"]
