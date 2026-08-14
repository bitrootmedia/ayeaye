"""a private note per person per task

Revision ID: 0012_private_notes
Revises: 0011_tags
Create Date: Phase 9

One scratchpad per person per task, readable by nobody else — organisation
admins included. That last part is the feature, not a detail: it is the second
deliberate exception to "an admin can do anything" (the first is a hidden
task), and `services/notes.py` has no branch that could grant one.

`user_id` cascades rather than nulling: a note with no owner is one nobody may
read and nobody can delete.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_private_notes"
down_revision = "0011_tags"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "task_notes",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # The upsert in services/notes.py names this constraint. The editor
        # autosaves, so two saves can overlap; without it the second is a 500
        # in the middle of typing.
        sa.UniqueConstraint("task_id", "user_id", name="uq_task_notes_task_user"),
    )
    op.create_index("ix_task_notes_task_id", "task_notes", ["task_id"])
    op.create_index("ix_task_notes_user_id", "task_notes", ["user_id"])
    # Searchable, but only ever by their author — see notes_stmt.
    op.execute("CREATE INDEX ix_task_notes_body_trgm ON task_notes USING gin (body gin_trgm_ops)")


def downgrade() -> None:
    op.drop_table("task_notes")
