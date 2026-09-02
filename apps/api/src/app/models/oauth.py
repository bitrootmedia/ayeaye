"""OAuth 2.1, so Claude.ai and ChatGPT's own "connect an MCP server" flows can
reach `/mcp` without anyone pasting a personal access token.

    users ──► oauth_grants ──► oauth_access_tokens
                  ▲    ▲
    oauth_clients ┘    └── oauth_authorization_codes

Hand-rolled — see `services/oauth.py`'s own docstring for why (SuperTokens'
`OAuth2Provider` is a paid core add-on that only offers admin-authenticated
client creation anyway, not the public self-registration these clients need).
No new dependency: the wire-format models and the resource-server token
verification are `mcp.shared.auth` / `mcp.server.auth.provider`, already a
mandatory dependency of this project's own MCP server.

Every bearer secret here is hashed the same way `PersonalAccessToken` already
is — SHA-256 via `services.tokens.hash_token`, no second scheme. A client's
own secret is the one exception mirrored from that same file's reasoning:
`client_secret_hash` is nullable because most clients here are *public*
(self-registered via Dynamic Client Registration, PKCE-only, no way to keep a
secret) — OAuth 2.1's own preferred shape for exactly this situation.
"""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import func as sa_func
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.token import SCOPE_READ, SCOPES

# Public (no secret — PKCE carries the proof instead) or confidential (a
# secret, shown once like everything else here). "none" is RFC 7591's own
# name for `token_endpoint_auth_method: public`, kept verbatim so the value
# stored here matches the wire value a client sent, with nothing translated
# in between to drift.
AUTH_METHOD_NONE = "none"
AUTH_METHOD_POST = "client_secret_post"
AUTH_METHODS = (AUTH_METHOD_NONE, AUTH_METHOD_POST)


class OAuthClient(Base):
    """One row per Dynamically-Registered client. There is no admin step —
    see `services/oauth.py::register_client`."""

    __tablename__ = "oauth_clients"
    __table_args__ = (
        CheckConstraint(
            f"token_endpoint_auth_method IN {AUTH_METHODS!r}",
            name="ck_oauth_clients_auth_method",
        ),
        CheckConstraint(f"scope IN {SCOPES!r}", name="ck_oauth_clients_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
    )
    # SHA-256, same as a personal access token. NULL for a public client.
    client_secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # From DCR's `client_name`, or a placeholder — shown on the consent
    # screen and the Account "Connected apps" list, so it can't be blank.
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    token_endpoint_auth_method: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=AUTH_METHOD_NONE
    )
    # Space-delimited, matching the OAuth wire format exactly — nothing here
    # ever splits or filters on it in SQL, so there's no reason to normalise
    # it into a second shape.
    grant_types: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default="authorization_code refresh_token"
    )
    # The ceiling this client may ever be granted, regardless of what any one
    # person consents to — reuses the identical read/write split
    # `PersonalAccessToken.scope` already uses.
    scope: Mapped[str] = mapped_column(String(32), nullable=False, server_default=SCOPE_READ)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )


class OAuthGrant(Base):
    """"This person let this app in" — the unit the Account screen revokes.
    Revoking cascades to every access/refresh token issued under it."""

    __tablename__ = "oauth_grants"
    __table_args__ = (
        UniqueConstraint("client_id", "user_id", name="uq_oauth_grants_client_user"),
        CheckConstraint(f"scope IN {SCOPES!r}", name="ck_oauth_grants_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # What was actually allowed at consent — may be narrower than the
    # client's own ceiling. Copied onto each token at issuance, so revoking
    # write and re-consenting to read-only never reaches back into a token
    # already handed out; only a fresh one carries the new value.
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )


class OAuthAuthorizationCode(Base):
    """Single-use, minutes-lived. `services.oauth.redeem_code` claims one
    with `UPDATE ... WHERE consumed_at IS NULL ... RETURNING`, the identical
    race-safe shape `reminders.claim` already uses — never select-then-
    update, which would let two racing redemptions both succeed."""

    __tablename__ = "oauth_authorization_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("oauth_clients.id", ondelete="CASCADE"), nullable=False
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("oauth_grants.id", ondelete="CASCADE"), nullable=False
    )
    # The exact value from the /authorize request, re-checked byte-for-byte
    # at redemption — one of several checks that stop a stolen code being
    # replayed through a different client.
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    # S256 only — OAuth 2.1 drops the `plain` method entirely.
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    # RFC 8707. NULL when the client didn't send one — see
    # services/oauth.py's own docstring for why that's accepted leniently.
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )


class OAuthAccessToken(Base):
    """One row per access+refresh pair. Rotated, not reused: redeeming the
    refresh token sets `replaced_at` on this row and inserts a fresh one,
    which is what makes presenting an already-replaced refresh token
    detectable as reuse (see `services.oauth.redeem_refresh_token`) rather
    than silently accepted."""

    __tablename__ = "oauth_access_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa_text("uuidv7()")
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("oauth_grants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    access_token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # NULL once rotated away by a refresh — the row stays (for reuse
    # detection) but this half of it is spent.
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    # Copied from the grant *at issuance* — see OAuthGrant's own comment.
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A tidying-up aid, not an audit log — the identical once-a-minute
    # `TOUCH_EVERY` idiom `PersonalAccessToken.last_used_at` already uses.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
