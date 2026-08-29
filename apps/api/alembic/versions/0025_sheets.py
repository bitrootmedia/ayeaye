"""sheets: a grid checklist under a task — rows, columns, and a checkbox
per cell

Revision ID: 0025_sheets
Revises: 0024_checklists
Create Date: Phase 21

Four tables. A cell's existence IS the check — there is no boolean column
on task_sheet_cells, just a unique (row_id, column_id) — checking inserts,
unchecking deletes. That is what makes a newly added row or column start
unchecked everywhere for free rather than something to backfill. See
models/sheet.py.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025_sheets"
down_revision = "0024_checklists"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "task_sheets",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("task_id", UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_task_sheets_task_id", "task_sheets", ["task_id"])

    op.create_table(
        "task_sheet_rows",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "sheet_id", UUID, sa.ForeignKey("task_sheets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_task_sheet_rows_sheet_id", "task_sheet_rows", ["sheet_id"])

    op.create_table(
        "task_sheet_columns",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "sheet_id", UUID, sa.ForeignKey("task_sheets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_task_sheet_columns_sheet_id", "task_sheet_columns", ["sheet_id"])

    op.create_table(
        "task_sheet_cells",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column(
            "row_id",
            UUID,
            sa.ForeignKey("task_sheet_rows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "column_id",
            UUID,
            sa.ForeignKey("task_sheet_columns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "checked_by_user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("row_id", "column_id", name="uq_task_sheet_cells_row_column"),
    )
    op.create_index("ix_task_sheet_cells_row_id", "task_sheet_cells", ["row_id"])
    op.create_index("ix_task_sheet_cells_column_id", "task_sheet_cells", ["column_id"])


def downgrade() -> None:
    op.drop_table("task_sheet_cells")
    op.drop_table("task_sheet_columns")
    op.drop_table("task_sheet_rows")
    op.drop_table("task_sheets")
