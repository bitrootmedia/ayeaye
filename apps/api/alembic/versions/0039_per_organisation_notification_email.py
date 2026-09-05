"""per-organisation notification email, with the account address as fallback

Revision ID: 0039_per_org_notification_email
Revises: 0038_task_revisions
Create Date: Phase 26

Two columns, and the pairing is the feature:

`organisation_members.notification_email` is where one person wants *this*
organisation's mail to go. It lives on the membership because a membership
already is "this person, in this organisation" — the exact scope of the
override — so it needs no table of its own and no cleanup when somebody
leaves. NULL means the account address; there is no third state.

`notifications.organisation_id` is what lets the email job find that row at
send time. Every notification this product raises is organisation-scoped
already (each call site builds a `/orgs/{id}/…` link), so this is recording
something the sender knew and used to throw away. Backfilled below from the
link path, which is exactly the guesswork the column exists to stop doing at
send time — but for rows already written it is the only source there is, and
a wrong guess on an old, already-delivered notification costs nothing.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0039_per_org_notification_email"
down_revision = "0038_task_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_members",
        sa.Column("notification_email", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_notifications_organisation_id",
        "notifications",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Existing rows: recover the id from the link they already carry. The
    # regex is anchored and length-checked so a path that isn't
    # `/orgs/<uuid>/…` yields NULL rather than something that only looks
    # like an id, and the join to `organisations` throws away any id that
    # no longer names a real one.
    op.execute(
        """
        UPDATE notifications AS n
           SET organisation_id = o.id
          FROM organisations AS o
         WHERE n.link_path ~ '^/orgs/[0-9a-fA-F-]{36}/'
           AND o.id = substring(n.link_path from 7 for 36)::uuid
        """
    )
    # The email job's own lookup: one notification, one membership.
    op.create_index(
        "ix_org_members_user_org", "organisation_members", ["user_id", "organisation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_org_members_user_org", table_name="organisation_members")
    op.drop_constraint("fk_notifications_organisation_id", "notifications", type_="foreignkey")
    op.drop_column("notifications", "organisation_id")
    op.drop_column("organisation_members", "notification_email")
