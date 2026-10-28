"""Sheets on a task — a grid checklist. `write` gates every mutation, the
same bar checklists, tags and files already clear.

Read `models/sheet.py` first: a cell's existence is the check, so toggling
is insert-or-delete rather than a boolean flip, and a newly added row or
column starts unchecked everywhere without anything to backfill.

A text column's cells are the same rows with a `value`. Each column takes
one kind of write only — checking a text cell or typing into a checkbox is
a 409, not a guess at what was meant.
"""

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Task, TaskSheet, TaskSheetCell, TaskSheetColumn, TaskSheetRow, User
from app.models.sheet import (
    COLUMN_KINDS,
    MAX_LABEL_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_VALUE_LENGTH,
)


async def for_task(db: AsyncSession, task_id: uuid.UUID) -> list[TaskSheet]:
    return list(
        (
            await db.execute(
                select(TaskSheet)
                .where(TaskSheet.task_id == task_id)
                .options(selectinload(TaskSheet.rows), selectinload(TaskSheet.columns))
                .order_by(TaskSheet.id)
            )
        )
        .scalars()
        .all()
    )


async def cells_for_sheets(
    db: AsyncSession, sheet_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, uuid.UUID], tuple[TaskSheetCell, User]]:
    """Every checked cell across a page of sheets, in one query — the same
    one-lookup-not-one-per-row discipline every list endpoint in this
    codebase follows once access gets interesting."""
    if not sheet_ids:
        return {}
    rows = (
        await db.execute(
            select(TaskSheetCell, User)
            .join(TaskSheetRow, TaskSheetRow.id == TaskSheetCell.row_id)
            .join(User, User.id == TaskSheetCell.checked_by_user_id)
            .where(TaskSheetRow.sheet_id.in_(sheet_ids))
        )
    ).all()
    return {(cell.row_id, cell.column_id): (cell, who) for cell, who in rows}


async def add_sheet(db: AsyncSession, task: Task, *, title: str) -> TaskSheet:
    title = (title or "").strip()[:MAX_TITLE_LENGTH]
    if not title:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a sheet needs a name"
        )
    sheet = TaskSheet(task_id=task.id, title=title)
    db.add(sheet)
    await db.commit()
    await db.refresh(sheet)
    return sheet


async def get_sheet_or_404(db: AsyncSession, task_id: uuid.UUID, sheet_id: uuid.UUID) -> TaskSheet:
    """Eager-loads `rows` and `columns` — every caller either serves them
    back or hands the sheet to a router that will. Without `selectinload`, a
    later access is a lazy load attempted outside an awaited call — the same
    `MissingGreenlet` trap `checklists.get_checklist_or_404` documents."""
    sheet = (
        await db.execute(
            select(TaskSheet)
            .where(TaskSheet.id == sheet_id, TaskSheet.task_id == task_id)
            .options(selectinload(TaskSheet.rows), selectinload(TaskSheet.columns))
        )
    ).scalar_one_or_none()
    if sheet is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="sheet not found")
    return sheet


async def rename_sheet(db: AsyncSession, sheet: TaskSheet, *, title: str) -> TaskSheet:
    title = (title or "").strip()[:MAX_TITLE_LENGTH]
    if not title:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a sheet needs a name"
        )
    sheet.title = title
    await db.commit()
    # Scoped to `title` alone — a full refresh would expire the already-
    # loaded `rows`/`columns` relationships and reintroduce the lazy-load
    # trap `get_sheet_or_404`'s docstring explains.
    await db.refresh(sheet, attribute_names=["title"])
    return sheet


async def remove_sheet(db: AsyncSession, sheet: TaskSheet) -> None:
    await db.delete(sheet)
    await db.commit()


async def add_row(db: AsyncSession, sheet: TaskSheet, *, label: str) -> TaskSheetRow:
    label = (label or "").strip()[:MAX_LABEL_LENGTH]
    if not label:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a row needs a label"
        )
    row = TaskSheetRow(sheet_id=sheet.id, label=label)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def add_column(
    db: AsyncSession, sheet: TaskSheet, *, label: str, kind: str = "check"
) -> TaskSheetColumn:
    label = (label or "").strip()[:MAX_LABEL_LENGTH]
    if not label:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a column needs a label"
        )
    if kind not in COLUMN_KINDS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a column holds checkboxes or text",
        )
    column = TaskSheetColumn(sheet_id=sheet.id, label=label, kind=kind)
    db.add(column)
    await db.commit()
    await db.refresh(column)
    return column


async def get_row_or_404(db: AsyncSession, sheet_id: uuid.UUID, row_id: uuid.UUID) -> TaskSheetRow:
    row = (
        await db.execute(
            select(TaskSheetRow).where(
                TaskSheetRow.id == row_id, TaskSheetRow.sheet_id == sheet_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="row not found")
    return row


async def get_column_or_404(
    db: AsyncSession, sheet_id: uuid.UUID, column_id: uuid.UUID
) -> TaskSheetColumn:
    column = (
        await db.execute(
            select(TaskSheetColumn).where(
                TaskSheetColumn.id == column_id, TaskSheetColumn.sheet_id == sheet_id
            )
        )
    ).scalar_one_or_none()
    if column is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="column not found")
    return column


async def remove_row(db: AsyncSession, row: TaskSheetRow) -> None:
    await db.delete(row)
    await db.commit()


async def remove_column(db: AsyncSession, column: TaskSheetColumn) -> None:
    await db.delete(column)
    await db.commit()


def _require_kind(column: TaskSheetColumn, kind: str) -> None:
    if column.kind != kind:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                f"{column.label!r} holds text, not checkboxes"
                if column.kind == "text"
                else f"{column.label!r} holds checkboxes, not text"
            ),
        )


def _cell_stmt(row: TaskSheetRow, column: TaskSheetColumn):
    return (
        select(TaskSheetCell, User)
        .join(User, User.id == TaskSheetCell.checked_by_user_id)
        .where(TaskSheetCell.row_id == row.id, TaskSheetCell.column_id == column.id)
    )


async def check_cell(
    db: AsyncSession, row: TaskSheetRow, column: TaskSheetColumn, user: User
) -> tuple[TaskSheetCell, User]:
    """Idempotent: checking an already-checked cell is a no-op, not a second
    row or a 409 somebody has to interpret — the same `ON CONFLICT DO
    NOTHING` idiom `tags.apply` uses, and for the identical reason: a
    duplicate is an expected outcome here, and a rollback would expire every
    ORM instance in the session mid-request.

    Returns who actually holds the check and when — on a conflict that's
    whoever got there first, not the caller, so the response has to be read
    back rather than assumed from the insert.
    """
    _require_kind(column, "check")
    await db.execute(
        pg_insert(TaskSheetCell)
        .values(row_id=row.id, column_id=column.id, checked_by_user_id=user.id)
        .on_conflict_do_nothing(constraint="uq_task_sheet_cells_row_column")
    )
    await db.commit()
    return (await db.execute(_cell_stmt(row, column))).one()


async def uncheck_cell(db: AsyncSession, row: TaskSheetRow, column: TaskSheetColumn) -> None:
    _require_kind(column, "check")
    await db.execute(
        delete(TaskSheetCell).where(
            TaskSheetCell.row_id == row.id, TaskSheetCell.column_id == column.id
        )
    )
    await db.commit()


async def set_value(
    db: AsyncSession, row: TaskSheetRow, column: TaskSheetColumn, user: User, value: str
) -> tuple[TaskSheetCell, User] | None:
    """Write a text cell. Empty clears it — the row goes, the same way an
    unchecked box has none — and returns None.

    Last write wins, for this one cell: unlike a check, where a second
    click means the same thing as the first, a second value means something
    new, so the conflict updates rather than doing nothing. Read back for
    the same reason `check_cell` is — what landed is the answer.
    """
    _require_kind(column, "text")
    value = (value or "").strip()
    if len(value) > MAX_VALUE_LENGTH:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"a cell holds at most {MAX_VALUE_LENGTH} characters",
        )
    if not value:
        await db.execute(
            delete(TaskSheetCell).where(
                TaskSheetCell.row_id == row.id, TaskSheetCell.column_id == column.id
            )
        )
        await db.commit()
        return None
    stmt = pg_insert(TaskSheetCell).values(
        row_id=row.id, column_id=column.id, checked_by_user_id=user.id, value=value
    )
    await db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_task_sheet_cells_row_column",
            set_={
                "value": stmt.excluded.value,
                "checked_by_user_id": stmt.excluded.checked_by_user_id,
                "updated_at": func.now(),
            },
        )
    )
    await db.commit()
    # `one_or_none`: somebody clearing the cell between the two statements
    # is a real outcome, and the answer then is that it's empty.
    return (await db.execute(_cell_stmt(row, column))).one_or_none()


async def reset_sheet(db: AsyncSession, sheet: TaskSheet) -> None:
    """Unticks every checkbox for a new round — the sweep is done, start
    again. **Text stays.** The versions and providers down a sheet are what
    the next round is checked against, not part of the round itself."""
    await db.execute(
        delete(TaskSheetCell).where(
            TaskSheetCell.column_id.in_(
                select(TaskSheetColumn.id).where(
                    TaskSheetColumn.sheet_id == sheet.id, TaskSheetColumn.kind == "check"
                )
            )
        )
    )
    await db.commit()


__all__ = [
    "COLUMN_KINDS",
    "MAX_LABEL_LENGTH",
    "MAX_TITLE_LENGTH",
    "MAX_VALUE_LENGTH",
    "add_column",
    "add_row",
    "add_sheet",
    "cells_for_sheets",
    "check_cell",
    "for_task",
    "get_column_or_404",
    "get_row_or_404",
    "get_sheet_or_404",
    "remove_column",
    "remove_row",
    "remove_sheet",
    "rename_sheet",
    "reset_sheet",
    "set_value",
    "uncheck_cell",
]
