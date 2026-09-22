"""Swagger UI and ReDoc, hand-mounted for one reason: the favicon.

FastAPI generates both pages itself when `docs_url`/`redoc_url` are set, and
both generated pages point their `<link rel="icon">` at
`https://fastapi.tiangolo.com/img/favicon.png` — somebody else's logo, and a
third-party request from an installation whose whole premise is that it runs
on your own hardware. There is no argument for it on `FastAPI(...)`; the
favicon is a parameter of `get_swagger_ui_html`, so having our own means
owning the two routes.

**`/favicon.svg` is the SPA's own file, not a copy.** Single origin is what
makes that a URL rather than a build step: Caddy's catch-all serves the web
app, so the same drawing the browser tab already shows is one fetch away on
the same hostname. Shipping a second, API-side copy is exactly the "second,
rasterised copy that quietly stops matching" the favicon's own comment
exists to rule out. Somebody hitting the API's own port directly gets a
default icon instead — that port is published in dev alone, and "correct
through Caddy" is the same bargain every neighbour of this file makes.

The URLs are unchanged: `/api/docs` and `/api/redoc`, from being mounted on
`api_router` like everything else, for the reason `main.py` gives for moving
them off FastAPI's bare-root default in the first place.

**Swagger's OAuth2 redirect helper is deliberately not carried over.** FastAPI
registers it at `/docs/oauth2-redirect` — a bare-root path, which Caddy hands
to the SPA, so it has always answered with the app's own HTML rather than the
page Swagger expects. Nothing has ever reached it: this API declares no OAuth2
security scheme at all, so Swagger UI draws no Authorize button to start the
flow. OAuth 2.1 here is for MCP clients, which never see this page.
"""

from fastapi import APIRouter
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse

from app.core.config import settings

# Written down once, here, and read by `main.py` when it configures the
# schema itself: the two pages below fetch it, so a move that changed one
# and not the other would leave the docs rendering an error where the API
# should be.
OPENAPI_URL = "/api/openapi.json"

# The SPA's own tile, served from the same origin by Caddy's catch-all.
FAVICON_URL = "/favicon.svg"

# `include_in_schema=False` for the same reason FastAPI's own generated
# routes carry it: the docs are not part of the API they document.
router = APIRouter(include_in_schema=False)


@router.get("/docs")
async def swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=OPENAPI_URL,
        title=f"{settings.brand_name} API - Swagger UI",
        swagger_favicon_url=FAVICON_URL,
    )


@router.get("/redoc")
async def redoc() -> HTMLResponse:
    return get_redoc_html(
        openapi_url=OPENAPI_URL,
        title=f"{settings.brand_name} API - ReDoc",
        redoc_favicon_url=FAVICON_URL,
    )
