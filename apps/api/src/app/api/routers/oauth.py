"""OAuth 2.1: Dynamic Client Registration, the authorize hand-off, and the
token endpoint. Thin — every rule lives in `services/oauth.py`.

`/register`, `/token` and `/revoke` are unauthenticated at the FastAPI level
(no `CurrentUser`) on purpose: a client registers and exchanges codes for
itself, not as any particular person. `/authorize/preview` is the same,
mirroring `GET /invites/{token}` — someone deciding whether to authorize an
app usually hasn't signed in on this device yet. Only `/authorize/decision`
needs `CurrentUser`, because granting access *is* an action taken by a
signed-in person.

`/token` and `/revoke` use form-encoded bodies, not JSON — RFC 6749 and
RFC 7009 both require it, and every real OAuth client sends it that way.
"""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, status
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.provider import AuthorizeError, RegistrationError, TokenError
from mcp.shared.auth import OAuthClientMetadata
from pydantic import BaseModel
from starlette.responses import JSONResponse

from app.api.deps import CurrentUser, DbSession
from app.services import oauth as oauth_service

router = APIRouter(prefix="/oauth", tags=["oauth"])


def _error(exc: RegistrationError | AuthorizeError | TokenError, *, status_code: int = 400):
    code = 401 if getattr(exc, "error", None) == "invalid_client" else status_code
    return JSONResponse(
        {"error": exc.error, "error_description": exc.error_description}, status_code=code
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(db: DbSession, metadata: OAuthClientMetadata):
    """Dynamic Client Registration (RFC 7591) — no admin step, see
    `services/oauth.py::register_client`."""
    try:
        info = await oauth_service.register_client(db, metadata)
    except RegistrationError as exc:
        return _error(exc)
    return PydanticJSONResponse(info, status_code=status.HTTP_201_CREATED)


class AuthorizePreviewOut(BaseModel):
    client_name: str
    scope: str


@router.get("/authorize/preview", response_model=AuthorizePreviewOut)
async def authorize_preview(
    db: DbSession,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    response_type: str = "code",
    code_challenge_method: str = "S256",
    resource: str | None = None,
):
    """What the consent screen needs to render — unauthenticated, the same
    reasoning `GET /invites/{token}` already documents. Never redirects on
    failure: the redirect target isn't trusted until this has passed."""
    try:
        client = await oauth_service.preview_authorize(
            db,
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
        )
    except AuthorizeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": exc.error, "error_description": exc.error_description},
        ) from exc
    return AuthorizePreviewOut(client_name=client.client_name, scope=client.scope)


class AuthorizeDecisionIn(BaseModel):
    client_id: str
    redirect_uri: str
    code_challenge: str
    response_type: str = "code"
    code_challenge_method: str = "S256"
    state: str | None = None
    resource: str | None = None
    allow: bool
    # What the person consenting picked — clamped server-side to the
    # client's own registered ceiling, never trusted outright.
    scope: str = "read"


class AuthorizeDecisionOut(BaseModel):
    redirect_to: str


@router.post("/authorize/decision", response_model=AuthorizeDecisionOut)
async def authorize_decision(body: AuthorizeDecisionIn, user: CurrentUser, db: DbSession):
    """The consent decision. Re-validates everything server-side — the SPA's
    echoed params are never trusted outright — and returns the URL to send
    the browser to next."""
    try:
        redirect_to = await oauth_service.decide(
            db,
            user,
            client_id=body.client_id,
            redirect_uri=body.redirect_uri,
            response_type=body.response_type,
            code_challenge=body.code_challenge,
            code_challenge_method=body.code_challenge_method,
            state=body.state,
            resource=body.resource,
            allow=body.allow,
            scope=body.scope,
        )
    except AuthorizeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": exc.error, "error_description": exc.error_description},
        ) from exc
    return AuthorizeDecisionOut(redirect_to=redirect_to)


@router.post("/token")
async def token(
    db: DbSession,
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    client_secret: Annotated[str | None, Form()] = None,
    code: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
    scope: Annotated[str | None, Form()] = None,
    resource: Annotated[str | None, Form()] = None,
):
    try:
        client = await oauth_service.authenticate_client(
            db, client_id=client_id, client_secret=client_secret
        )
        if grant_type == "authorization_code":
            if not code or not redirect_uri or not code_verifier:
                raise TokenError(
                    "invalid_request", "code, redirect_uri and code_verifier are required"
                )
            result = await oauth_service.redeem_code(
                db,
                client=client,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
                resource=resource,
            )
        elif grant_type == "refresh_token":
            if not refresh_token:
                raise TokenError("invalid_request", "refresh_token is required")
            result = await oauth_service.redeem_refresh_token(
                db, client=client, refresh_token=refresh_token, scope=scope
            )
        else:
            raise TokenError("unsupported_grant_type", f"unsupported grant_type: {grant_type}")
    except TokenError as exc:
        return _error(exc)
    return PydanticJSONResponse(result)


@router.post("/revoke")
async def revoke(
    db: DbSession,
    token: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    client_secret: Annotated[str | None, Form()] = None,
    token_type_hint: Annotated[str | None, Form()] = None,
):
    """RFC 7009 — 200 regardless of whether the token existed; only a client
    authentication failure gets a real error."""
    try:
        client = await oauth_service.authenticate_client(
            db, client_id=client_id, client_secret=client_secret
        )
    except TokenError as exc:
        return _error(exc)
    await oauth_service.revoke_token(db, client=client, token=token)
    return JSONResponse({})
