"""OAuth discovery documents — RFC 8414 and RFC 9728.

Mounted at the bare root in `main.py`, the same tier as `/health`: these two
paths are spec-fixed under `/.well-known/`, not something this app can move
under `/api` the way everything else lives.

Reuses `mcp.shared.auth`'s own Pydantic models for both documents — correct
field names and serialization (`exclude_none`, via `PydanticJSONResponse`)
for free, rather than hand-typing RFC-shaped JSON.

`openid-configuration` is deliberately **not** served here — see
`infra/caddy/Caddyfile`, which keeps that one path 404ing forever. This is
an OAuth 2.1 authorization server issuing scoped API access tokens, not an
OIDC identity provider: no id_token, no "sign in with ayeaye". A 200 there
would claim a capability this server doesn't have.
"""

from fastapi import APIRouter
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata

from app.core.config import settings

router = APIRouter(tags=["oauth-discovery"])


def _site_url() -> str:
    return settings.site_url.rstrip("/")


@router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server_metadata():
    site = _site_url()
    metadata = OAuthMetadata(
        issuer=site,
        authorization_endpoint=f"{site}/oauth/authorize",
        token_endpoint=f"{site}/api/oauth/token",
        registration_endpoint=f"{site}/api/oauth/register",
        revocation_endpoint=f"{site}/api/oauth/revoke",
        scopes_supported=["read", "write"],
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["none", "client_secret_post"],
        code_challenge_methods_supported=["S256"],
    )
    return PydanticJSONResponse(metadata)


# Both the bare form and the RFC 9728 *path-inserted* form
# (`/.well-known/oauth-protected-resource/mcp`) — the exact request an
# OAuth-aware MCP connector makes, and the one a Caddy or app misconfiguration
# most easily 200s-with-the-wrong-thing instead of 404ing. See CLAUDE.md's
# OAuth section for the incident that made this worth spelling out.
@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
async def oauth_protected_resource_metadata():
    site = _site_url()
    metadata = ProtectedResourceMetadata(
        resource=f"{site}/mcp",
        authorization_servers=[site],
        scopes_supported=["read", "write"],
        resource_name="ayeayecaptain",
    )
    return PydanticJSONResponse(metadata)
