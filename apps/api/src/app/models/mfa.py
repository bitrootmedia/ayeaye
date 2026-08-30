"""Two-factor auth: one TOTP device and a set of backup codes per account.

    users ──► mfa_totp_devices (0 or 1)
    users ──► mfa_backup_codes (0..10)

Hand-rolled, not SuperTokens' `totp`/`multifactorauth` recipes — those
require a paid core license even self-hosted. See services/mfa.py.

**One device per person, not a list.** SuperTokens' own recipe supports
several named devices; this product doesn't need that flexibility; a single
row keeps enrollment, replacement and removal each one statement instead of
a small device-management screen of their own.

**The secret is stored in the clear.** Unlike a password or a backup code,
a TOTP secret can't be hashed — verifying a code requires computing one from
the secret, which a one-way hash makes impossible. This is the same trust
boundary the rest of this product's data already sits behind (task content,
private notes, comments are all plaintext in the same database); encrypting
this one column would need its own key-management story — generation, a new
required `.env` var, rotation — for a bar this product doesn't otherwise
hold anywhere else. If that bar changes, this column is the first thing to
revisit.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MfaTotpDevice(Base):
    __tablename__ = "mfa_totp_devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfaBackupCode(Base):
    """Same "plaintext exists once" rule as `PersonalAccessToken`
    (models/token.py) — only `code_hash` is stored, via the same
    `services.tokens.hash_token`.

    `used_at` rather than a boolean: a used code is redeemed exactly once,
    and `services/mfa.py`'s `redeem_backup_code` claims one with a single
    `UPDATE ... WHERE code_hash = ... AND used_at IS NULL RETURNING id` — the
    same claim-not-select-then-update shape `reminders.claim` already uses,
    so two racing submits of the same code can't both succeed.
    """

    __tablename__ = "mfa_backup_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
