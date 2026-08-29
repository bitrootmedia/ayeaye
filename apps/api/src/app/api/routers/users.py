import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from supertokens_python.recipe.emailpassword.asyncio import (
    update_email_or_password,
    verify_credentials,
)
from supertokens_python.recipe.emailpassword.interfaces import (
    PasswordPolicyViolationError,
    WrongCredentialsError,
)
from supertokens_python.types import RecipeUserId

from app.api.deps import CurrentUser, DbSession
from app.services import tokens as tokens_service
from app.services import users as users_service

router = APIRouter(tags=["users"])


class MeOut(BaseModel):
    # `id` is our local user id — what memberships, grants and tasks point at.
    # `user_id` is SuperTokens'; it's what a WebSocket handshake can prove, so
    # it stays on the wire.
    id: str
    user_id: str
    email: str | None
    display_name: str | None
    # IANA. The SPA sends it on first sight so reminders know whose "tomorrow"
    # is meant; nobody has to find a setting for it to work.
    timezone: str | None
    # "Heads-down on the refit today." Yours, shown to colleagues beside your
    # name. Not the same thing as an organisation announcement, which has an
    # author and an audience.
    status_message: str | None
    # Opt-out, default on — see the column's own comment in models/user.py.
    daily_summary_enabled: bool


class MeUpdate(BaseModel):
    display_name: str | None = None
    timezone: str | None = None
    status_message: str | None = Field(default=None, max_length=140)
    daily_summary_enabled: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def _me(user) -> MeOut:
    return MeOut(
        id=str(user.id),
        user_id=user.supertokens_user_id,
        email=user.email or None,
        display_name=user.display_name,
        timezone=user.timezone,
        status_message=user.status_message,
        daily_summary_enabled=user.daily_summary_enabled,
    )


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser):
    """Who you are.

    Also the request that creates the local user row on first sight, which is
    why the SPA calls it before rendering anything.
    """
    return _me(user)


@router.patch("/me", response_model=MeOut)
async def update_me(body: MeUpdate, user: CurrentUser, db: DbSession):
    updated = await users_service.update_profile(db, user, **body.model_dump(exclude_unset=True))
    return _me(updated)


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: str = Field(default="read", pattern="^(read|write)$")


class TokenOut(BaseModel):
    id: str
    name: str
    scope: str
    prefix: str
    last_used_at: datetime | None
    created_at: datetime


class TokenCreated(TokenOut):
    # Returned **once**, at creation. Only the hash is stored, so there is no
    # endpoint that can show it again — which is the property that makes a
    # database backup not a list of live credentials.
    token: str


def _token_out(row) -> TokenOut:
    return TokenOut(
        id=str(row.id),
        name=row.name,
        scope=row.scope,
        prefix=row.prefix,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
    )


@router.get("/me/tokens", response_model=list[TokenOut])
async def list_tokens(user: CurrentUser, db: DbSession):
    """Your access tokens. The secrets are not here and cannot be."""
    return [_token_out(row) for row in await tokens_service.mine(db, user)]


@router.post("/me/tokens", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(body: TokenIn, user: CurrentUser, db: DbSession):
    """Mint one. **The plaintext is in this response and nowhere else.**"""
    row, plaintext = await tokens_service.create(db, user, name=body.name, scope=body.scope)
    return TokenCreated(**_token_out(row).model_dump(), token=plaintext)


@router.delete("/me/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Immediate: the next call with it fails, because the lookup is by hash
    and the row is gone."""
    await tokens_service.revoke(db, user, token_id)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: PasswordChange, user: CurrentUser):
    """Change your own password.

    **The current one is verified first**, and that is not a formality: a
    session can be left open on a shared machine, and without this step
    anybody who finds it can lock the owner out of their own account.

    `verify_credentials` rather than `sign_in` — checking a password should not
    mint a second session as a side effect.

    SuperTokens owns the password policy, so its rejection is passed through
    rather than restated here; two copies of a rule that lives in a library are
    two rules that can disagree.
    """
    check = await verify_credentials("public", user.email, body.current_password)
    if isinstance(check, WrongCredentialsError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="that isn't your current password"
        )

    result = await update_email_or_password(
        recipe_user_id=RecipeUserId(user.supertokens_user_id),
        password=body.new_password,
    )
    if isinstance(result, PasswordPolicyViolationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result.failure_reason
        )
