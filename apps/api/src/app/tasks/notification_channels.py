"""Telegram and webhook notification delivery.

Runs in the worker for the same reason `send_notification_email` does: an
unreachable bot API or a slow webhook receiver must not hold a request open.

Neither job carries the per-channel idempotency `send_notification_email`
gets from `Notification.emailed` — there's exactly one email channel per
person, so one flag on the notification row is enough to say "this went."
Telegram and webhook are N channels per person, and a flag per (notification,
channel) pair was traded away deliberately: a webhook receiver is expected to
dedupe on the notification id in its own payload, the identical at-least-once
contract GitHub and Stripe already teach people to expect from a webhook, and
a duplicate Telegram message on a worker retry is a minor cosmetic cost, not
a correctness one.
"""

import json
import logging
import uuid

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.db import SessionLocal
from app.models import Notification, NotificationChannel
from app.services import notification_channels as channels_service
from app.services import telegram as telegram_service
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.notification_channels")


async def _load(
    db, notification_id: str, channel_id: str
) -> tuple[Notification | None, NotificationChannel | None]:
    notification = (
        await db.execute(select(Notification).where(Notification.id == uuid.UUID(notification_id)))
    ).scalar_one_or_none()
    channel = (
        await db.execute(
            select(NotificationChannel).where(NotificationChannel.id == uuid.UUID(channel_id))
        )
    ).scalar_one_or_none()
    return notification, channel


@broker.task
async def send_telegram_message(notification_id: str, channel_id: str) -> None:
    async with SessionLocal() as db:
        notification, channel = await _load(db, notification_id, channel_id)
    if notification is None or channel is None:
        # Either was deleted between the raise and this job running — the
        # subject vanished, same reasoning `send_notification_email` already
        # documents for its own version of this check.
        logger.info("notification or channel gone before Telegram send")
        return
    chat_id = channel.config.get("chat_id")
    if not chat_id:
        return

    paragraphs = [notification.title]
    if notification.body:
        paragraphs.append(notification.body)
    if notification.link_path:
        paragraphs.append(f"{settings.site_url}{notification.link_path}")
    await telegram_service.send_message(str(chat_id), "\n\n".join(paragraphs))


@broker.task
async def send_webhook_notification(notification_id: str, channel_id: str) -> None:
    async with SessionLocal() as db:
        notification, channel = await _load(db, notification_id, channel_id)
    if notification is None or channel is None:
        logger.info("notification or channel gone before webhook send")
        return
    url = channel.config.get("url")
    secret = channel.config.get("secret")
    if not url or not secret:
        return

    body = json.dumps(
        {
            "id": str(notification.id),
            "kind": notification.kind,
            "title": notification.title,
            "body": notification.body,
            "link_path": notification.link_path,
            "created_at": notification.created_at.isoformat(),
        }
    ).encode()
    headers = {
        "Content-Type": "application/json",
        # The same header shape GitHub and Stripe already taught people to
        # expect from a webhook, signed over the raw body with the channel's
        # own secret — see services/notification_channels.py for why that
        # secret is stored in plaintext rather than hashed.
        "X-Ayeaye-Signature": channels_service.sign(secret, body),
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, content=body, headers=headers)
        resp.raise_for_status()
