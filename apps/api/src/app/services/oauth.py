"""OAuth 2.1 for MCP connectors — Dynamic Client Registration, PKCE-only
authorization codes, and rotating refresh tokens.

Hand-rolled rather than SuperTokens' `OAuth2Provider`: that recipe is a paid
add-on on the self-hosted core (a license key activated against
SuperTokens' own license servers), and even paid for, its "create a client"
operation is an *admin*-authenticated API call — not the public self-service
registration Claude.ai and ChatGPT's own MCP connectors actually need at
connect time. Same call this codebase already made for MFA
(`services/mfa.py`, on `pyotp`, after SuperTokens' MFA recipe returned a 402).

No new dependency either: `mcp` is already a mandatory dependency of this
project's own MCP server, and it ships RFC-correct wire-format models
(`mcp.shared.auth`) and the exact resource-server verification primitive
(`mcp.server.auth.provider.TokenVerifier`) this module needs. Everything
*else* here — client registration, PKCE, code and token issuance — is plain
`async def`s against SQLAlchemy, the identical idiom `services/tokens.py`
already uses for personal access tokens; every bearer secret is hashed with
the same `hash_token` (SHA-256, no bcrypt — these are 256-bit random
secrets, not human-chosen passwords, so there's nothing to brute-force).

## Four rules

1. **A client is public unless it proves otherwise.** Dynamic Client
   Registration has no admin step, so most callers here self-registered
   with no way to keep a secret — `client_secret_hash` is NULL, and PKCE is
   the whole proof of possession. OAuth 2.1's own preferred shape.

2. **Every code and refresh token is claimed, not read then trusted.**
   `redeem_code` and `redeem_refresh_token` both use the identical
   `UPDATE ... WHERE ... RETURNING` shape `reminders.claim` and
   `exports.claim_expired` already use — a plain SELECT followed by an
   UPDATE would leave a window where two racing requests both succeed,
   which for a refresh token is exactly the reuse this module is supposed
   to catch.

3. **A rotated refresh token that gets presented again is treated as
   theft.** `replaced_at` is set, not the row deleted, specifically so a
   second presentation of an already-rotated token can be recognised as
   reuse rather than just "unknown token" — and the whole grant is revoked
   defensively when that happens.

4. **A grant's scope is a ceiling, not a promise.** `OAuthClient.scope` is
   what a client may ever be granted; the person consenting can narrow it
   further at `/oauth/authorize`, and whatever they chose is copied onto
   each `OAuthAccessToken` *at issuance* — a later re-consent (or a client
   asking for more later) never reaches back into a token already handed
   out.

## Resource indicators (RFC 8707)

This deployment has exactly one resource server: `f"{SITE_URL}/mcp"`. A
`resource` parameter that doesn't match it is rejected outright; one that's
absent is accepted leniently, since some client libraries still omit it
despite the spec's SHOULD. There is no real cross-resource audience
enforcement beyond that string match — building it for a product with one
API would be speculative, and this is a decision, not a gap nobody noticed.
"""

import hashlib
import hmac
import secrets
import uuid
from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from fastapi import HTTPException
from fastapi import status as http_status
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizeError,
    RegistrationError,
    TokenError,
    TokenVerifier,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import SessionLocal
from app.models import OAuthAccessToken, OAuthAuthorizationCode, OAuthClient, OAuthGrant, User
from app.models.oauth import AUTH_METHOD_NONE, AUTH_METHOD_POST, AUTH_METHODS
from app.models.token import SCOPE_READ, SCOPE_WRITE, SCOPES, TOKEN_PREFIX
from app.services import tokens as tokens_service
from app.services.tokens import TOUCH_EVERY, hash_token

CODE_TTL = timedelta(minutes=2)
ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=180)

# Recognisable in a log, same reasoning `TOKEN_PREFIX` already documents.
ACCESS_TOKEN_PREFIX = "ayo_"
REFRESH_TOKEN_PREFIX = "ayr_"

SUPPORTED_GRANT_TYPES = frozenset({"authorization_code", "refresh_token"})


def _canonical_resource() -> str:
    return f"{settings.site_url.rstrip('/')}/mcp"


def _pkce_ok(verifier: str, challenge: str) -> bool:
    """S256 only — OAuth 2.1 drops the `plain` method entirely."""
    if not verifier or not challenge:
        return False
    digest = hashlib.sha256(verifier.encode()).digest()
    computed = urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(computed, challenge)


def _clamp_scope(requested: str, *, ceiling: str) -> str:
    """Never grants more than the client's own registered ceiling, however
    generously the person consenting tries to."""
    if requested not in SCOPES:
        requested = SCOPE_READ
    if ceiling == SCOPE_READ:
        return SCOPE_READ
    return requested


# --- client registration -----------------------------------------------------


async def _get_client(db: AsyncSession, client_id: str) -> OAuthClient | None:
    try:
        cid = uuid.UUID(client_id)
    except ValueError:
        return None
    return await db.get(OAuthClient, cid)


async def register_client(
    db: AsyncSession, metadata: OAuthClientMetadata
) -> OAuthClientInformationFull:
    """Dynamic Client Registration (RFC 7591) — unauthenticated, on purpose:
    the whole point is a client can register itself the moment someone adds
    the connector, with no admin step."""
    redirect_uris = [str(u) for u in (metadata.redirect_uris or [])]
    if not redirect_uris:
        raise RegistrationError("invalid_redirect_uri", "at least one redirect_uri is required")
    for uri in redirect_uris:
        parsed = urlparse(uri)
        localhost = parsed.hostname in ("localhost", "127.0.0.1")
        if parsed.scheme == "https" or (parsed.scheme == "http" and localhost):
            continue
        raise RegistrationError(
            "invalid_redirect_uri", f"{uri} must be https, or http on localhost"
        )

    auth_method = metadata.token_endpoint_auth_method or AUTH_METHOD_NONE
    if auth_method not in AUTH_METHODS:
        raise RegistrationError(
            "invalid_client_metadata",
            f"unsupported token_endpoint_auth_method: {auth_method}",
        )

    requested_grants = set(metadata.grant_types or ["authorization_code", "refresh_token"])
    if not requested_grants <= SUPPORTED_GRANT_TYPES:
        raise RegistrationError(
            "invalid_client_metadata", "only authorization_code and refresh_token are supported"
        )

    scope = SCOPE_WRITE if "write" in (metadata.scope or "").split() else SCOPE_READ

    secret_plain = None
    secret_hash = None
    if auth_method == AUTH_METHOD_POST:
        secret_plain = secrets.token_urlsafe(32)
        secret_hash = hash_token(secret_plain)

    row = OAuthClient(
        client_secret_hash=secret_hash,
        client_name=(metadata.client_name or "Unnamed app").strip()[:200],
        redirect_uris=redirect_uris,
        token_endpoint_auth_method=auth_method,
        grant_types=" ".join(sorted(requested_grants)),
        scope=scope,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return OAuthClientInformationFull(
        client_id=str(row.id),
        client_secret=secret_plain,
        client_id_issued_at=int(row.created_at.timestamp()),
        redirect_uris=redirect_uris,
        token_endpoint_auth_method=auth_method,
        grant_types=sorted(requested_grants),
        scope=scope,
        client_name=row.client_name,
    )


async def authenticate_client(
    db: AsyncSession, *, client_id: str, client_secret: str | None
) -> OAuthClient:
    """The `/token` endpoint's own client check — a public client proves
    nothing here (PKCE already did that); a confidential one must present
    the secret it was issued at registration."""
    client = await _get_client(db, client_id)
    if client is None:
        raise TokenError("invalid_client", "unknown client")
    if client.token_endpoint_auth_method == AUTH_METHOD_POST:
        if not client_secret or hash_token(client_secret) != client.client_secret_hash:
            raise TokenError("invalid_client", "bad client credentials")
    return client


# --- authorize -----------------------------------------------------------------


async def preview_authorize(
    db: AsyncSession,
    *,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str | None = None,
) -> OAuthClient:
    """Validates a `/authorize` request without ever redirecting on failure
    — the redirect target isn't trusted until *this* has passed, so a bad
    request is a 400 shown on the page, the classic open-redirect trap
    avoided by construction."""
    client = await _get_client(db, client_id)
    if client is None:
        raise AuthorizeError("invalid_request", "unknown client")
    if redirect_uri not in client.redirect_uris:
        raise AuthorizeError("invalid_request", "redirect_uri is not registered for this client")
    if response_type != "code":
        raise AuthorizeError("unsupported_response_type", "only 'code' is supported")
    if code_challenge_method != "S256":
        raise AuthorizeError("invalid_request", "only S256 PKCE is supported")
    if not code_challenge:
        raise AuthorizeError("invalid_request", "code_challenge is required")
    if resource is not None and resource.rstrip("/") != _canonical_resource().rstrip("/"):
        raise AuthorizeError("invalid_target", "unknown resource")
    return client


async def _upsert_grant(
    db: AsyncSession, client: OAuthClient, user: User, *, scope: str
) -> OAuthGrant:
    existing = (
        await db.execute(
            select(OAuthGrant).where(
                OAuthGrant.client_id == client.id, OAuthGrant.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.scope = scope
        await db.commit()
        await db.refresh(existing)
        return existing
    grant = OAuthGrant(client_id=client.id, user_id=user.id, scope=scope)
    db.add(grant)
    await db.commit()
    await db.refresh(grant)
    return grant


async def decide(
    db: AsyncSession,
    user: User,
    *,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    code_challenge: str,
    code_challenge_method: str,
    state: str | None,
    resource: str | None,
    allow: bool,
    scope: str,
) -> str:
    """The consent decision. Re-validates everything from scratch — never
    trusts params the SPA merely echoed back — and returns the URL to
    redirect the browser to."""
    client = await preview_authorize(
        db,
        client_id=client_id,
        redirect_uri=redirect_uri,
        response_type=response_type,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        resource=resource,
    )
    if not allow:
        return construct_redirect_uri(redirect_uri, error="access_denied", state=state)

    granted_scope = _clamp_scope(scope, ceiling=client.scope)
    grant = await _upsert_grant(db, client, user, scope=granted_scope)

    code_plain = secrets.token_urlsafe(32)
    row = OAuthAuthorizationCode(
        code_hash=hash_token(code_plain),
        client_id=client.id,
        grant_id=grant.id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        resource=resource,
        expires_at=datetime.now(UTC) + CODE_TTL,
    )
    db.add(row)
    await db.commit()
    return construct_redirect_uri(redirect_uri, code=code_plain, state=state)


# --- token issuance --------------------------------------------------------------


async def _issue_tokens(
    db: AsyncSession, grant: OAuthGrant, *, resource: str | None
) -> OAuthToken:
    access_plain = ACCESS_TOKEN_PREFIX + secrets.token_urlsafe(32)
    refresh_plain = REFRESH_TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    row = OAuthAccessToken(
        grant_id=grant.id,
        access_token_hash=hash_token(access_plain),
        refresh_token_hash=hash_token(refresh_plain),
        scope=grant.scope,
        resource=resource,
        access_token_expires_at=now + ACCESS_TOKEN_TTL,
        refresh_token_expires_at=now + REFRESH_TOKEN_TTL,
    )
    db.add(row)
    await db.commit()
    return OAuthToken(
        access_token=access_plain,
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
        scope=grant.scope,
        refresh_token=refresh_plain,
    )


async def redeem_code(
    db: AsyncSession,
    *,
    client: OAuthClient,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    resource: str | None,
) -> OAuthToken:
    """Claims the code with one `UPDATE ... RETURNING` — see this module's
    own rule 2. A failed PKCE or redirect_uri check below still leaves the
    code burned: a failed check must never leave a replayable code sitting
    around for a second attempt."""
    now = datetime.now(UTC)
    claimed = (
        await db.execute(
            update(OAuthAuthorizationCode)
            .where(
                OAuthAuthorizationCode.code_hash == hash_token(code),
                OAuthAuthorizationCode.consumed_at.is_(None),
                OAuthAuthorizationCode.expires_at > now,
                OAuthAuthorizationCode.client_id == client.id,
            )
            .values(consumed_at=now)
            .returning(
                OAuthAuthorizationCode.grant_id,
                OAuthAuthorizationCode.redirect_uri,
                OAuthAuthorizationCode.code_challenge,
                OAuthAuthorizationCode.resource,
            )
        )
    ).first()
    await db.commit()
    if claimed is None:
        raise TokenError("invalid_grant", "unknown, expired or already-used code")
    grant_id, stored_redirect_uri, code_challenge, stored_resource = claimed
    if stored_redirect_uri != redirect_uri:
        raise TokenError("invalid_grant", "redirect_uri does not match")
    if not _pkce_ok(code_verifier, code_challenge):
        raise TokenError("invalid_grant", "code_verifier does not match")
    if resource is not None and stored_resource is not None and resource != stored_resource:
        raise TokenError("invalid_target", "resource does not match")

    grant = await db.get(OAuthGrant, grant_id)
    assert grant is not None  # FK guarantees this; codes are deleted with their grant
    return await _issue_tokens(db, grant, resource=stored_resource)


async def redeem_refresh_token(
    db: AsyncSession, *, client: OAuthClient, refresh_token: str, scope: str | None = None
) -> OAuthToken:
    """Rotates both tokens on every use. If the presented refresh token
    turns out to already be `replaced_at` (rule 3), the whole grant is
    revoked rather than just this one request refused."""
    token_hash = hash_token(refresh_token)
    now = datetime.now(UTC)
    own_grants = select(OAuthGrant.id).where(OAuthGrant.client_id == client.id)

    claimed = (
        await db.execute(
            update(OAuthAccessToken)
            .where(
                OAuthAccessToken.refresh_token_hash == token_hash,
                OAuthAccessToken.replaced_at.is_(None),
                or_(
                    OAuthAccessToken.refresh_token_expires_at.is_(None),
                    OAuthAccessToken.refresh_token_expires_at > now,
                ),
                OAuthAccessToken.grant_id.in_(own_grants),
            )
            .values(replaced_at=now)
            .returning(OAuthAccessToken.grant_id, OAuthAccessToken.resource)
        )
    ).first()
    await db.commit()

    if claimed is None:
        stale = (
            await db.execute(
                select(OAuthAccessToken.grant_id).where(
                    OAuthAccessToken.refresh_token_hash == token_hash,
                    OAuthAccessToken.replaced_at.is_not(None),
                    OAuthAccessToken.grant_id.in_(own_grants),
                )
            )
        ).scalar_one_or_none()
        if stale is not None:
            await db.execute(delete(OAuthGrant).where(OAuthGrant.id == stale))
            await db.commit()
        raise TokenError("invalid_grant", "refresh token is invalid, expired or already used")

    grant_id, resource = claimed
    grant = await db.get(OAuthGrant, grant_id)
    assert grant is not None
    return await _issue_tokens(db, grant, resource=resource)


async def revoke_token(db: AsyncSession, *, client: OAuthClient, token: str) -> None:
    """RFC 7009 — always succeeds, even for an unknown or already-revoked
    token, and only ever touches tokens issued to the calling client."""
    token_hash = hash_token(token)
    own_grants = select(OAuthGrant.id).where(OAuthGrant.client_id == client.id)
    await db.execute(
        delete(OAuthAccessToken).where(
            or_(
                OAuthAccessToken.access_token_hash == token_hash,
                OAuthAccessToken.refresh_token_hash == token_hash,
            ),
            OAuthAccessToken.grant_id.in_(own_grants),
        )
    )
    await db.commit()


# --- the account screen ------------------------------------------------------


async def my_grants(db: AsyncSession, user: User) -> list[tuple[OAuthGrant, OAuthClient]]:
    rows = (
        await db.execute(
            select(OAuthGrant, OAuthClient)
            .join(OAuthClient, OAuthClient.id == OAuthGrant.client_id)
            .where(OAuthGrant.user_id == user.id)
            .order_by(OAuthGrant.created_at.desc())
        )
    ).all()
    return [(g, c) for g, c in rows]


async def revoke_grant(db: AsyncSession, user: User, grant_id: uuid.UUID) -> None:
    """Yours, or it doesn't exist — 404, not 403, the identical reasoning
    `tokens_service.revoke` already uses for a personal access token."""
    grant = (
        await db.execute(
            select(OAuthGrant).where(OAuthGrant.id == grant_id, OAuthGrant.user_id == user.id)
        )
    ).scalar_one_or_none()
    if grant is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="not found")
    await db.delete(grant)
    await db.commit()


# --- resource-server verification, for app/mcp/server.py -----------------------


class OAuthTokenVerifier(TokenVerifier):
    """The bridge `app/mcp/server.py` wires into its transport-level auth
    middleware (see `main.py`). Accepts either credential shape an MCP
    caller may present — a personal access token or an OAuth access token —
    normalising both to the SDK's own `AccessToken` shape. This is where
    "accept both" actually lives: once per HTTP request at the transport
    layer, not once per tool call.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        async with SessionLocal() as db:
            if token.startswith(TOKEN_PREFIX):
                found = await tokens_service.authenticate(db, f"Bearer {token}")
                if found is None:
                    return None
                user, pat = found
                return AccessToken(
                    token=token, client_id="pat", scopes=[pat.scope], subject=str(user.id)
                )

            if not token.startswith(ACCESS_TOKEN_PREFIX):
                return None
            now = datetime.now(UTC)
            row = (
                await db.execute(
                    select(OAuthAccessToken, OAuthGrant)
                    .join(OAuthGrant, OAuthGrant.id == OAuthAccessToken.grant_id)
                    .where(OAuthAccessToken.access_token_hash == hash_token(token))
                )
            ).first()
            if row is None:
                return None
            access_row, grant = row
            if access_row.access_token_expires_at < now:
                return None
            if access_row.last_used_at is None or now - access_row.last_used_at > TOUCH_EVERY:
                access_row.last_used_at = now
                await db.commit()
            return AccessToken(
                token=token,
                client_id=str(access_row.grant_id),
                scopes=access_row.scope.split(),
                expires_at=int(access_row.access_token_expires_at.timestamp()),
                subject=str(grant.user_id),
            )
