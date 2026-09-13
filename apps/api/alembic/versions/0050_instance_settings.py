"""instance_settings: the landing headline, and the signup switch

Revision ID: 0050_instance_settings
Revises: 0049_attribution_and_idempotency
Create Date: Phase 9 follow-up

What the operator of this installation decided about its front door. One
table, exactly one row, created lazily on first read rather than seeded here
— see `services/instance.py::settings` for why a migration writing the
defaults a second time would give this schema two answers to the same
question the day one of them changes.

The singleton is enforced by a unique index on a constant expression, which
is why this migration is hand-written like 0043, 0046, 0048 and 0049:
autogenerate cannot see an expression index (it offers to drop every partial
and trigram index in this schema along the way), and an `instance_settings`
that quietly allowed two rows would make "is registration open" depend on
which row the query happened to reach first.

Nothing is backfilled and nothing else is touched. An existing installation
comes up with registration open and the product's own name as the heading,
which is exactly what it had before this migration ran.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050_instance_settings"
down_revision: str | None = "0049_attribution_and_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "instance_settings",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("landing_headline", sa.String(length=120), nullable=True),
        sa.Column(
            "signups_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # One row, ever. `(true)` is the same value for every row, so a unique
    # index on it admits exactly one — and the INSERT in
    # `services/instance.py::settings` relies on this failing rather than on
    # a lock, because the read that creates the row is the landing page's.
    op.execute("CREATE UNIQUE INDEX uq_instance_settings_singleton ON instance_settings ((true))")


def downgrade() -> None:
    op.drop_table("instance_settings")
