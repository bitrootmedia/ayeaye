"""ASGI entrypoint — wiring only.

Routes live in app/api/routers/, business logic in app/services/. This file
just assembles them, so it shouldn't grow as the API does.
"""

from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.middleware.authentication import AuthenticationMiddleware
from supertokens_python import get_all_cors_headers
from supertokens_python.framework.fastapi import get_middleware

from app.api.router import api_router
from app.api.routers import health, wellknown
from app.core.config import settings
from app.core.lifespan import lifespan
from app.core.logging import configure_logging
from app.mcp.server import mcp, token_verifier
from app.security.authn import init_auth


async def _mcp_asgi(scope, receive, send):
    """Hand the request straight to the MCP transport."""
    await mcp.session_manager.handle_request(scope, receive, send)


class MCPPath:
    """Make `/mcp` and `/mcp/` the same endpoint.

    Starlette's `Mount` only ever matches a *sub*-path, so mounting at `/mcp`
    leaves the real endpoint at `/mcp/` and a POST to `/mcp` gets a 307. The
    MCP client doesn't follow it, and the failure surfaces as the wonderfully
    unhelpful "Unexpected content type:" — the empty body of a redirect.

    Configuration is a URL somebody types once, so it has to work with and
    without the slash. Done here rather than in Caddy so the API is correct on
    its own port too.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/mcp":
            scope = {**scope, "path": "/mcp/", "raw_path": b"/mcp/"}
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    configure_logging()
    # SuperTokens must be configured before get_middleware() /
    # get_all_cors_headers() are called below.
    init_auth()

    # Docs live under /api, not FastAPI's own default of the bare root —
    # Caddy only ever proxies /api/*, /mcp*, /health and /media/*, and the
    # API's own port is published in dev alone (see CLAUDE.md's "Running and
    # testing"). Left at the default, interactive docs would work while
    # developing and be genuinely unreachable on any real deployment: a
    # request to the bare /docs falls through Caddy's catch-all to the SPA,
    # which has no route there either. Under /api, the same URL — SITE_URL +
    # /api/docs — works identically in dev and in production, no flag to
    # remember, the same "one origin" reasoning everything else here follows.
    app = FastAPI(
        title=f"{settings.brand_name} API",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # SuperTokens' own middleware must be added before CORS so its auth routes
    # (under /api/auth/*) get session/refresh handling.
    app.add_middleware(get_middleware())
    app.add_middleware(
        CORSMiddleware,
        # One origin, so this is a formality — the SPA and the API are
        # same-origin behind Caddy in dev and in production alike. It's here
        # for anyone who bypasses Caddy and hits the API port directly.
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "PUT", "POST", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["Content-Type"] + get_all_cors_headers(),
    )

    # /health stays at the root for container and load-balancer probes;
    # everything else is served under /api. The two OAuth discovery
    # documents stay at the root too — RFC 8414/9728 fix their paths under
    # /.well-known/, which isn't something this app can move under /api.
    app.include_router(health.router)
    app.include_router(wellknown.router)
    app.include_router(api_router, prefix="/api")

    # The MCP endpoint, for somebody's own assistant. Its own ASGI app rather
    # than a router: it speaks JSON-RPC over a streaming transport, which is
    # not something FastAPI's routing has an opinion about.
    #
    # Authenticated per call by a personal access token, **not** by the
    # session cookie — see app/mcp/server.py.
    #
    # **Mounted as a bare ASGI handler, not as the SDK's Starlette wrapper.**
    # That wrapper puts its route at "/", so mounting it at `/mcp` makes the
    # real endpoint `/mcp/` and a POST to `/mcp` gets a 307. Clients post to
    # the URL they were given, and the redirect surfaces as the wonderfully
    # unhelpful "Unexpected content type:".
    # **DNS-rebinding protection has to know our hostname.** It defaults to
    # allowing 127.0.0.1 only, and behind Caddy the Host header is whatever
    # SITE_URL says — so without this every call is refused with "Invalid Host
    # header", which reads like a proxy misconfiguration rather than a setting
    # in this file.
    #
    # SITE_URL is the single source of the hostname everywhere else too, so
    # there is nothing new for a self-hoster to configure.
    host = urlparse(settings.site_url).netloc or "localhost"
    mcp.streamable_http_app(  # also builds the session manager, lazily created
        # **Stateless, and that is not a shortcut.** A stateful transport
        # hands the client a session id and expects every later call to come
        # back to the worker that issued it — but uvicorn runs several, and
        # nothing is shared between them. It is the same reasoning that puts
        # the realtime fan-out through Redis; here the cheaper answer is to
        # need no session at all, since every call authenticates itself.
        stateless_http=True,
        # Plain JSON rather than an SSE frame per response. Nothing here
        # streams or pushes, and one fewer encoding is one fewer thing for a
        # proxy to buffer.
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[host, host.split(":")[0], "localhost", "127.0.0.1"],
            allowed_origins=[settings.site_url, "*"],
        )
    )
    # **A missing or bad token must get a real 401, not a 200 with an error
    # buried in a JSON-RPC result.** `_mcp_asgi` alone can't do that — a
    # `Denied` raised inside `app/mcp/server.py`'s `_caller()` is caught by
    # the MCP protocol itself and turned into an ordinary tool-error result,
    # HTTP 200 throughout. An OAuth-aware client (claude.ai's connector,
    # ChatGPT's) never sees that; it needs `WWW-Authenticate` on its very
    # first touch of `/mcp` to know to go start OAuth at all. Composed by
    # hand around the bare `_mcp_asgi` — not via the SDK's own
    # `streamable_http_app()` return value, which is discarded above for
    # the `/mcp` vs `/mcp/` reason `MCPPath` already explains, so its own
    # auth wiring never runs either way.
    resource_metadata_url = build_resource_metadata_url(AnyHttpUrl(f"{settings.site_url}/mcp"))
    mcp_endpoint = RequireAuthMiddleware(
        _mcp_asgi, required_scopes=[], resource_metadata_url=resource_metadata_url
    )
    mcp_endpoint = AuthContextMiddleware(mcp_endpoint)
    mcp_endpoint = AuthenticationMiddleware(mcp_endpoint, backend=BearerAuthBackend(token_verifier))
    app.mount("/mcp", mcp_endpoint)
    app.add_middleware(MCPPath)

    return app


app = create_app()
