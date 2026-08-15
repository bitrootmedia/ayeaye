"""Minting and checking personal access tokens.

Three rules:

1. **The plaintext exists once.** It is returned from `create()` and never
   stored — only its SHA-256. A token you can read back out of the database is
   a token that a backup hands to whoever holds the backup.

2. **A token is its owner.** `authenticate()` returns the `User`, and every
   caller then goes through the ordinary services. There is no "service
   account" path and no elevated mode: whatever the person can see, the token
   can see, and not a row more.

3. **`read` is refused by anything that writes**, in one place
   (`require_write`). Two scopes rather than a permission matrix, because the
   only question anybody actually has is "can this thing change my work".

SHA-256 rather than a password hash: this is a 256-bit random secret, not a
human-chosen password, so there is nothing to brute-force and no reason to pay
bcrypt's cost on every request.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PersonalAccessToken, User
from app.models.token import PREFIX_KEPT, SCOPE_WRITE, SCOPES, TOKEN_PREFIX

# 32 bytes of randomness, base64url'd. Long enough that guessing is not a
# threat model worth thinking about.
TOKEN_BYTES = 32

# `last_used_at` is a tidying-up aid, not an audit log. Writing it on every
# call would mean an UPDATE per MCP request — this makes it at most one a
# minute per token.
TOUCH_EVERY = timedelta(minutes=1)


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


async def create(
    db: AsyncSession, user: User, *, name: str, scope: str
) -> tuple[PersonalAccessToken, str]:
    """Returns the row **and the plaintext**, which the caller must show once."""
    name = (name or "").strip()[:80]
    if not name:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="give the token a name, so you know which one to revoke later",
        )
    if scope not in SCOPES:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"scope must be one of {', '.join(SCOPES)}",
        )

    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)
    row = PersonalAccessToken(
        user_id=user.id,
        name=name,
        scope=scope,
        token_hash=hash_token(plaintext),
        prefix=plaintext[:PREFIX_KEPT],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, plaintext


async def mine(db: AsyncSession, user: User) -> list[PersonalAccessToken]:
    return list(
        (
            await db.execute(
                select(PersonalAccessToken)
                .where(PersonalAccessToken.user_id == user.id)
                .order_by(PersonalAccessToken.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def revoke(db: AsyncSession, user: User, token_id: uuid.UUID) -> None:
    """Yours, or it doesn't exist. 404 rather than 403 — somebody else's token
    is not something you are being told about."""
    row = (
        await db.execute(
            select(PersonalAccessToken).where(
                PersonalAccessToken.id == token_id, PersonalAccessToken.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="token not found")
    await db.delete(row)
    await db.commit()


async def authenticate(
    db: AsyncSession, header: str | None
) -> tuple[User, PersonalAccessToken] | None:
    """Resolve `Authorization: Bearer ayc_…` to the person who owns it.

    Returns None for anything unrecognised — a caller with a bad token learns
    only that it didn't work, never whether it was the right shape, the wrong
    user's, or revoked a minute ago.
    """
    if not header or not header.lower().startswith("bearer "):
        return None
    plaintext = header[7:].strip()
    if not plaintext.startswith(TOKEN_PREFIX):
        return None

    row = (
        await db.execute(
            select(PersonalAccessToken).where(
                PersonalAccessToken.token_hash == hash_token(plaintext)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if user is None:
        return None

    now = datetime.now(UTC)
    if row.last_used_at is None or now - row.last_used_at > TOUCH_EVERY:
        row.last_used_at = now
        await db.commit()
    return user, row


def require_write(token: PersonalAccessToken) -> None:
    """The one place a read-only token is turned away."""
    if token.scope != SCOPE_WRITE:
        raise PermissionError(
            "This token is read-only. Create one with write access if you want "
            "the assistant to be able to change anything."
        )
