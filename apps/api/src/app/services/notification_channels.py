"""Where a notification actually goes, once it exists.

Three kinds in one table (`models/notification_channel.py`) — email is a row
here too, auto-provisioned lazily the first time anything needs to notify a
person, not a special case bolted on beside a channel abstraction. That is
what turns `notify()` from "always email" into "deliver to every channel with
this kind enabled" without changing behaviour for anyone who has never opened
the notification settings screen.

**The webhook secret is stored in plaintext, deliberately, unlike a personal
access token's SHA-256 hash.** A PAT is a bearer credential the server only
ever *verifies* — hash it, and the server never needs the plaintext again. A
webhook signing secret is the opposite: it's a symmetric key the server has
to *use*, computing a fresh HMAC on every delivery, for the life of the
channel. There is no way to do that from a one-way hash. The mitigations
that make this an acceptable trade rather than an oversight: the secret signs
nudges that carry no task detail by design (`services/notifications.py`'s own
docstring), it's scoped to one channel and revocable independently of every
other credential in the account, and it is never sent back to the browser
after creation — only a short preview, the same "which one do I revoke"
purpose `PersonalAccessToken.prefix` already serves.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationChannel, OrganisationMember, User
from app.models.notification import NOTIFICATION_KINDS
from app.models.notification_channel import (
    CHANNEL_EMAIL,
    CHANNEL_KINDS,
    CHANNEL_TELEGRAM,
    CHANNEL_WEBHOOK,
)
from app.models.organisation import STATUS_ACTIVE
from app.services import tokens as tokens_service

# How long a "link your Telegram" deep link stays valid. Short enough that a
# stale link sitting in an old chat isn't a standing way in; long enough that
# nobody has to race it.
LINK_CODE_TTL = timedelta(minutes=15)


async def get_or_create_email_channel(db: AsyncSession, user_id: uuid.UUID) -> NotificationChannel:
    """Every user has exactly one, created the first time it's needed rather
    than at signup — the same lazy `get_or_create` shape `services/users.py`
    already uses for the local user row. Two concurrent `notify()` calls
    racing to provision it collide on `uq_notification_channels_user_email`;
    the loser's `IntegrityError` just means re-reading what the winner
    inserted, the identical race-recovery shape `tasks_service.grant()`
    already uses for its own unique-grant race."""
    row = (
        await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user_id, NotificationChannel.kind == CHANNEL_EMAIL
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row

    row = NotificationChannel(
        user_id=user_id,
        kind=CHANNEL_EMAIL,
        label="Email",
        config={},
        enabled_kinds=list(NOTIFICATION_KINDS),
        verified_at=datetime.now(UTC),
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return (
            await db.execute(
                select(NotificationChannel).where(
                    NotificationChannel.user_id == user_id,
                    NotificationChannel.kind == CHANNEL_EMAIL,
                )
            )
        ).scalar_one()
    await db.refresh(row)
    return row


async def mine(db: AsyncSession, user: User) -> list[NotificationChannel]:
    """Every channel, provisioning email first so it's never missing from a
    settings screen that's supposed to show every destination there is."""
    await get_or_create_email_channel(db, user.id)
    rows = (
        await db.execute(
            select(NotificationChannel)
            .where(NotificationChannel.user_id == user.id)
            .order_by(NotificationChannel.kind, NotificationChannel.created_at)
        )
    ).scalars().all()
    return list(rows)


async def channels_for(
    db: AsyncSession, user_id: uuid.UUID, *, kind: str
) -> list[NotificationChannel]:
    """Every destination this notification `kind` should actually reach.
    Called from `notify()` — not the router — so every caller of `notify()`
    gets routing for free without knowing this table exists."""
    await get_or_create_email_channel(db, user_id)
    rows = (
        await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user_id,
                NotificationChannel.verified_at.is_not(None),
            )
        )
    ).scalars().all()
    return [c for c in rows if kind in c.enabled_kinds]


async def update_enabled_kinds(
    db: AsyncSession, user: User, channel_id: uuid.UUID, *, enabled_kinds: list[str]
) -> NotificationChannel:
    row = await _get_or_404(db, user, channel_id)
    unknown = set(enabled_kinds) - set(NOTIFICATION_KINDS)
    if unknown:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown notification kind: {', '.join(sorted(unknown))}",
        )
    row.enabled_kinds = enabled_kinds
    await db.commit()
    await db.refresh(row)
    return row


async def delete_channel(db: AsyncSession, user: User, channel_id: uuid.UUID) -> None:
    row = await _get_or_404(db, user, channel_id)
    if row.kind == CHANNEL_EMAIL:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="email can be narrowed to nothing, but not removed",
        )
    await db.delete(row)
    await db.commit()


async def _get_or_404(db: AsyncSession, user: User, channel_id: uuid.UUID) -> NotificationChannel:
    row = (
        await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.id == channel_id, NotificationChannel.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="notification channel not found"
        )
    return row


# --- Telegram ---------------------------------------------------------------------


async def start_telegram_link(db: AsyncSession, user: User) -> str:
    """Mint a one-time code and stash it on a pending (`verified_at IS NULL`)
    channel row. Any previous Telegram channel for this person — pending or
    already linked — is replaced: a person has one Telegram account, and
    starting a fresh link is how they'd re-point it at a different chat."""
    await db.execute(
        NotificationChannel.__table__.delete().where(
            NotificationChannel.user_id == user.id, NotificationChannel.kind == CHANNEL_TELEGRAM
        )
    )
    code = secrets.token_urlsafe(18)
    db.add(
        NotificationChannel(
            user_id=user.id,
            kind=CHANNEL_TELEGRAM,
            label="Telegram",
            config={"link_code": code},
            enabled_kinds=list(NOTIFICATION_KINDS),
            verified_at=None,
        )
    )
    await db.commit()
    return code


async def complete_telegram_link(db: AsyncSession, *, code: str, chat_id: str) -> bool:
    """Called from the `/telegram/webhook` route when someone taps `/start
    {code}` in the bot. Returns whether a pending link actually matched —
    an expired or already-used code is not an error, just nothing to do."""
    cutoff = datetime.now(UTC) - LINK_CODE_TTL
    row = (
        await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.kind == CHANNEL_TELEGRAM,
                NotificationChannel.verified_at.is_(None),
                NotificationChannel.config["link_code"].astext == code,
                NotificationChannel.created_at >= cutoff,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False

    # A real Telegram chat id belongs to one Telegram account, which can be
    # linked to at most one ayeaye account at a time — `start_telegram_link`
    # already replaces the *caller's own* previous claim, but says nothing
    # about a *different* account that verified this exact chat earlier
    # (someone re-linking the same Telegram to a second ayeaye account, most
    # plausibly). Without this, two verified rows can carry the same chat
    # id, and `telegram_commands._channel_and_user`'s lookup by chat id
    # becomes ambiguous. Deleting any other channel already holding it is
    # the identical "re-linking transfers the claim" rule, just applied
    # across accounts instead of within one.
    await db.execute(
        NotificationChannel.__table__.delete().where(
            NotificationChannel.kind == CHANNEL_TELEGRAM,
            NotificationChannel.id != row.id,
            NotificationChannel.config["chat_id"].astext == chat_id,
        )
    )
    row.config = {"chat_id": chat_id}
    row.verified_at = datetime.now(UTC)
    await db.commit()
    return True


async def set_telegram_default_organisation(
    db: AsyncSession, channel: NotificationChannel, organisation_id: uuid.UUID
) -> None:
    """Which organisation `/task` files into. Written by `/org` (and by
    `/task`'s own single-organisation auto-pick) — see `services/
    telegram_commands.py`. Membership is the caller's job to have already
    checked; this is pure persistence, the same split `services/
    dependencies.py` draws between the access check and the write."""
    channel.config = {**channel.config, "default_organisation_id": str(organisation_id)}
    await db.commit()


# --- webhook ------------------------------------------------------------------------


def sign(secret: str, body: bytes) -> str:
    """`X-Ayeaye-Signature: sha256=...` — the same header shape GitHub and
    Stripe already taught people to expect from a webhook."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def create_webhook(
    db: AsyncSession, user: User, *, url: str, label: str
) -> tuple[NotificationChannel, str]:
    """Returns the row **and the plaintext secret**, shown once — the
    identical contract `services/tokens.py::create` uses, even though the
    secret itself isn't hashed at rest (see the module docstring)."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="give a full http(s) URL",
        )
    label = (label or "").strip()[:120] or url
    secret = secrets.token_urlsafe(32)
    row = NotificationChannel(
        user_id=user.id,
        kind=CHANNEL_WEBHOOK,
        label=label,
        config={"url": url, "secret": secret},
        enabled_kinds=list(NOTIFICATION_KINDS),
        verified_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, secret


# --- where this organisation's mail goes ------------------------------------------


def resolve_email(account_email: str | None, override: str | None) -> str | None:
    """The one place the fallback rule is written down.

    An override that is blank, whitespace, or absent means "use the account
    address" — three spellings of the same intention, and treating them
    differently is how a saved-but-empty field becomes mail nobody receives.
    Returns None only when there is nothing to send to at all, which the
    caller must treat as "don't send" rather than as an address.
    """
    chosen = (override or "").strip() or (account_email or "").strip()
    return chosen or None


def normalise_override(value: str | None) -> str | None:
    """What to store for a typed-in override. Blank stores NULL, so clearing
    the box and clearing the override are the same act — the alternative is
    an empty string that reads as "set" everywhere it is checked."""
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return None
    if len(cleaned) > 320 or "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="that doesn't look like an email address",
        )
    return cleaned


async def email_for_organisation(
    db: AsyncSession, *, user: User, organisation_id: uuid.UUID | None
) -> str | None:
    """Where to send this person's mail about this organisation.

    A notification with no organisation (nothing raises one today, but the
    column is nullable) goes to the account address, as does one for an
    organisation they have set no preference for. **Scoped to an active
    membership**: a disabled or removed member's row shouldn't keep steering
    mail, and after removal there is no row to read anyway.
    """
    override: str | None = None
    if organisation_id is not None:
        override = (
            await db.execute(
                select(OrganisationMember.notification_email).where(
                    OrganisationMember.user_id == user.id,
                    OrganisationMember.organisation_id == organisation_id,
                    OrganisationMember.status == STATUS_ACTIVE,
                )
            )
        ).scalar_one_or_none()
    return resolve_email(user.email, override)


async def overrides_for(
    db: AsyncSession, user: User
) -> dict[uuid.UUID, tuple[str | None, str | None]]:
    """Every override this person has, live and pending, by organisation id.

    One statement for the whole settings screen rather than a lookup per
    row — the same discipline every list in this codebase follows. Both
    values, because the screen has to say "going here" and "waiting on a
    confirmation" differently; one column would make a pending address look
    like it was already in use, which is the one thing it must not do.
    """
    rows = (
        await db.execute(
            select(
                OrganisationMember.organisation_id,
                OrganisationMember.notification_email,
                OrganisationMember.notification_email_pending,
            ).where(
                OrganisationMember.user_id == user.id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).all()
    return {org_id: (live, pending) for org_id, live, pending in rows}


#: How long a confirmation link is good for. Long enough to survive a "I'll
#: do it when I'm at my desk", short enough that a forgotten one expires
#: rather than sitting there indefinitely.
CONFIRM_TTL = timedelta(hours=48)


async def request_email_for_organisation(
    db: AsyncSession, *, user: User, organisation_id: uuid.UUID, email: str | None
) -> tuple[OrganisationMember, str | None]:
    """Ask to send this organisation's mail somewhere else.

    **Nothing changes where mail goes until the address is confirmed.** The
    new address waits in `notification_email_pending`, and the live
    `notification_email` is untouched until somebody opens the link sent to
    the new address. That is what makes this safe to point anywhere: a typo
    costs nothing, and aiming it at a colleague's inbox achieves nothing,
    because only they could open the link and they have no reason to.

    Blank clears everything — the live override *and* anything pending — so
    "stop sending it elsewhere" is one act rather than two.

    Returns the membership and the plaintext token, which exists only here
    and in the email. Only your own membership, ever: there is no branch that
    lets an admin redirect somebody else's mail.
    """
    membership = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.user_id == user.id,
                OrganisationMember.organisation_id == organisation_id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="not found")

    wanted = normalise_override(email)
    membership.notification_email_pending = None
    membership.notification_email_token = None
    membership.notification_email_requested_at = None

    if wanted is None:
        membership.notification_email = None
        await db.commit()
        return membership, None
    if wanted == membership.notification_email:
        # Already confirmed and already in use. Re-sending a link for an
        # address that is working would be a confusing thing to receive.
        await db.commit()
        return membership, None

    plaintext = secrets.token_urlsafe(32)
    membership.notification_email_pending = wanted
    membership.notification_email_token = tokens_service.hash_token(plaintext)
    membership.notification_email_requested_at = datetime.now(UTC)
    await db.commit()
    return membership, plaintext


async def confirm_email_for_organisation(
    db: AsyncSession, token: str
) -> OrganisationMember | None:
    """Promote a pending address to the live one. Returns None for anything
    unrecognised — a wrong, used or expired token all look the same, because
    telling them apart tells a stranger which tokens once existed.

    Unauthenticated by design: the token is the authority, exactly as it is
    for an invitation link (see `services/invites.py`). The person who can
    read the mail sent to an address is the person entitled to say it is
    theirs — requiring a signed-in session as well would mean the link only
    works in the browser it was requested from, which is precisely the
    browser it probably wasn't opened in.
    """
    if not token:
        return None
    membership = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.notification_email_token == tokens_service.hash_token(token)
            )
        )
    ).scalar_one_or_none()
    if membership is None or membership.notification_email_pending is None:
        return None
    requested = membership.notification_email_requested_at
    if requested is None or datetime.now(UTC) - requested > CONFIRM_TTL:
        return None

    membership.notification_email = membership.notification_email_pending
    membership.notification_email_pending = None
    # Cleared, so the link is single-use — the same rule an invite token
    # follows, and for the same reason.
    membership.notification_email_token = None
    membership.notification_email_requested_at = None
    await db.commit()
    return membership


__all__ = [
    "CHANNEL_KINDS",
    "resolve_email",
    "normalise_override",
    "email_for_organisation",
    "overrides_for",
    "request_email_for_organisation",
    "confirm_email_for_organisation",
    "get_or_create_email_channel",
    "mine",
    "channels_for",
    "update_enabled_kinds",
    "delete_channel",
    "start_telegram_link",
    "complete_telegram_link",
    "set_telegram_default_organisation",
    "sign",
    "create_webhook",
]
