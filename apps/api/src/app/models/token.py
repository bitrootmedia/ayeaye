"""Personal access tokens: how a program acts as a person.

    users ──► personal_access_tokens

**A token is a person, not a service account.** Everything it can reach is
resolved through `services/access.py` against the user who created it, so a
token cannot see one row more than its owner can. That is the whole safety
argument for exposing MCP at all: there is no second access path to review,
because there is no second access path.

## What is stored

The secret is **hashed**, and the plaintext is shown exactly once at creation.
A token that can be recovered from the database is a token that a database
backup hands to whoever holds it.

`prefix` is the first few characters, kept in the clear so the account screen
can show *which* token a row is without being able to reconstruct it — "which
of these three do I revoke" is otherwise unanswerable.

## Scope

Two values, `read` and `write`, and the split is deliberate: "let an assistant
read my work" and "let it create things in my name" are different decisions,
and most people only want the first. A `read` token is refused by every tool
that changes anything, in one place.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPES = (SCOPE_READ, SCOPE_WRITE)

# Recognisable in a log or a config file, and greppable if one leaks.
TOKEN_PREFIX = "ayc_"
PREFIX_KEPT = 12


class PersonalAccessToken(Base):
    __tablename__ = "personal_access_tokens"
    __table_args__ = (CheckConstraint(f"scope IN {SCOPES!r}", name="ck_pat_scope"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # What it's for, in the owner's words. "Claude on my laptop" is the whole
    # point of the field: a list of hashes tells nobody which one to revoke.
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    scope: Mapped[str] = mapped_column(String(8), nullable=False, server_default=SCOPE_READ)

    # SHA-256 of the secret. Unique so a lookup is an index hit rather than a
    # scan over every token in the installation.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)

    # Answering "is this one still in use" is the only way anybody ever tidies
    # up. Written at most once a minute — see services/tokens.py.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
