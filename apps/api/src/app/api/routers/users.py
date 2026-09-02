import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Path, status
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
from app.core.config import settings
from app.schemas.working_hours import WorkingHourCell, WorkingHoursOut
from app.security.authn import MfaPendingSession, mark_mfa_satisfied
from app.services import mfa as mfa_service
from app.services import notification_channels as channels_service
from app.services import oauth as oauth_service
from app.services import tokens as tokens_service
from app.services import users as users_service
from app.services import working_hours as working_hours_service

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


def _working_hours_out(user, cells) -> WorkingHoursOut:
    return WorkingHoursOut(
        timezone=user.timezone,
        cells=[WorkingHourCell(weekday=c.weekday, hour=c.hour) for c in cells],
    )


@router.get("/me/working-hours", response_model=WorkingHoursOut)
async def my_working_hours(user: CurrentUser, db: DbSession):
    """Your own weekly pattern, plus the timezone it's recorded in — a
    colleague converts it themselves (see the organisation-scoped route
    below), so there's nothing to convert to here."""
    return _working_hours_out(user, await working_hours_service.mine(db, user))


@router.put("/me/working-hours/{weekday}/{hour}", status_code=status.HTTP_204_NO_CONTENT)
async def set_working_hour(
    user: CurrentUser,
    db: DbSession,
    weekday: int = Path(ge=0, le=6),
    hour: int = Path(ge=0, le=23),
):
    """Mark one cell of the grid. Idempotent — marking a marked hour is a
    no-op, not an error, the identical shape `sheets.check_cell` uses."""
    await working_hours_service.set_cell(db, user, weekday=weekday, hour=hour)


@router.delete("/me/working-hours/{weekday}/{hour}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_working_hour(
    user: CurrentUser,
    db: DbSession,
    weekday: int = Path(ge=0, le=6),
    hour: int = Path(ge=0, le=23),
):
    await working_hours_service.clear_cell(db, user, weekday=weekday, hour=hour)


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


class OAuthGrantOut(BaseModel):
    id: str
    client_name: str
    scope: str
    created_at: datetime


@router.get("/me/oauth-grants", response_model=list[OAuthGrantOut])
async def list_oauth_grants(user: CurrentUser, db: DbSession):
    """Apps you've authorized over OAuth — the "Connected apps" card. A
    personal access token isn't here; those are `/me/tokens`, above."""
    return [
        OAuthGrantOut(
            id=str(grant.id), client_name=client.client_name, scope=grant.scope,
            created_at=grant.created_at,
        )
        for grant, client in await oauth_service.my_grants(db, user)
    ]


@router.delete("/me/oauth-grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_oauth_grant(grant_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Immediate — cascades to every access/refresh token issued under this
    grant, the same "the next call fails" contract `/me/tokens` already has."""
    await oauth_service.revoke_grant(db, user, grant_id)


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


async def _mfa_user(session: MfaPendingSession, db: DbSession):
    return await users_service.get_or_create(db, supertokens_user_id=session.get_user_id())


class MfaStatusOut(BaseModel):
    enrolled: bool
    codes_remaining: int


class TotpDeviceOut(BaseModel):
    # The secret is shown once, alongside the QR — neither is stored until
    # `verify_totp` confirms the person actually has it in an authenticator
    # app. There is no "pending device" row to abandon if they never finish.
    secret: str
    qr_data_uri: str


class TotpVerify(BaseModel):
    secret: str
    code: str


class BackupCodesOut(BaseModel):
    # Returned **once**, at creation — the identical "plaintext exists once"
    # rule TokenCreated makes for an access token. Only the hashes are
    # stored, so no endpoint can show these again.
    codes: list[str]


class BackupCodeRedeem(BaseModel):
    code: str


class BackupCodeRedeemed(BaseModel):
    codes_remaining: int


# Every route below uses MfaPendingSession, not CurrentUser — not just the
# challenge endpoints (verifying a code, redeeming a backup code, which are
# *how* the session claim gets satisfied), but plain enrollment too: turning
# 2FA on can itself be what satisfies a freshly forced organisation's
# requirement, in the same session, with no second sign-in. See
# `MfaPendingSession`'s own docstring in security/authn.py.


@router.get("/me/mfa/status", response_model=MfaStatusOut)
async def mfa_status(session: MfaPendingSession, db: DbSession):
    user = await _mfa_user(session, db)
    return MfaStatusOut(
        enrolled=await mfa_service.is_enrolled(db, user),
        codes_remaining=await mfa_service.codes_remaining(db, user),
    )


@router.post("/me/mfa/totp", response_model=TotpDeviceOut)
async def create_totp_device(session: MfaPendingSession, db: DbSession):
    """Generate a fresh secret and its QR. Nothing is persisted until
    `verify_totp` confirms it against a real code."""
    user = await _mfa_user(session, db)
    secret = mfa_service.new_secret()
    return TotpDeviceOut(
        secret=secret, qr_data_uri=mfa_service.provisioning_qr_data_uri(user, secret)
    )


@router.post("/me/mfa/totp/verify", status_code=status.HTTP_204_NO_CONTENT)
async def verify_totp(body: TotpVerify, session: MfaPendingSession, db: DbSession):
    user = await _mfa_user(session, db)
    ok = await mfa_service.activate_device(db, user, body.secret, body.code)
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="that code is wrong")
    await mark_mfa_satisfied(session)


@router.post("/me/mfa/totp/challenge", status_code=status.HTTP_204_NO_CONTENT)
async def challenge_totp(body: BackupCodeRedeem, session: MfaPendingSession, db: DbSession):
    """The login-time check against an already-enrolled device — `code`
    only, no secret. `BackupCodeRedeem`'s shape (`{code}`) happens to be
    identical, reused rather than declaring a second one-field schema."""
    user = await _mfa_user(session, db)
    if not await mfa_service.challenge(db, user, body.code):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="that code is wrong")
    await mark_mfa_satisfied(session)


@router.delete("/me/mfa/totp", status_code=status.HTTP_204_NO_CONTENT)
async def remove_totp_device(session: MfaPendingSession, db: DbSession):
    """Turn 2FA off for yourself. Also clears backup codes — see
    services/mfa.py's reset_totp for why a device gone but its old codes
    still redeemable is a state nobody should be able to reach."""
    user = await _mfa_user(session, db)
    await mfa_service.reset_totp(db, user)


@router.post(
    "/me/mfa/backup-codes", response_model=BackupCodesOut, status_code=status.HTTP_201_CREATED
)
async def create_backup_codes(session: MfaPendingSession, db: DbSession):
    """Mint a fresh set of ten, replacing any that already existed. Called
    once right after enrolling a TOTP device, and again on demand as
    "Regenerate codes" from the Account screen."""
    user = await _mfa_user(session, db)
    codes = await mfa_service.generate_backup_codes(db, user)
    return BackupCodesOut(codes=codes)


@router.post("/me/mfa/backup-codes/redeem", response_model=BackupCodeRedeemed)
async def redeem_backup_code(body: BackupCodeRedeem, session: MfaPendingSession, db: DbSession):
    """The one route in the codebase reachable before the MFA claim is
    satisfied — see `MfaPendingSession`. A match marks the claim satisfied
    directly, without a real TOTP code ever existing."""
    user = await _mfa_user(session, db)
    ok = await mfa_service.redeem_backup_code(db, user, body.code)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="that code is wrong or already used"
        )

    await mark_mfa_satisfied(session)
    remaining = await mfa_service.codes_remaining(db, user)
    return BackupCodeRedeemed(codes_remaining=remaining)


# --- notification channels --------------------------------------------------------


class NotificationChannelOut(BaseModel):
    id: str
    kind: str
    label: str
    enabled_kinds: list[str]
    # NULL for a Telegram link nobody has tapped `/start` on yet. Always set
    # for email and webhook — there's nothing to verify for either.
    verified_at: datetime | None
    created_at: datetime
    # The webhook's own URL, never its secret. `None` for email and Telegram.
    url: str | None = None
    # Where `/task` files new tasks — set from inside Telegram via `/org`,
    # never from here (see services/telegram_commands.py). `None` for email
    # and webhook, and for a Telegram link with no default chosen yet.
    default_organisation_id: str | None = None


class NotificationChannelUpdate(BaseModel):
    enabled_kinds: list[str]


class WebhookChannelIn(BaseModel):
    url: str
    label: str = ""


class WebhookChannelCreated(NotificationChannelOut):
    # Returned **once**, at creation — see services/notification_channels.py
    # for why the secret itself is stored in plaintext even though this is
    # shown only this one time, the identical UX `TokenCreated` uses for a
    # very different reason.
    secret: str


class TelegramLinkOut(BaseModel):
    deep_link: str


def _channel_out(row) -> NotificationChannelOut:
    return NotificationChannelOut(
        id=str(row.id),
        kind=row.kind,
        label=row.label,
        enabled_kinds=list(row.enabled_kinds),
        verified_at=row.verified_at,
        created_at=row.created_at,
        url=row.config.get("url") if row.kind == "webhook" else None,
        default_organisation_id=row.config.get("default_organisation_id")
        if row.kind == "telegram"
        else None,
    )


@router.get("/me/notification-channels", response_model=list[NotificationChannelOut])
async def list_notification_channels(user: CurrentUser, db: DbSession):
    """Every destination a notification can reach — email is provisioned on
    first read if it doesn't exist yet, so this list is never missing the
    one channel everyone effectively already has."""
    return [_channel_out(c) for c in await channels_service.mine(db, user)]


@router.patch("/me/notification-channels/{channel_id}", response_model=NotificationChannelOut)
async def update_notification_channel(
    channel_id: uuid.UUID,
    body: NotificationChannelUpdate,
    user: CurrentUser,
    db: DbSession,
):
    """The per-kind routing toggle: which notification kinds this channel
    receives."""
    row = await channels_service.update_enabled_kinds(
        db, user, channel_id, enabled_kinds=body.enabled_kinds
    )
    return _channel_out(row)


@router.delete("/me/notification-channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification_channel(channel_id: uuid.UUID, user: CurrentUser, db: DbSession):
    """Unlink Telegram, or remove a webhook. Email can be narrowed to
    nothing but not removed outright — `services/notification_channels.py`
    refuses that with 422."""
    await channels_service.delete_channel(db, user, channel_id)


@router.post(
    "/me/notification-channels/webhook",
    response_model=WebhookChannelCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook_channel(body: WebhookChannelIn, user: CurrentUser, db: DbSession):
    row, secret = await channels_service.create_webhook(db, user, url=body.url, label=body.label)
    return WebhookChannelCreated(**_channel_out(row).model_dump(), secret=secret)


@router.post("/me/notification-channels/telegram/link-start", response_model=TelegramLinkOut)
async def start_telegram_link(user: CurrentUser, db: DbSession):
    """A deep link that opens the bot with a one-time code pre-filled. Tapping
    `/start` in Telegram is what finishes the link — see
    `api/routers/telegram_webhook.py`."""
    if not settings.telegram_bot_username:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Telegram notifications aren't configured on this installation",
        )
    code = await channels_service.start_telegram_link(db, user)
    return TelegramLinkOut(
        deep_link=f"https://t.me/{settings.telegram_bot_username}?start={code}"
    )
