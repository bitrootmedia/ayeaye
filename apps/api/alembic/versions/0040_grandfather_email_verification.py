"""grandfather the accounts that existed before verification was a thing

Revision ID: 0040_grandfather_verification
Revises: 0039_per_org_notification_email
Create Date: Phase 26

Turning verification on retroactively would lock out every existing account
until its owner found an email and clicked it — including whoever ran the
upgrade, which is a memorable way to learn about a deploy. So every account
that exists at this moment is marked as needing grandfathering, and the API
completes it on its next start.

**Why not just do it here.** Verification lives in SuperTokens' own database,
not this one — `emailverification_verified_emails`, on the same server but a
different database and a schema this project doesn't own. Writing into it
from a migration would be reaching into somebody else's storage and betting
on its shape; going through the SDK is the supported way to say "this
address is verified", and that needs a running app. Hence a flag here and a
one-off pass there (`services/verification.py`).

The flag defaults to **false**, so accounts created after this migration are
never grandfathered — they verify like everyone else from now on.
"""

import sqlalchemy as sa
from alembic import op

revision = "0040_grandfather_verification"
down_revision = "0039_per_org_notification_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "grandfather_verification",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute("UPDATE users SET grandfather_verification = true")
    # The startup pass's own query, and it wants to find nothing quickly on
    # every boot after the first. Partial, because the rows it looks for stop
    # existing — a full index on a column that is false for every row in the
    # table is a page of nothing.
    op.create_index(
        "ix_users_grandfather_verification",
        "users",
        ["id"],
        postgresql_where=sa.text("grandfather_verification"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_grandfather_verification", table_name="users")
    op.drop_column("users", "grandfather_verification")
