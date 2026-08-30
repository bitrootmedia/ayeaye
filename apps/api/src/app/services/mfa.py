"""Two-factor authentication: who must complete it, and how it's recovered.

Hand-rolled TOTP (RFC 6238, via `pyotp`) and backup codes, not SuperTokens'
own `totp`/`multifactorauth` recipes — those require a paid core license even
self-hosted, confirmed against a real core ("MFA feature is not enabled.
Please subscribe to a SuperTokens core license key to enable this feature."),
which conflicts with this product's whole self-hosting story. Enforcement
still runs through SuperTokens' session claims — `MfaSatisfiedClaim` in
`security/authn.py` — because that machinery (`BooleanClaim`, a validator on
every `verify_session()`) is part of the free, open-source `session` recipe.
Only the paid recipe's device/factor bookkeeping is replaced.

**One rule decides who needs a second factor**, and it lives in exactly one
place — `account_requires_mfa`, called from `security/authn.py`'s
`_fetch_mfa_satisfied`. TOTP is required for an account if *either* they
already have a device (`MfaTotpDevice` — personal opt-in is sticky, that's
what "enabling 2FA" means) *or* they're an active member of an organisation
with `require_mfa` set. Union, not override: turning an organisation's
requirement off never revokes someone's own enrollment, and enrolling
personally is never a substitute for a different organisation's requirement.

**Recovery has three layers**, from most to least self-service:

1. Backup codes (`generate_backup_codes`/`redeem_backup_code`) — the everyday
   answer to a lost phone. Same "plaintext exists once" rule as
   `services/tokens.py`'s access tokens, and reuses its `hash_token` rather
   than a second hashing scheme.
2. `reset_totp` — an org admin clearing a member's device from the People
   roster, the same "an org admin can do anything" escape hatch offboarding
   already uses. Covers "lost the device *and* the codes."
3. `scripts/reset-mfa.sh` — an operator running this function directly from
   a shell, for the one case an admin can't reach: a lone owner locked out of
   their own account.

Resetting always clears backup codes too. A device gone but its old codes
still redeemable is a state nobody should be able to reach — the account
looks reset but a stale code left over from before still opens it.
"""

import base64
import secrets
from io import BytesIO

import pyotp
import qrcode
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import MfaBackupCode, MfaTotpDevice, Organisation, OrganisationMember, User
from app.models.organisation import STATUS_ACTIVE
from app.services.tokens import hash_token

BACKUP_CODE_COUNT = 10

# Accepts the code either side of "now" — the standard TOTP allowance for
# clock drift between the server and whatever device generated it.
VALID_WINDOW = 1


async def account_requires_mfa(db: AsyncSession, supertokens_user_id: str) -> bool:
    """Called from inside `security/authn.py`'s claim fetcher, not a
    request. `False` for an account with no local row yet: a brand-new
    signup can't be an organisation member, so there's nothing to require
    (and nothing to look up)."""
    user = (
        await db.execute(select(User).where(User.supertokens_user_id == supertokens_user_id))
    ).scalar_one_or_none()
    if user is None:
        return False

    has_device = (
        await db.execute(select(MfaTotpDevice.id).where(MfaTotpDevice.user_id == user.id))
    ).scalar_one_or_none()
    if has_device is not None:
        return True

    org_requires = (
        await db.execute(
            select(OrganisationMember.id)
            .join(Organisation, Organisation.id == OrganisationMember.organisation_id)
            .where(
                OrganisationMember.user_id == user.id,
                OrganisationMember.status == STATUS_ACTIVE,
                Organisation.require_mfa.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return org_requires is not None


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_qr_data_uri(user: User, secret: str) -> str:
    """A `data:image/png;base64,...` URI, rendered server-side so enrollment
    needs no new frontend dependency — every other picture in this product
    already comes from the server as a URL, this is just one more."""
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.email, issuer_name=settings.brand_name
    )
    img = qrcode.make(uri)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def verify_code(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=VALID_WINDOW)


async def is_enrolled(db: AsyncSession, user: User) -> bool:
    return (
        await db.execute(select(MfaTotpDevice.id).where(MfaTotpDevice.user_id == user.id))
    ).scalar_one_or_none() is not None


async def challenge(db: AsyncSession, user: User, code: str) -> bool:
    """The login-time check, against an *already-enrolled* device — distinct
    from `activate_device`, which confirms a brand-new secret the client is
    still holding. Here the secret never leaves the server: it's read back by
    `user_id`, not supplied by the caller."""
    device = (
        await db.execute(select(MfaTotpDevice).where(MfaTotpDevice.user_id == user.id))
    ).scalar_one_or_none()
    if device is None:
        return False
    return verify_code(device.secret, code)


async def activate_device(db: AsyncSession, user: User, secret: str, code: str) -> bool:
    """Verify a freshly generated secret against the code the person just
    typed from their authenticator app, and only then persist it — there is
    no "pending, unconfirmed device" row to clean up if they never finish.

    `ON CONFLICT` rather than check-then-insert: re-enrolling replaces
    whatever device was there, one statement, no race with a concurrent
    remove."""
    if not verify_code(secret, code):
        return False

    await db.execute(
        pg_insert(MfaTotpDevice)
        .values(user_id=user.id, secret=secret)
        .on_conflict_do_update(index_elements=["user_id"], set_={"secret": secret})
    )
    await db.commit()
    return True


async def reset_totp(db: AsyncSession, user: User) -> None:
    """Remove the device and every backup code. Used both by an org admin
    resetting a member (services/organisations.py's reset_member_mfa) and
    by someone turning 2FA off for themselves."""
    await db.execute(delete(MfaTotpDevice).where(MfaTotpDevice.user_id == user.id))
    await db.execute(delete(MfaBackupCode).where(MfaBackupCode.user_id == user.id))
    await db.commit()


def _generate_code() -> str:
    raw = secrets.token_hex(5)
    return f"{raw[:5]}-{raw[5:]}"


async def generate_backup_codes(db: AsyncSession, user: User) -> list[str]:
    """Replaces any existing set. Regenerating is how someone recovers from
    "I think I used one of these already but I'm not sure which" — a fresh
    set is simpler to reason about than trying to show which ones remain."""
    await db.execute(delete(MfaBackupCode).where(MfaBackupCode.user_id == user.id))

    codes = [_generate_code() for _ in range(BACKUP_CODE_COUNT)]
    for code in codes:
        db.add(MfaBackupCode(user_id=user.id, code_hash=hash_token(code)))
    await db.commit()
    return codes


async def redeem_backup_code(db: AsyncSession, user: User, code: str) -> bool:
    """One conditional UPDATE that both selects and marks — the identical
    claim-not-select-then-update shape `reminders.claim` uses, so two racing
    submits of the same code can't both succeed."""
    row_id = (
        await db.execute(
            update(MfaBackupCode)
            .where(
                MfaBackupCode.user_id == user.id,
                MfaBackupCode.code_hash == hash_token(code.strip().lower()),
                MfaBackupCode.used_at.is_(None),
            )
            .values(used_at=func.now())
            .returning(MfaBackupCode.id)
        )
    ).scalar_one_or_none()
    await db.commit()
    return row_id is not None


async def codes_remaining(db: AsyncSession, user: User) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(MfaBackupCode)
            .where(MfaBackupCode.user_id == user.id, MfaBackupCode.used_at.is_(None))
        )
    ).scalar_one()


__all__ = [
    "account_requires_mfa",
    "new_secret",
    "provisioning_qr_data_uri",
    "verify_code",
    "is_enrolled",
    "activate_device",
    "reset_totp",
    "generate_backup_codes",
    "redeem_backup_code",
    "codes_remaining",
]
