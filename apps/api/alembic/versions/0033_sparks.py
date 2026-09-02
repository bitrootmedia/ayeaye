"""sparks: quick capture, cross-organisation, yours alone

Revision ID: 0033_sparks
Revises: 0032_working_hours
Create Date: Phase 9 follow-up

No title, no organisation_id — see services/sparks.py.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033_sparks"
down_revision = "0032_working_hours"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "sparks",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_sparks_user_id", "sparks", ["user_id"])


def downgrade() -> None:
    op.drop_table("sparks")
