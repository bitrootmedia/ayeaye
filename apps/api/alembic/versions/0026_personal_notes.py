"""the notepad: free-form personal notes, scoped to an organisation

Revision ID: 0026_personal_notes
Revises: 0025_sheets
Create Date: Phase 22

One table. Only the author ever reads a row — the same absence-of-a-branch
discipline task_notes already has — so there is no access table to add, just
`organisation_id` and `user_id` to scope the list. See models/personal_note.py.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026_personal_notes"
down_revision = "0025_sheets"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "personal_notes",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "organisation_id",
            UUID,
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_personal_notes_organisation_id", "personal_notes", ["organisation_id"])
    op.create_index("ix_personal_notes_user_id", "personal_notes", ["user_id"])


def downgrade() -> None:
    op.drop_table("personal_notes")
