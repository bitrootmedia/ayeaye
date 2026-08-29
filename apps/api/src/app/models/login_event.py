"""A record of every successful sign-in — no UI yet, just the history.

Deliberately **not** foreign-keyed to `users`: the local user row is created
lazily on first authenticated request (see `services/users.get_or_create`),
so on a brand-new signup this fires *before* that row exists. Keying on
`supertokens_user_id` — the identity SuperTokens already assigned by the time
a session is created — sidesteps the ordering problem entirely, and is a
plain indexed join to `users.supertokens_user_id` whenever something reads it.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LoginEvent(Base):
    __tablename__ = "login_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    supertokens_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # X-Forwarded-For first — Caddy fronts every request, so the socket peer
    # is Caddy's own container, not the visitor.
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
