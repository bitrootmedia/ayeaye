"""login history: who signed in, from where — no UI yet, just the record

Revision ID: 0021_login_events
Revises: 0020_recurring_tasks
Create Date: Phase 17

Not foreign-keyed to `users` — the local user row is created lazily on
first authenticated request, so on a brand-new signup this fires before
that row exists. Keyed on `supertokens_user_id` instead, which already
exists by the time a session is created. See models/login_event.py.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_login_events"
down_revision = "0020_recurring_tasks"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "login_events",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("supertokens_user_id", sa.String(length=128), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_login_events_supertokens_user_id", "login_events", ["supertokens_user_id"]
    )


def downgrade() -> None:
    op.drop_table("login_events")
