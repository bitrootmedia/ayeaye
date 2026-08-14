"""Authentication: SuperTokens setup and identity lookups.

Answers "who is this user?" and nothing else. What they may do is decided by
organisation membership and grants — see services/access.py (Phase 3). There is
no policy engine and no staff tier; PLAN.md §2.1 explains why.
"""

from typing import Annotated

from fastapi import Depends
from supertokens_python import InputAppInfo, SupertokensConfig, init
from supertokens_python.asyncio import get_user
from supertokens_python.ingredients.emaildelivery.types import EmailDeliveryConfig
from supertokens_python.recipe import emailpassword, session
from supertokens_python.recipe.session import SessionContainer
from supertokens_python.recipe.session.framework.fastapi import verify_session

from app.core.config import settings
from app.security.email import MailerEmailDelivery

# The canonical "this request has a valid session" dependency. Declared here so
# everything shares one instance instead of building its own verifier.
VerifiedSession = Annotated[SessionContainer, Depends(verify_session())]


def init_auth() -> None:
    """Configure the SuperTokens SDK.

    Must run before `get_middleware()` / `get_all_cors_headers()` are called —
    see create_app(). Route dependencies (`verify_session()`) resolve the recipe
    lazily at request time, so import order elsewhere doesn't matter.
    """
    init(
        app_info=InputAppInfo(
            app_name=settings.brand_name,
            # One origin for both, because there is one origin for everything.
            api_domain=settings.api_domain,
            website_domain=settings.website_domain,
            # Everything the browser hits is under /api, so the auth routes
            # live at /api/auth and Caddy needs exactly one API rule.
            api_base_path="/api/auth",
            # One app, so one auth surface. The reference project had to rewrite
            # this per recipient because it had three; we don't.
            website_base_path="/auth",
        ),
        supertokens_config=SupertokensConfig(
            connection_uri=settings.supertokens_connection_uri,
            api_key=settings.supertokens_api_key or None,
        ),
        framework="fastapi",
        recipe_list=[
            session.init(),
            emailpassword.init(
                # Replaces SuperTokens' managed sending service: password-reset
                # mail goes out through our own SMTP, from our own domain.
                email_delivery=EmailDeliveryConfig(service=MailerEmailDelivery()),
            ),
        ],
        mode="asgi",
    )


async def get_user_email(user_id: str) -> str | None:
    """SuperTokens holds the email in its core, not in the session, so we look
    it up by user_id. `.emails` is a list under the account-linking model."""
    user = await get_user(user_id)
    return user.emails[0] if user and user.emails else None
