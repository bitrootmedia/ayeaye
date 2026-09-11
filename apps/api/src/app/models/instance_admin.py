"""Who administers this *installation* — not any organisation in it.

    users ──► instance_admins

**Its own table, and that is the point rather than a schema preference.**
`users` has no `role`, `kind`, `is_admin` or `is_staff` column, and
`tests/test_schema_invariants.py` fails the build if one appears — because
what a person may do *inside* an organisation comes from their membership and
their grants, and a second place to look when something is denied is exactly
what that rule exists to prevent. This is not that. An instance admin has no
extra power inside any organisation at all: `services/access.py` never learns
this table exists, a hidden task stays hidden from them, a private note stays
private, and an export stays the requester's. What they get is the operator
view — counts, dates, names — and the ability to suspend an account or an
organisation, both of which sit *upstream* of the access model exactly as
`users.disabled_at` already does.

So the line this row sits on is the same one
`test_account_suspension_is_not_a_role` draws: it says nothing about
authorization, and `tests/test_schema_invariants.py` asserts that
`services/access.py` never reads it, for the same reason it already asserts
the same of `disabled_at`.

**Granted from the shell, never from the web panel it unlocks.** A screen
that can appoint its own successors is a screen where one stolen session is
permanent; `scripts/instance.sh grant-admin` needs shell access to the box,
which is a credential the web has no way to phish. The panel can suspend and
restore; it cannot hand out this row.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InstanceAdmin(Base):
    __tablename__ = "instance_admins"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    # Unique, not the primary key: this schema's one convention is a single
    # `id` defaulted from `uuidv7()` on every table, and an association table
    # is not an excuse to depart from it — see
    # `test_every_table_has_a_uuidv7_primary_key`. CASCADE because the row is
    # meaningless without the account.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    #: Free text, for the operator's own benefit — "set up the box", "on call".
    #: Never shown to anybody who isn't already an instance admin.
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
