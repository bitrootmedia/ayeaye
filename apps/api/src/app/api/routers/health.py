from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness probe — no auth, no DB hit. Stays at the root (not under /api)
    for container and load-balancer checks, and Caddy routes it explicitly so
    an uptime monitor can't get a 200 from the SPA while the API is down."""
    return {"status": "ok"}
