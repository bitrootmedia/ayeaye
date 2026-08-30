"""Wire shapes for organisations, membership and invitations.

`role` arrives as a plain string and is validated against the model's tuple
rather than a Python Enum, so the Pydantic schema, the SQL CHECK constraint and
the frontend union all read from one list.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.organisation import ROLE_MEMBER, ROLES


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrganisationUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrganisationOut(BaseModel):
    id: str
    name: str
    slug: str
    # The caller's own role, resolved server-side. The UI never re-derives
    # permissions — it branches on this.
    role: str
    # Unions with a member's own TOTP enrollment rather than replacing it —
    # see services/mfa.py's account_requires_mfa.
    require_mfa: bool
    created_at: datetime


class RequireMfaUpdate(BaseModel):
    enabled: bool


class MemberOut(BaseModel):
    id: str
    role: str
    status: str
    # None until an invited person has an account.
    user_id: str | None
    email: str | None
    display_name: str | None
    invited_by: str | None
    accepted_at: datetime | None
    created_at: datetime
    # Only ever populated for the person who may act on it — see the router.
    invite_url: str | None = None


class MemberRoleUpdate(BaseModel):
    role: str = Field(pattern=f"^({'|'.join(ROLES)})$")


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = Field(default=ROLE_MEMBER, pattern=f"^({'|'.join(ROLES)})$")


class InviteCreated(BaseModel):
    member: MemberOut
    # The copyable link, always returned. This is the half of the invitation
    # that works with no SMTP configured at all — see PLAN.md §2.4.
    invite_url: str
    # Whether an email was also queued. False is normal, not an error: it means
    # this deployment has no SMTP, and the UI says "copy the link" instead of
    # "we've emailed them".
    emailed: bool


class InvitePreview(BaseModel):
    """What an invitation link shows before you sign in — deliberately thin.

    Enough to decide whether to accept, and nothing that would leak the
    organisation's contents to whoever holds the URL.
    """

    organisation_name: str
    invited_email: str | None
    role: str
    invited_by: str | None


class PendingInviteOut(BaseModel):
    id: str
    organisation_id: str
    organisation_name: str
    role: str
    invited_by: str | None
    created_at: datetime
