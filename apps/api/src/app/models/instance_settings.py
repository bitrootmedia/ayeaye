"""What the operator of this installation decided about its front door.

    instance_settings   (exactly one row, ever)

**One row, enforced by the database rather than by everyone remembering.**
A unique index on a constant expression is what makes a second row impossible;
without it a race between two `get_or_create` callers leaves two rows and the
answer to "is signup open" depends on which one you read. `settings()` in
`services/instance.py` is the only thing that creates it.

**Why a table and not environment variables.** Everything else configurable
about this installation lives in `core/config.py` and needs a restart —
correct for a database URL, wrong for these two, which are the operator's
answer to a spam wave at two in the morning. `SITE_URL` is infrastructure;
whether the front door is open is a decision, and a decision belongs where
it can be changed from the panel and from `scripts/instance.sh` without
touching the deployment.

**And not a column on `organisations` or `users`.** Neither question is about
a person or an organisation: this is the installation's own state, the same
scope `instance_admins` sits at, and the same distance from
`services/access.py` — which never learns either table exists.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: The headline's cap. A front door, not a paragraph — anything longer is a
#: sentence somebody wanted in a page they should be editing instead, and it
#: wraps into an unreadable block at phone width either way.
MAX_HEADLINE = 120


class InstanceSettings(Base):
    __tablename__ = "instance_settings"
    __table_args__ = (
        # `(true)` is constant for every row, so a unique index on it admits
        # exactly one. The alternative — a `singleton bool` column with a
        # unique constraint — carries a column whose only value is `True`,
        # which reads as data and isn't.
        Index("uq_instance_settings_singleton", text("(true)"), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    #: The headline on the front door. NULL means "use the product's own
    #: name", which is deliberately not the same as an empty string: an
    #: operator who clears the field gets the default back rather than a
    #: blank page, and there is no state where the landing page has no
    #: heading at all.
    landing_headline: Mapped[str | None] = mapped_column(String(MAX_HEADLINE), nullable=True)
    #: Whether a stranger can create an account. Off does **not** close the
    #: door on people who were invited — see `signup_allowed_for` in
    #: `services/instance.py`, which is the one place that rule is written.
    signups_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
