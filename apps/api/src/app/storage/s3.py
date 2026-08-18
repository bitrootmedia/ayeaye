"""Object storage for attachments (RustFS, S3-compatible).

**Two endpoints, and the difference is load-bearing:**

* **internal** (`rustfs:9000`) — what the API calls for HEAD, DELETE and setup.
* **public** — what presigned URLs are *signed against*, because SigV4 covers
  the Host header. Sign with the internal name and the browser's request fails
  the signature check with an error that says nothing about hostnames.

In production both are the site host, because Caddy fronts `/media/*`. In dev
the public one is `http://localhost` for the same reason — a single origin
means the browser needs no CORS at all to upload, which removes the entire
class of preflight problems the reference project had to work around on the
client.

**Path-style addressing by default.** There is no wildcard DNS for
`<bucket>.host`, and it makes the object URL literally `/<bucket>/<key>` — so
with the bucket named `media`, Caddy forwards `/media/*` through untouched.
Stripping the prefix would invalidate every signature, which is why the Caddy
rule is `handle` and not `handle_path`. That reasoning is specific to the
bundled RustFS behind Caddy on the site's own origin — a managed bucket is
never reached through `/media/*` at all, uploads go straight to
`S3_PUBLIC_ENDPOINT` — so `S3_ADDRESSING_STYLE` exists to let a managed
provider differ.

**DigitalOcean Spaces requires virtual-hosted addressing.** Their own docs are
explicit that path-style isn't supported for regular operations, only
`https://<space>.<region>.digitaloceanspaces.com`, with the bucket in the
*host*, not the path — `S3_ADDRESSING_STYLE=virtual` is for exactly this.
Traced back from a real deployment where it surfaced as nothing more specific
than "that file didn't upload": it isn't a signature error or a permissions
error, it's DO's origin not recognising a bucket-in-the-path request as
addressing a bucket at all. **DigitalOcean also requires `S3_REGION=us-east-1`
regardless of where the Space actually is** — the real region lives only in
the endpoint hostname (`fra1`, `nyc3`, …); passing it as the SigV4 region too
produces a signature DO's origin computes differently and rejects.

boto3 is synchronous. Presigning is pure local HMAC with no I/O, so it is safe
inline; anything that actually talks to RustFS goes through a thread so it
can't stall the event loop.
"""

import logging
from functools import lru_cache

import anyio.to_thread
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger("app.storage")


def _config() -> Config:
    return Config(
        signature_version="s3v4",
        s3={"addressing_style": settings.s3_addressing_style},
        retries={"max_attempts": 3, "mode": "standard"},
    )


def _client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=_config(),
    )


@lru_cache(maxsize=2)
def internal_client():
    """For our own calls: HEAD, DELETE, bucket setup."""
    return _client(settings.s3_endpoint)


@lru_cache(maxsize=2)
def public_client():
    """Only ever for signing URLs the browser will use."""
    return _client(settings.s3_public_url)


async def ensure_bucket() -> None:
    """Create the bucket if it isn't there. Called once at startup.

    Failure is logged, not raised: storage being down is a reason attachments
    don't work, not a reason the whole API refuses to boot.
    """

    def _run() -> None:
        client = internal_client()
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
            return
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket", "403"):
                raise
        client.create_bucket(Bucket=settings.s3_bucket)
        logger.info("created bucket %s", settings.s3_bucket)

    try:
        await anyio.to_thread.run_sync(_run)
    except Exception as exc:
        logger.warning("could not ensure bucket %s: %s", settings.s3_bucket, exc)


def presigned_put(key: str, content_type: str, expires: int | None = None) -> str:
    """A URL the browser may PUT exactly one object to.

    `ContentType` is part of the signature, so the client must send precisely
    this value — it cannot relabel a 400MB video as an image after the ticket
    was issued.
    """
    return public_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires or settings.s3_upload_url_ttl,
    )


def presigned_get(key: str, *, filename: str | None = None, expires: int | None = None) -> str:
    """A short-lived URL for reading one object.

    **The URL is a bearer token until it expires.** Anyone holding it can fetch
    the object; that is inherent to presigning. It prevents permanent public
    links, not sharing a live one. If per-request authorisation ever becomes a
    hard requirement, the bytes have to be proxied through the API instead —
    which costs the direct-to-storage transfer this whole design exists for.
    """
    params: dict[str, str] = {"Bucket": settings.s3_bucket, "Key": key}
    if filename:
        # So a download saves under the name the person recognises rather than
        # a UUID.
        params["ResponseContentDisposition"] = f'inline; filename="{filename}"'
    return public_client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=expires or settings.s3_view_url_ttl
    )


async def head_object(key: str) -> dict | None:
    """What actually landed, or None.

    This is the **only** point at which the API can inspect an upload: with a
    presigned PUT the bytes never pass through it. The size limit is enforced
    here against the real object, not against whatever the client claimed.
    """

    def _run():
        try:
            return internal_client().head_object(Bucket=settings.s3_bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    return await anyio.to_thread.run_sync(_run)


async def delete_object(key: str) -> None:
    def _run() -> None:
        internal_client().delete_object(Bucket=settings.s3_bucket, Key=key)

    try:
        await anyio.to_thread.run_sync(_run)
    except Exception as exc:
        # The database row decides what is visible; a stray object is wasted
        # bytes, not a correctness problem.
        logger.warning("could not delete object %s: %s", key, exc)


async def get_object_bytes(key: str) -> bytes | None:
    """Read one object into memory. For the thumbnail worker, which has to see
    the pixels — everything else in the product streams past the API."""

    def _run():
        try:
            return internal_client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    return await anyio.to_thread.run_sync(_run)


async def put_object_bytes(key: str, body: bytes, content_type: str) -> None:
    """Write one object from the API side. Only the worker does this; user
    uploads go browser → storage directly."""

    def _run() -> None:
        internal_client().put_object(
            Bucket=settings.s3_bucket, Key=key, Body=body, ContentType=content_type
        )

    await anyio.to_thread.run_sync(_run)
