"""ASGI entrypoint — wiring only.

Routes live in app/api/routers/, business logic in app/services/. This file
just assembles them, so it shouldn't grow as the API does.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supertokens_python import get_all_cors_headers
from supertokens_python.framework.fastapi import get_middleware

from app.api.router import api_router
from app.api.routers import health
from app.core.config import settings
from app.core.lifespan import lifespan
from app.core.logging import configure_logging
from app.security.authn import init_auth


def create_app() -> FastAPI:
    configure_logging()
    # SuperTokens must be configured before get_middleware() /
    # get_all_cors_headers() are called below.
    init_auth()

    app = FastAPI(title=f"{settings.brand_name} API", lifespan=lifespan)

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
    # everything else is served under /api.
    app.include_router(health.router)
    app.include_router(api_router, prefix="/api")

    return app


app = create_app()
