"""Sheets: the same maintenance sweep across many servers, as a grid.

    tasks ──► task_sheets ──► task_sheet_rows ─┐
                          └──► task_sheet_columns ─┴──► task_sheet_cells ── users

More than one per task allowed, the same "packing list" vs "before we ship"
reasoning as checklists — a "Weekly maintenance" sheet and a "Security audit"
sheet on the same task are two different grids, not two sections of one.

**A cell's existence IS the check.** There is no boolean column: checking a
cell inserts a row into `task_sheet_cells`, unchecking deletes it. That is
what makes "a new row or column starts unchecked everywhere" free rather than
something to backfill — an added row simply has no cells yet, for any
column, until someone checks one. The same idiom `task_tags` already uses for
"is this tag applied", and for the same reason: existence is cheaper to keep
correct than a flag that can drift from it.

Ordered by `id`, no `position` column — UUIDv7 sorts chronologically, the
same convention `task_checklists` uses and for the same reason: nothing here
needs drag-and-drop reordering.

Shared task content, not a personal record: `write` gates every mutation
(`services/sheets.py`), the identical bar checklists, tags and files already
clear.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

MAX_TITLE_LENGTH = 200
MAX_LABEL_LENGTH = 200


class TaskSheet(Base):
    __tablename__ = "task_sheets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(MAX_TITLE_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )

    rows: Mapped[list["TaskSheetRow"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", order_by="TaskSheetRow.id"
    )
    columns: Mapped[list["TaskSheetColumn"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", order_by="TaskSheetColumn.id"
    )


class TaskSheetRow(Base):
    __tablename__ = "task_sheet_rows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    sheet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_sheets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(MAX_LABEL_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )

    sheet: Mapped[TaskSheet] = relationship(back_populates="rows")


class TaskSheetColumn(Base):
    __tablename__ = "task_sheet_columns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    sheet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_sheets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(MAX_LABEL_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )

    sheet: Mapped[TaskSheet] = relationship(back_populates="columns")


class TaskSheetCell(Base):
    __tablename__ = "task_sheet_cells"
    __table_args__ = (
        # One check per row×column — checking twice is a no-op, not a second
        # row, the same reasoning `uq_task_tags_task_tag` already applies.
        UniqueConstraint("row_id", "column_id", name="uq_task_sheet_cells_row_column"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_sheet_rows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    column_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_sheet_columns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # CASCADE, the same as every other user_id in this schema (task_pins,
    # reminders, …) — there is no user-deletion feature to make this fire in
    # practice, only the lazily-created local row SuperTokens identity backs.
    checked_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The check IS this row's existence — `created_at` doubles as "when",
    # with no separate boolean anywhere to drift out of sync with it.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
