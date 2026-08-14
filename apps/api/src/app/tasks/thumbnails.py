"""Making a thumbnail for an uploaded image.

Runs in the worker because resizing a 12MP phone photo is CPU work that has no
business on a request thread — and because the request that triggers it has
already returned. The UI falls back to the full-size object until this lands,
so a worker that is down costs bandwidth rather than a broken image.

Failure is logged, never retried into a loop: a file that can't be decoded
(a "PNG" that is actually a text file, an image format Pillow doesn't know)
will fail identically every time, and the fallback already works.
"""

import io
import logging
import uuid

import anyio.to_thread
from PIL import Image, ImageOps
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Attachment
from app.services.attachments import thumbnail_key
from app.storage import s3
from app.tasks.broker import broker

logger = logging.getLogger("app.tasks.thumbnails")

# Big enough for a retina grid cell, small enough that forty of them cost less
# than one original.
MAX_EDGE = 480
JPEG_QUALITY = 78


def _shrink(raw: bytes) -> bytes:
    with Image.open(io.BytesIO(raw)) as image:
        # Phone photos carry an EXIF orientation that browsers honour and
        # Pillow does not — without this a portrait shot thumbnails sideways.
        image = ImageOps.exif_transpose(image)
        image.thumbnail((MAX_EDGE, MAX_EDGE))
        # Flattened onto white: a JPEG has no alpha channel, and a transparent
        # PNG would otherwise come out with a black background.
        if image.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            converted = image.convert("RGBA")
            background.paste(converted, mask=converted.split()[-1])
            image = background
        else:
            image = image.convert("RGB")

        out = io.BytesIO()
        image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue()


@broker.task
async def make_thumbnail(attachment_id: str) -> None:
    aid = uuid.UUID(attachment_id)

    async with SessionLocal() as db:
        attachment = (
            await db.execute(select(Attachment).where(Attachment.id == aid))
        ).scalar_one_or_none()
        if attachment is None or attachment.thumbnail_key:
            return
        key = attachment.storage_key

    raw = await s3.get_object_bytes(key)
    if raw is None:
        logger.info("no object for %s, nothing to thumbnail", attachment_id)
        return

    try:
        small = await anyio.to_thread.run_sync(_shrink, raw)
    except Exception as exc:
        # Not an error worth retrying — see the module docstring.
        logger.info("could not thumbnail %s: %s", attachment_id, exc)
        return

    thumb = thumbnail_key(key)
    await s3.put_object_bytes(thumb, small, "image/jpeg")

    async with SessionLocal() as db:
        attachment = (
            await db.execute(select(Attachment).where(Attachment.id == aid))
        ).scalar_one_or_none()
        if attachment is not None:
            attachment.thumbnail_key = thumb
            await db.commit()
