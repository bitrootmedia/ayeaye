"""Tags — a shared vocabulary, and the one property that changes behaviour.

Three rules:

1. **Anyone in the organisation can create and apply a tag; only admins can
   rename, delete or take one off the board.** Creating has to be open or the
   feature is dead on arrival — nobody files a ticket to get a label. Editing
   the vocabulary is different: a rename changes what every existing tagging
   means, and `off_board` decides whether work appears on anyone's board.

2. **Uniqueness is case-insensitive, display is not.** `lower(name)` is
   unique per organisation, so the second person to type "knowledge base"
   lands on the existing "Knowledge base" instead of creating a twin. That is
   the whole reason tags don't rot: there is exactly one of each.

3. **`off_board` never hides anything.** Tasks carrying such a tag leave the
   board and the list — that's the point — but they stay in search, on their
   project, and reachable by filtering for the tag. Nothing becomes
   unfindable; it just stops queueing for attention.
"""

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import delete, exists, func, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article, ArticleTag, Fact, FactTag, Tag, Task, TaskTag, User
from app.models.tag import normalise_tag
from app.services import access
from app.services.organisations import OrgContext


def can_manage_vocabulary(org_role: str) -> bool:
    """Rename, delete, or change `off_board`. Admins only.

    Not the creator: a tag is shared the moment anyone else uses it, and
    "whoever typed it first owns it" is a rule nobody can predict from the
    screen.
    """
    return access.administers_organisation(org_role)


async def list_for_org(db: AsyncSession, ctx: OrgContext) -> list[tuple[Tag, int]]:
    """Every tag, with how many things carry it — tasks, articles and facts
    together, since it is one vocabulary.

    The count is over *all* of them, not just the ones the caller can see. It
    is a property of the vocabulary rather than of your view of the work, and
    scoping it would mean two people disagreeing about whether a tag is in use
    — which is the question the delete button asks.
    """
    taggings = union_all(
        select(TaskTag.tag_id),
        select(ArticleTag.tag_id),
        select(FactTag.tag_id),
    ).subquery()
    used = (
        select(taggings.c.tag_id, func.count().label("n"))
        .group_by(taggings.c.tag_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(Tag, func.coalesce(used.c.n, 0))
            .outerjoin(used, used.c.tag_id == Tag.id)
            .where(Tag.organisation_id == ctx.organisation.id)
            .order_by(Tag.off_board.desc(), func.lower(Tag.name))
        )
    ).all()
    return [(tag, int(n)) for tag, n in rows]


async def get_or_create(
    db: AsyncSession, ctx: OrgContext, user: User, *, name: str, off_board: bool = False
) -> Tag:
    """Find the tag by name, case-insensitively, or make it.

    **Get-or-create rather than create**, because the UI offers "create «foo»"
    the moment a filter matches nothing, and two people doing that at the same
    moment must not produce one error and one tag. The IntegrityError path is
    the race, not a bug: the unique index is what actually enforces rule 2, and
    losing the race means somebody else just made the tag you wanted.
    """
    name = normalise_tag(name)
    if not name:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a tag needs a name"
        )
    found = await find_by_name(db, ctx, name)
    if found is not None:
        return found

    if off_board and not can_manage_vocabulary(ctx.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="only an organisation admin can take a tag off the board",
        )

    tag = Tag(
        organisation_id=ctx.organisation.id,
        name=name,
        off_board=off_board,
        created_by_user_id=user.id,
    )
    db.add(tag)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await find_by_name(db, ctx, name)
        if existing is None:
            raise
        return existing
    await db.refresh(tag)
    return tag


async def find_by_name(db: AsyncSession, ctx: OrgContext, name: str) -> Tag | None:
    return (
        await db.execute(
            select(Tag).where(
                Tag.organisation_id == ctx.organisation.id,
                func.lower(Tag.name) == func.lower(normalise_tag(name)),
            )
        )
    ).scalar_one_or_none()


async def get_or_404(db: AsyncSession, ctx: OrgContext, tag_id: uuid.UUID) -> Tag:
    tag = (
        await db.execute(
            select(Tag).where(Tag.id == tag_id, Tag.organisation_id == ctx.organisation.id)
        )
    ).scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="tag not found")
    return tag


async def update(
    db: AsyncSession, ctx: OrgContext, tag: Tag, *, fields: dict
) -> Tag:
    if not can_manage_vocabulary(ctx.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="only an organisation admin can change a tag",
        )
    if "name" in fields:
        name = normalise_tag(fields["name"])
        if not name:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a tag needs a name"
            )
        tag.name = name
    if "off_board" in fields:
        tag.off_board = bool(fields["off_board"])
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="there is already a tag with that name",
        ) from exc
    await db.refresh(tag)
    return tag


async def remove(db: AsyncSession, ctx: OrgContext, tag: Tag) -> None:
    """Delete the tag, and every tagging of it.

    A tag is a label. Deleting one takes the label off the work; it never
    touches the work — which is why this is allowed at all while a project
    group's deletion is `ON DELETE SET NULL` rather than a cascade to tasks.
    """
    if not can_manage_vocabulary(ctx.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="only an organisation admin can delete a tag",
        )
    await db.delete(tag)
    await db.commit()


# --- tags on tasks ------------------------------------------------------------


async def for_tasks(
    db: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Tag]]:
    """Every tag across a page of tasks, in one query.

    The same discipline as every other list here: one lookup for the board,
    never one per card.
    """
    if not task_ids:
        return {}
    rows = (
        await db.execute(
            select(TaskTag.task_id, Tag)
            .join(Tag, Tag.id == TaskTag.tag_id)
            .where(TaskTag.task_id.in_(task_ids))
            .order_by(func.lower(Tag.name))
        )
    ).all()
    grouped: dict[uuid.UUID, list[Tag]] = {}
    for task_id, tag in rows:
        grouped.setdefault(task_id, []).append(tag)
    return grouped


async def apply(db: AsyncSession, task: Task, tag: Tag) -> None:
    """Idempotent: applying a tag twice is not an error.

    The UI can send the whole set on save, and a duplicate is a no-op rather
    than a 409 somebody has to interpret.

    **`ON CONFLICT DO NOTHING`, not catch-and-rollback.** A duplicate is an
    expected outcome here, not an exception — and a rollback expires every
    ORM instance in the session, so the caller's `task` becomes a lazy load
    waiting to happen. Under asyncio that is a `MissingGreenlet` 500 the
    moment anything downstream touches `task.id`, which is exactly what
    announcing the change does.
    """
    await db.execute(
        pg_insert(TaskTag)
        .values(task_id=task.id, tag_id=tag.id)
        .on_conflict_do_nothing(constraint="uq_task_tags_task_tag")
    )
    await db.commit()


async def unapply(db: AsyncSession, task: Task, tag_id: uuid.UUID) -> None:
    await db.execute(
        delete(TaskTag).where(TaskTag.task_id == task.id, TaskTag.tag_id == tag_id)
    )
    await db.commit()


def off_board_exists():
    """`EXISTS (… a tag on this task that is off the board)`.

    Correlated to `Task`, so it composes into the board's single statement
    rather than becoming a second query and a Python filter.
    """
    return exists(
        select(1)
        .select_from(TaskTag)
        .join(Tag, Tag.id == TaskTag.tag_id)
        .where(TaskTag.task_id == Task.id, Tag.off_board.is_(True))
        .correlate(Task)
    )


def tagged_with(tag_id: uuid.UUID):
    return exists(
        select(1)
        .select_from(TaskTag)
        .where(TaskTag.task_id == Task.id, TaskTag.tag_id == tag_id)
        .correlate(Task)
    )


# --- tags on articles and facts -------------------------------------------------
#
# The same three operations tasks have, over the other two join tables. No
# access rule here, for the reason `apply` has none: the caller resolved the
# article's or the book's level first, and applying a tag is `write` on it.


async def for_articles(
    db: AsyncSession, article_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Tag]]:
    """Every tag across a page of articles, in one query — `for_tasks`'s twin."""
    return await _grouped(db, ArticleTag, ArticleTag.article_id, article_ids)


async def for_facts(db: AsyncSession, fact_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Tag]]:
    return await _grouped(db, FactTag, FactTag.fact_id, fact_ids)


async def _grouped(db: AsyncSession, model, anchor, ids: list[uuid.UUID]):
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(anchor, Tag)
            .join(Tag, Tag.id == model.tag_id)
            .where(anchor.in_(ids))
            .order_by(func.lower(Tag.name))
        )
    ).all()
    grouped: dict[uuid.UUID, list[Tag]] = {}
    for anchor_id, tag in rows:
        grouped.setdefault(anchor_id, []).append(tag)
    return grouped


async def apply_to_article(db: AsyncSession, article: Article, tag: Tag) -> None:
    """Idempotent, and `ON CONFLICT DO NOTHING` for `apply`'s own reason."""
    await db.execute(
        pg_insert(ArticleTag)
        .values(article_id=article.id, tag_id=tag.id)
        .on_conflict_do_nothing(constraint="uq_article_tags_article_tag")
    )
    await db.commit()


async def unapply_from_article(db: AsyncSession, article: Article, tag_id: uuid.UUID) -> None:
    await db.execute(
        delete(ArticleTag).where(ArticleTag.article_id == article.id, ArticleTag.tag_id == tag_id)
    )
    await db.commit()


async def apply_to_fact(db: AsyncSession, fact: Fact, tag: Tag, *, commit: bool = True) -> None:
    """`commit=False` lets `facts.create` file a fact and its tags as one
    transaction — a fact that exists without the tags it was written with
    would turn up in recall under none of the filters its author chose."""
    await db.execute(
        pg_insert(FactTag)
        .values(fact_id=fact.id, tag_id=tag.id)
        .on_conflict_do_nothing(constraint="uq_fact_tags_fact_tag")
    )
    if commit:
        await db.commit()


async def unapply_from_fact(db: AsyncSession, fact: Fact, tag_id: uuid.UUID) -> None:
    await db.execute(delete(FactTag).where(FactTag.fact_id == fact.id, FactTag.tag_id == tag_id))
    await db.commit()


def article_tagged_with_all(tag_ids: list[uuid.UUID]):
    """Every one of these tags is on the article — recall's tag filter, which
    narrows (`app:leadflow` *and* `type:gotcha`) rather than widens."""
    return [
        exists(
            select(1)
            .select_from(ArticleTag)
            .where(ArticleTag.article_id == Article.id, ArticleTag.tag_id == tag_id)
            .correlate(Article)
        )
        for tag_id in tag_ids
    ]


def fact_tagged_with_all(tag_ids: list[uuid.UUID]):
    return [
        exists(
            select(1)
            .select_from(FactTag)
            .where(FactTag.fact_id == Fact.id, FactTag.tag_id == tag_id)
            .correlate(Fact)
        )
        for tag_id in tag_ids
    ]


def task_tagged_with_all(tag_ids: list[uuid.UUID]):
    return [tagged_with(tag_id) for tag_id in tag_ids]
