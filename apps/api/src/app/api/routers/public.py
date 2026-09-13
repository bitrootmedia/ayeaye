"""What the front door needs to know, before anybody has signed in.

The only unauthenticated route in the `/api` tree besides the invite preview,
and it exists for the same reason that one does: the landing page is reached
by people with no account, so anything it renders has to be answerable
without a session.

**Two fields, and nothing that isn't already on the screen.** The headline is
about to be displayed to whoever asked; whether registration is open is
discoverable in one POST anyway, since `security/authn.py` is the real gate
and says plainly why it refused. An endpoint that leaked an installation's
*shape* — counts, names, versions — would be a different thing entirely, and
`services/instance.py`'s "metadata only" rule applies to the panel precisely
because that data is worth protecting. This is the operator's own poster.

**Deliberately not `/instance/settings` with the auth relaxed.** That prefix
is 404 for everybody without an `instance_admins` row, on purpose — a 403
would confirm the surface exists. Hanging a public route off it would hand
back exactly that confirmation.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import DbSession
from app.services import instance as instance_service

router = APIRouter(tags=["public"])


class PublicSettingsOut(BaseModel):
    #: NULL when the operator hasn't set one. The frontend falls back to the
    #: product's own name from `lib/brand.ts` rather than this carrying it —
    #: a rename is a three-file change (see CLAUDE.md) and sending the name
    #: here would quietly make it four, with two of them able to disagree.
    landing_headline: str | None
    signups_enabled: bool


@router.get("/public/settings", response_model=PublicSettingsOut)
async def public_settings(db: DbSession):
    """The landing page's own two facts. No session, no cookie — it is one
    row, and the SPA asks once per load."""
    row = await instance_service.settings(db)
    return PublicSettingsOut(
        landing_headline=row.landing_headline,
        signups_enabled=row.signups_enabled,
    )
