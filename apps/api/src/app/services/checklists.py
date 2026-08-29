"""Checklists on a task — more than one allowed, `write` gates every mutation.

Shared task content, not a personal record: unlike a note, a reminder or a
pin, everyone with access to the task sees the same lists. That's why the
bar is `write`, the same one tagging and attaching a file already clear,
rather than the `read`-is-enough rule reminders and time logging use for a
record of what *you* did.
"""

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Task, TaskChecklist, TaskChecklistItem
from app.models.checklist import MAX_ITEM_TEXT_LENGTH, MAX_TITLE_LENGTH


async def for_task(db: AsyncSession, task_id: uuid.UUID) -> list[TaskChecklist]:
    return list(
        (
            await db.execute(
                select(TaskChecklist)
                .where(TaskChecklist.task_id == task_id)
                .options(selectinload(TaskChecklist.items))
                .order_by(TaskChecklist.id)
            )
        )
        .scalars()
        .all()
    )


async def add_checklist(db: AsyncSession, task: Task, *, title: str) -> TaskChecklist:
    title = (title or "").strip()[:MAX_TITLE_LENGTH]
    if not title:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a checklist needs a name",
        )
    checklist = TaskChecklist(task_id=task.id, title=title)
    db.add(checklist)
    await db.commit()
    await db.refresh(checklist)
    return checklist


async def get_checklist_or_404(
    db: AsyncSession, task_id: uuid.UUID, checklist_id: uuid.UUID
) -> TaskChecklist:
    """Eager-loads `items` — every caller either serves them back in a
    `ChecklistOut` or hands the checklist to a router that will. Without
    `selectinload`, a later `.items` access is a lazy load attempted outside
    an awaited call, and the async ORM raises `MissingGreenlet` for it —
    the exact trap `recurrence.attach()` hit, documented in CLAUDE.md."""
    checklist = (
        await db.execute(
            select(TaskChecklist)
            .where(TaskChecklist.id == checklist_id, TaskChecklist.task_id == task_id)
            .options(selectinload(TaskChecklist.items))
        )
    ).scalar_one_or_none()
    if checklist is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="checklist not found"
        )
    return checklist


async def rename_checklist(
    db: AsyncSession, checklist: TaskChecklist, *, title: str
) -> TaskChecklist:
    title = (title or "").strip()[:MAX_TITLE_LENGTH]
    if not title:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a checklist needs a name",
        )
    checklist.title = title
    await db.commit()
    # Scoped to `title` alone — a full refresh would expire the already-
    # loaded `items` relationship and reintroduce the same lazy-load trap
    # `get_checklist_or_404`'s docstring explains.
    await db.refresh(checklist, attribute_names=["title"])
    return checklist


async def remove_checklist(db: AsyncSession, checklist: TaskChecklist) -> None:
    await db.delete(checklist)
    await db.commit()


async def add_item(db: AsyncSession, checklist: TaskChecklist, *, text: str) -> TaskChecklistItem:
    text = (text or "").strip()[:MAX_ITEM_TEXT_LENGTH]
    if not text:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="an item needs some text",
        )
    item = TaskChecklistItem(checklist_id=checklist.id, text=text)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def get_item_or_404(
    db: AsyncSession, checklist_id: uuid.UUID, item_id: uuid.UUID
) -> TaskChecklistItem:
    item = (
        await db.execute(
            select(TaskChecklistItem).where(
                TaskChecklistItem.id == item_id, TaskChecklistItem.checklist_id == checklist_id
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="item not found")
    return item


async def update_item(
    db: AsyncSession, item: TaskChecklistItem, *, fields: dict
) -> TaskChecklistItem:
    if "text" in fields:
        text = (fields["text"] or "").strip()[:MAX_ITEM_TEXT_LENGTH]
        if not text:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="an item needs some text",
            )
        item.text = text
    if "done" in fields:
        item.done_at = func.now() if fields["done"] else None
    await db.commit()
    await db.refresh(item)
    return item


async def remove_item(db: AsyncSession, item: TaskChecklistItem) -> None:
    await db.delete(item)
    await db.commit()


__all__ = [
    "MAX_ITEM_TEXT_LENGTH",
    "MAX_TITLE_LENGTH",
    "add_checklist",
    "add_item",
    "for_task",
    "get_checklist_or_404",
    "get_item_or_404",
    "remove_checklist",
    "remove_item",
    "rename_checklist",
    "update_item",
]
