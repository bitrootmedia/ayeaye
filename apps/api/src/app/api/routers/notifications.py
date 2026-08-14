"""The inbox. One per person, across every organisation they're in."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.tasks import NotificationOut, UnreadCountOut
from app.services import notifications as notifications_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    user: CurrentUser, db: DbSession, unread_only: bool = False, limit: int = 50
):
    """Not organisation-scoped, deliberately: you have one inbox, and being
    notified about a task shouldn't depend on which organisation you happen to
    have open."""
    return [
        NotificationOut(
            id=str(n.id),
            kind=n.kind,
            title=n.title,
            body=n.body,
            link_path=n.link_path,
            read_at=n.read_at,
            created_at=n.created_at,
        )
        for n in await notifications_service.list_for_user(
            db, user, unread_only=unread_only, limit=limit
        )
    ]


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread(user: CurrentUser, db: DbSession):
    """The badge. Polled, so it stays cheap: one indexed count."""
    return UnreadCountOut(unread=await notifications_service.unread_count(db, user))


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(notification_id: uuid.UUID, user: CurrentUser, db: DbSession):
    await notifications_service.mark_read(db, user, notification_id)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(user: CurrentUser, db: DbSession):
    await notifications_service.mark_all_read(db, user)
