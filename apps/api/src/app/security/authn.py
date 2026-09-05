"""Authentication: SuperTokens setup and identity lookups.

Answers "who is this user?" and nothing else. What they may do is decided by
organisation membership and grants — see services/access.py (Phase 3). There is
no policy engine and no staff tier; PLAN.md §2.1 explains why.
"""

import logging
import re
from typing import Annotated

from fastapi import Depends
from supertokens_python import InputAppInfo, SupertokensConfig, get_request_from_user_context, init
from supertokens_python.asyncio import get_user
from supertokens_python.ingredients.emaildelivery.types import EmailDeliveryConfig
from supertokens_python.recipe import emailpassword, emailverification, session
from supertokens_python.recipe.emailpassword import InputFormField, InputSignUpFeature
from supertokens_python.recipe.emailpassword.constants import FORM_FIELD_PASSWORD_ID
from supertokens_python.recipe.session import SessionContainer
from supertokens_python.recipe.session.claim_base_classes.boolean_claim import BooleanClaim
from supertokens_python.recipe.session.framework.fastapi import verify_session
from supertokens_python.recipe.session.interfaces import RecipeInterface
from supertokens_python.recipe.session.utils import SessionOverrideConfig

from app.core.config import settings
from app.security.email import MailerEmailDelivery, MailerVerificationDelivery


async def _fetch_mfa_satisfied(user_id, _recipe_user_id, _tenant_id, _payload, _user_context):
    """The one rule that decides who needs a second factor — see
    `services/mfa.py`'s own docstring for the full reasoning. Called exactly
    once per session, the first time anything checks the claim (SuperTokens'
    claim framework fetches lazily on first need, then keeps whatever value
    is in the payload — see `MfaSatisfiedClaim`'s own comment for why that's
    the right cadence here). Returns `True` ("satisfied") when nothing is
    required at all; a required-but-incomplete account gets `False`, which
    the validator below turns into a blocked session until TOTP or a backup
    code flips it — see `mark_mfa_satisfied`.
    """
    from app.db import SessionLocal
    from app.services import mfa as mfa_service

    async with SessionLocal() as db:
        return not await mfa_service.account_requires_mfa(db, user_id)


# A custom, free/open-source session claim — SuperTokens' own `multifactorauth`
# recipe would do this natively, but it requires a paid core license even
# self-hosted (confirmed against a real core: "MFA feature is not enabled.
# Please subscribe to a SuperTokens core license key"). `BooleanClaim` is part
# of the base `session` recipe instead, and gives the same shape: a value
# fetched into the access token payload and checked by a validator on every
# `verify_session()` call.
#
# `default_max_age_in_sec=None` is deliberate, not an oversight: with no max
# age, the claim framework only refetches when the payload has no value yet
# (a brand-new session) — never on a timer. So the requirement is decided once,
# at first use per session, and completing TOTP or a backup code (which calls
# `mark_mfa_satisfied`, setting the value directly) sticks for that session's
# whole life rather than being silently recomputed and reset. An organisation
# turning `require_mfa` on reaches existing sessions at their *next* sign-in,
# not mid-session — the same "eventual, not instant" trade-off a paid claim
# with a refresh interval would also have made, just decided at a different
# point (session boundary instead of a timer).
MfaSatisfiedClaim = BooleanClaim(key="st-mfa-ok", fetch_value=_fetch_mfa_satisfied)


async def mark_mfa_satisfied(session_container: SessionContainer) -> None:
    """Called after a TOTP code or backup code is accepted. See
    `api/routers/users.py`'s `verify_totp`/`redeem_backup_code`."""
    await session_container.set_claim_value(MfaSatisfiedClaim, True)


def _add_mfa_validator(default_validators, _session, _user_context):
    """Passed to `verify_session(override_global_claim_validators=...)` on the
    one shared `VerifiedSession` dependency every router builds on — this is
    the actual security boundary, not the frontend's `MfaGate`. There is no
    "default global validator" registration to hook for a custom claim the
    way a recipe gets for free, so it's added explicitly here instead."""
    return [*default_validators, MfaSatisfiedClaim.validators.is_true(None)]


# The canonical "this request has a valid session" dependency. Declared here
# so everything shares one instance instead of building its own verifier —
# and, since `_add_mfa_validator` is baked in, so every router enforces the
# MFA claim with no per-route change.
VerifiedSession = Annotated[
    SessionContainer, Depends(verify_session(override_global_claim_validators=_add_mfa_validator))
]


def _skip_mfa_validator(_default, _session, _user_context):
    """Passed to `verify_session(override_global_claim_validators=...)` for
    every `/me/mfa/*` route — see `MfaPendingSession`. Returns an empty list
    rather than filtering `_default` down: nothing else in this codebase adds
    a global validator, so the two are equivalent today, but this is correct
    even the day something else does."""
    return []


# A verified session that does NOT enforce the MFA claim. Every `/me/mfa/*`
# route uses this instead of `VerifiedSession`/`CurrentUser` — not just the
# challenge endpoints (verifying a code, redeeming a backup code, both of
# which are *how* the claim gets satisfied, so the route that does it can't
# itself require it), but also plain enrollment: turning 2FA on for the first
# time from the Account screen can itself be the thing that satisfies a
# freshly forced organisation's requirement, in the same session, with no
# second sign-in. A session that already satisfies the claim reaches these
# routes exactly the same way — skipping a check nobody fails is a no-op for
# them.
MfaPendingSession = Annotated[
    SessionContainer,
    Depends(verify_session(override_global_claim_validators=_skip_mfa_validator)),
]

# The same thing under a name that says what it is used for now: a session
# that is real but hasn't yet satisfied whatever claim is standing in its
# way. `_skip_mfa_validator` returns an *empty* list rather than filtering
# one claim out, so this skips the email-verification claim too — which is
# exactly what a route the gate calls needs, since asking an unverified
# session for its own address is the one question it must be able to answer.
PendingSession = MfaPendingSession

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


logger = logging.getLogger("app.authn")


def _override_emailpassword_apis(original):
    """Send the verification email when an account is created.

    SuperTokens does not do this on its own: it sends when a *client* asks
    it to, which the prebuilt UI does on its way to the verify screen. That
    leaves two gaps this closes. A sign-up over the API — curl, a script,
    the e2e suites — would get no email at all; and even in a browser the
    "we sent you a link" screen would be describing something that hadn't
    happened yet, which is the kind of small lie that costs somebody ten
    minutes staring at an empty inbox.

    Wrapped around the sign-up API rather than the sign-up *function*, so it
    fires for a person signing up and not for anything internal that creates
    a user by another route.

    **Never fails the sign-up.** The account exists by this point; refusing
    the request because the mail didn't go would leave somebody with an
    account they were told they don't have. With no SMTP the mailer logs the
    link instead, which is the same escape hatch password reset already
    relies on.
    """
    original_sign_up_post = original.sign_up_post

    async def sign_up_post(
        form_fields,
        tenant_id,
        session,
        should_try_linking_with_session_user,
        api_options,
        user_context,
    ):
        response = await original_sign_up_post(
            form_fields,
            tenant_id,
            session,
            should_try_linking_with_session_user,
            api_options,
            user_context,
        )
        user = getattr(response, "user", None)
        if user is not None:
            try:
                from supertokens_python.recipe.emailverification.asyncio import (
                    send_email_verification_email,
                )

                await send_email_verification_email(
                    tenant_id=tenant_id,
                    user_id=user.id,
                    recipe_user_id=(
                        getattr(response, "recipe_user_id", None)
                        or user.login_methods[0].recipe_user_id
                    ),
                    email=user.emails[0] if user.emails else None,
                )
            except Exception as exc:
                logger.warning("could not send the verification email on sign-up: %s", exc)
        return response

    original.sign_up_post = sign_up_post
    return original


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
            # Verification, and the mode is a product decision as much as a
            # config one — see `settings.email_verification_required`.
            #
            # REQUIRED puts SuperTokens' own `EmailVerificationClaim` on
            # every session, so `verify_session()` refuses an unverified one
            # everywhere at once rather than each route remembering to ask.
            # OPTIONAL registers exactly the same endpoints and emails and
            # gates nothing, which is what makes "off" a usable state rather
            # than a missing feature: an address can still be confirmed, it
            # just isn't a condition of getting in.
            emailverification.init(
                mode="REQUIRED" if settings.email_verification_required else "OPTIONAL",
                email_delivery=EmailDeliveryConfig(service=MailerVerificationDelivery()),
            ),
            emailpassword.init(
                # Replaces SuperTokens' managed sending service: password-reset
                # mail goes out through our own SMTP, from our own domain.
                email_delivery=EmailDeliveryConfig(service=MailerEmailDelivery()),
                override=emailpassword.InputOverrideConfig(apis=_override_emailpassword_apis),
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
