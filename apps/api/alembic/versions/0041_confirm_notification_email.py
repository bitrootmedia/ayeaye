"""confirm an override address before sending anything to it

Revision ID: 0041_confirm_notification_email
Revises: 0040_grandfather_verification
Create Date: Phase 26

`notification_email` stays what it was: the address mail actually goes to,
and now it only ever holds a **confirmed** one. A newly typed address lands
in `notification_email_pending` with a hashed token beside it, and gets
promoted when somebody opens the link sent to it.

That ordering is the whole point. Until it is confirmed, mail keeps going to
the account address — so a typo costs you nothing, and pointing this at
somebody else's inbox achieves nothing either, because they are the only
person who can turn it on and doing so requires the link.

The token is hashed with the same SHA-256 as personal access tokens: the
plaintext exists in one email and nowhere else, so a database that leaks
cannot be used to confirm addresses.
"""

import sqlalchemy as sa
from alembic import op

revision = "0041_confirm_notification_email"
down_revision = "0040_grandfather_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_members",
        sa.Column("notification_email_pending", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "organisation_members",
        sa.Column("notification_email_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "organisation_members",
        sa.Column(
            "notification_email_requested_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    # The confirm route's only lookup: one token, one row. Unique because two
    # rows sharing a token would make "which membership is this for" a
    # question with two answers.
    op.create_index(
        "uq_org_members_notification_email_token",
        "organisation_members",
        ["notification_email_token"],
        unique=True,
        postgresql_where=sa.text("notification_email_token IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_org_members_notification_email_token", table_name="organisation_members"
    )
    op.drop_column("organisation_members", "notification_email_requested_at")
    op.drop_column("organisation_members", "notification_email_token")
    op.drop_column("organisation_members", "notification_email_pending")
