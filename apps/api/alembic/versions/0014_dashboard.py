"""out of office, announcements, and a personal status line

Revision ID: 0014_dashboard
Revises: 0013_reminders
Create Date: Phase 9

Three small things that together make a landing screen worth having.

`announcements` is **per organisation** because this product has no global
administrator — no staff tier, no backoffice — so there is nobody who could
write to every installation. The architecture decides that, not a preference.

`out_of_office` is deliberately not private: the whole value is a colleague
knowing before they ask you for something. The CHECK stops a period that ends
before it starts, which is a typo that would otherwise sit in the table
forever matching nothing.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_dashboard"
down_revision = "0013_reminders"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("users", sa.Column("status_message", sa.String(length=140), nullable=True))

    op.create_table(
        "out_of_office",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        # Inclusive. "Away until the 4th" is what people mean; an exclusive
        # end date gets entered wrong every single time.
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("ends_on >= starts_on", name="ck_ooo_dates"),
    )
    op.create_index("ix_out_of_office_user_id", "out_of_office", ["user_id"])
    op.create_index("ix_ooo_window", "out_of_office", ["ends_on", "starts_on"])

    op.create_table(
        "announcements",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "organisation_id",
            UUID,
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sticky", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_announcements_org", "announcements", ["organisation_id", "created_at"])


def downgrade() -> None:
    op.drop_table("announcements")
    op.drop_table("out_of_office")
    op.drop_column("users", "status_message")
