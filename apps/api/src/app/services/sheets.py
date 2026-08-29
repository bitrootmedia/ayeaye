"""Sheets on a task — a grid checklist. `write` gates every mutation, the
same bar checklists, tags and files already clear.

Read `models/sheet.py` first: a cell's existence is the check, so toggling
is insert-or-delete rather than a boolean flip, and a newly added row or
column starts unchecked everywhere without anything to backfill.
"""

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Task, TaskSheet, TaskSheetCell, TaskSheetColumn, TaskSheetRow, User
from app.models.sheet import MAX_LABEL_LENGTH, MAX_TITLE_LENGTH


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


async def add_column(db: AsyncSession, sheet: TaskSheet, *, label: str) -> TaskSheetColumn:
    label = (label or "").strip()[:MAX_LABEL_LENGTH]
    if not label:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a column needs a label"
        )
    column = TaskSheetColumn(sheet_id=sheet.id, label=label)
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
    await db.execute(
        pg_insert(TaskSheetCell)
        .values(row_id=row.id, column_id=column.id, checked_by_user_id=user.id)
        .on_conflict_do_nothing(constraint="uq_task_sheet_cells_row_column")
    )
    await db.commit()
    return (
        await db.execute(
            select(TaskSheetCell, User)
            .join(User, User.id == TaskSheetCell.checked_by_user_id)
            .where(TaskSheetCell.row_id == row.id, TaskSheetCell.column_id == column.id)
        )
    ).one()


async def uncheck_cell(db: AsyncSession, row: TaskSheetRow, column: TaskSheetColumn) -> None:
    await db.execute(
        delete(TaskSheetCell).where(
            TaskSheetCell.row_id == row.id, TaskSheetCell.column_id == column.id
        )
    )
    await db.commit()


async def reset_sheet(db: AsyncSession, sheet: TaskSheet) -> None:
    """Clears every cell for a new round — the sweep is done, start again."""
    await db.execute(
        delete(TaskSheetCell).where(
            TaskSheetCell.row_id.in_(
                select(TaskSheetRow.id).where(TaskSheetRow.sheet_id == sheet.id)
            )
        )
    )
    await db.commit()


__all__ = [
    "MAX_LABEL_LENGTH",
    "MAX_TITLE_LENGTH",
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
    "uncheck_cell",
]
