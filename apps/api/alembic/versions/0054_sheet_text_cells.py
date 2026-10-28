"""sheet text cells: a column can hold text instead of checkboxes

Revision ID: 0054_sheet_text_cells
Revises: 0053_weekly_report
Create Date: sheet text cells

See `models/sheet.py`. `task_sheet_columns.kind` decides what every cell in
the column is, defaulting to `'check'` so every existing sheet is unchanged.
A text cell is the same `task_sheet_cells` row with `value` filled in — its
existence still means "something is here", and clearing the text deletes it.
`updated_at` is new because a text cell, unlike a check, gets overwritten;
existing rows take their `created_at`, which is when they were last set.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054_sheet_text_cells"
down_revision: str | None = "0053_weekly_report"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "task_sheet_columns",
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="check"),
    )
    op.create_check_constraint(
        "ck_task_sheet_columns_kind", "task_sheet_columns", "kind IN ('check', 'text')"
    )
    op.add_column("task_sheet_cells", sa.Column("value", sa.String(length=500), nullable=True))
    op.add_column(
        "task_sheet_cells",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute("UPDATE task_sheet_cells SET updated_at = created_at")


def downgrade() -> None:
    # A text cell has no meaning as a check — dropping the column without
    # this would turn every filled-in value into a ticked box.
    op.execute(
        "DELETE FROM task_sheet_cells WHERE column_id IN "
        "(SELECT id FROM task_sheet_columns WHERE kind = 'text')"
    )
    op.execute("DELETE FROM task_sheet_columns WHERE kind = 'text'")
    op.drop_column("task_sheet_cells", "updated_at")
    op.drop_column("task_sheet_cells", "value")
    op.drop_constraint("ck_task_sheet_columns_kind", "task_sheet_columns", type_="check")
    op.drop_column("task_sheet_columns", "kind")
