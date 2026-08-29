"""Authentication: SuperTokens setup and identity lookups.

Answers "who is this user?" and nothing else. What they may do is decided by
organisation membership and grants — see services/access.py (Phase 3). There is
no policy engine and no staff tier; PLAN.md §2.1 explains why.
"""

import re
from typing import Annotated

from fastapi import Depends
from supertokens_python import InputAppInfo, SupertokensConfig, get_request_from_user_context, init
from supertokens_python.asyncio import get_user
from supertokens_python.ingredients.emaildelivery.types import EmailDeliveryConfig
from supertokens_python.recipe import emailpassword, session
from supertokens_python.recipe.emailpassword import InputFormField, InputSignUpFeature
from supertokens_python.recipe.emailpassword.constants import FORM_FIELD_PASSWORD_ID
from supertokens_python.recipe.session import SessionContainer
from supertokens_python.recipe.session.framework.fastapi import verify_session
from supertokens_python.recipe.session.interfaces import RecipeInterface
from supertokens_python.recipe.session.utils import SessionOverrideConfig

from app.core.config import settings
from app.security.email import MailerEmailDelivery

# The canonical "this request has a valid session" dependency. Declared here so
# everything shares one instance instead of building its own verifier.
VerifiedSession = Annotated[SessionContainer, Depends(verify_session())]

# SuperTokens' own default (8 characters, one letter, one digit) passes
# "aaaaaaa1" — length and mixed case are what actually resist guessing, and
# both are cheap to require. Stops short of demanding a symbol: that mostly
# trains people to write the password down rather than choose a better one.
MIN_PASSWORD_LENGTH = 10


async def strong_password_validator(value: str, _tenant_id: str) -> str | None:
    if len(value) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(value) >= 100:
        return "Password's length must be lesser than 100 characters"
    if not re.search(r"[a-z]", value):
        return "Include at least one lowercase letter."
    if not re.search(r"[A-Z]", value):
        return "Include at least one uppercase letter."
    if not re.search(r"[0-9]", value):
        return "Include at least one number."
    return None


def _client_ip(request) -> str | None:
    """The visitor's IP, not Caddy's own. `X-Forwarded-For` is what a
    reverse proxy sets, and single origin means Caddy fronts every request —
    the raw socket peer is always Caddy's container, never the visitor."""
    if request is None:
        return None
    forwarded = request.get_header("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    # The underlying Starlette Request, framework-specific — see
    # `FastApiRequest` in the SDK, which stores it as `.request`.
    raw = getattr(request, "request", None)
    if raw is not None and getattr(raw, "client", None):
        return raw.client.host
    return None


def _override_session_functions(original: RecipeInterface) -> RecipeInterface:
    """Log every successful sign-in — see `services/login_history.py`.

    Wraps `create_new_session` rather than the emailpassword recipe's own
    sign-in API: a session is created exactly once per successful sign-in
    *regardless of recipe*, so this covers Google sign-in for free the day
    that's added, instead of needing its own override too.
    """
    original_create_new_session = original.create_new_session

    async def create_new_session(
        user_id,
        recipe_user_id,
        access_token_payload,
        session_data_in_database,
        disable_anti_csrf,
        tenant_id,
        user_context,
    ):
        session_container = await original_create_new_session(
            user_id,
            recipe_user_id,
            access_token_payload,
            session_data_in_database,
            disable_anti_csrf,
            tenant_id,
            user_context,
        )
        # After the real work, and never allowed to fail it — see
        # services/login_history.py's own docstring for why.
        from app.services import login_history as login_history_service

        request = get_request_from_user_context(user_context)
        await login_history_service.record(
            supertokens_user_id=user_id,
            ip_address=_client_ip(request),
            user_agent=request.get_header("user-agent") if request else None,
        )
        return session_container

    original.create_new_session = create_new_session
    return original


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
            session.init(override=SessionOverrideConfig(functions=_override_session_functions)),
            emailpassword.init(
                # Replaces SuperTokens' managed sending service: password-reset
                # mail goes out through our own SMTP, from our own domain.
                email_delivery=EmailDeliveryConfig(service=MailerEmailDelivery()),
                # See `strong_password_validator` above — the email field
                # keeps SuperTokens' own default validator by not being
                # listed here.
                sign_up_feature=InputSignUpFeature(
                    form_fields=[
                        InputFormField(
                            id=FORM_FIELD_PASSWORD_ID, validate=strong_password_validator
                        )
                    ]
                ),
            ),
        ],
        mode="asgi",
    )


async def get_user_email(user_id: str) -> str | None:
    """SuperTokens holds the email in its core, not in the session, so we look
    it up by user_id. `.emails` is a list under the account-linking model."""
    user = await get_user(user_id)
    return user.emails[0] if user and user.emails else None
