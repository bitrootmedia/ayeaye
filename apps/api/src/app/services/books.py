"""Books, and who can see them.

A near-mechanical copy of `services/projects.py` — a book's access model is
a project's, unchanged, just naming a different resource. Every read here
goes through `services/access.py`; nothing in this module decides for
itself whether someone may see a book.
"""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Book, BookMember, OrganisationMember, Team, User
from app.models.notification import KIND_BOOK_SHARED
from app.models.organisation import STATUS_ACTIVE
from app.models.structure import GRANT_LEVELS
from app.services import access, notifications
from app.services.organisations import OrgContext


def _who(user: User) -> str:
    return user.display_name or user.email or "Someone"


@dataclass(frozen=True)
class BookContext:
    """A book plus the caller's resolved level on it."""

    book: Book
    level: str

    def require(self, allowed: bool, detail: str) -> None:
        """403. Reaching this point means they can already see the book;
        absence of access became a 404 in `context_for`."""
        if not allowed:
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=detail)


async def context_for(
    db: AsyncSession, ctx: OrgContext, book_id: uuid.UUID, user_id: uuid.UUID
) -> BookContext:
    """One book, or 404 — the same 404 whether it's missing, belongs to
    another organisation, or simply isn't shared with you."""
    row = (
        await db.execute(
            access.visible_book_stmt(
                user_id=user_id, org_id=ctx.organisation.id, org_role=ctx.role, book_id=book_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="book not found")
    book, rank = row
    return BookContext(book=book, level=access.level_name(rank) or "")


async def list_visible(
    db: AsyncSession, ctx: OrgContext, user_id: uuid.UUID, *, include_archived: bool = False
) -> list[tuple[Book, str]]:
    """One statement, no per-row checks."""
    rows = (
        await db.execute(
            access.visible_books_stmt(
                user_id=user_id,
                org_id=ctx.organisation.id,
                org_role=ctx.role,
                include_archived=include_archived,
            )
        )
    ).all()
    return [(book, access.level_name(rank) or "") for book, rank in rows]


async def create(
    db: AsyncSession, ctx: OrgContext, *, name: str, description: str | None, user: User
) -> BookContext:
    """Create a book. You own it, and by default only you can see it — any
    member may create one, which is what makes that default workable."""
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="a book needs a name"
        )
    book = Book(
        organisation_id=ctx.organisation.id,
        name=name,
        description=(description or "").strip() or None,
        owner_user_id=user.id,
        created_by_user_id=user.id,
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)
    # No grant row for the owner — ownership is a column, and a row saying
    # the same thing is a second answer that can drift out of step with it.
    return BookContext(book=book, level=access.LEVEL_OWNER)


async def update(
    db: AsyncSession,
    bctx: BookContext,
    *,
    name: str | None = None,
    description: str | None = None,
    archived: bool | None = None,
) -> Book:
    """Edit the book. Needs `write`; archiving needs `owner`."""
    book = bctx.book
    bctx.require(access.can_write(bctx.level), "you have read-only access to this book")

    if name is not None:
        name = name.strip()
        if not name:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="a book needs a name",
            )
        book.name = name
    if description is not None:
        book.description = description.strip() or None
    if archived is not None:
        bctx.require(access.can_administer(bctx.level), "only the book owner can archive this")
        book.archived_at = func.now() if archived else None

    await db.commit()
    await db.refresh(book)
    return book


async def transfer(
    db: AsyncSession, bctx: BookContext, ctx: OrgContext, *, new_owner_id: uuid.UUID
) -> Book:
    """Hand the book to someone else. Owner or organisation admin only."""
    bctx.require(access.can_administer(bctx.level), "only the book owner can hand it over")
    member = (
        await db.execute(
            select(OrganisationMember).where(
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.user_id == new_owner_id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="that person is not a member of this organisation",
        )
    bctx.book.owner_user_id = new_owner_id
    await db.commit()
    await db.refresh(bctx.book)
    return bctx.book


async def delete(db: AsyncSession, bctx: BookContext) -> None:
    bctx.require(access.can_administer(bctx.level), "only the book owner can delete this")
    await db.delete(bctx.book)
    await db.commit()


# --- access, and stating it plainly ------------------------------------------


async def list_grants(
    db: AsyncSession, book_id: uuid.UUID
) -> list[tuple[BookMember, User | None, Team | None]]:
    rows = (
        await db.execute(
            select(BookMember, User, Team)
            .outerjoin(User, User.id == BookMember.user_id)
            .outerjoin(Team, Team.id == BookMember.team_id)
            .where(BookMember.book_id == book_id)
            .order_by(BookMember.id)
        )
    ).all()
    return [(grant, user, team) for grant, user, team in rows]


async def list_implicit_viewers(
    db: AsyncSession, org_id: uuid.UUID, owner_id: uuid.UUID
) -> list[User]:
    """Everyone who can see this book without a grant: the organisation's
    owners and admins. Surfaced, not assumed — an invisible admin tier makes
    the access screen a lie."""
    member = aliased(OrganisationMember)
    return list(
        (
            await db.execute(
                select(User)
                .join(member, member.user_id == User.id)
                .where(
                    member.organisation_id == org_id,
                    member.status == STATUS_ACTIVE,
                    member.role.in_(("admin", "owner")),
                    User.id != owner_id,
                )
                .order_by(User.display_name, User.email)
            )
        )
        .scalars()
        .all()
    )


async def grant(
    db: AsyncSession,
    bctx: BookContext,
    ctx: OrgContext,
    *,
    user_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
    level: str,
    granted_by: User,
) -> BookMember:
    """Share the book with one person or one team."""
    bctx.require(
        access.can_administer(bctx.level), "only the book owner can change who has access"
    )
    if (user_id is None) == (team_id is None):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="grant to exactly one of a person or a team",
        )
    if level not in GRANT_LEVELS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"level must be one of {', '.join(GRANT_LEVELS)}",
        )

    if user_id is not None:
        if user_id == bctx.book.owner_user_id:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT, detail="they already own this book"
            )
        present = (
            await db.execute(
                select(OrganisationMember.id).where(
                    OrganisationMember.organisation_id == ctx.organisation.id,
                    OrganisationMember.user_id == user_id,
                    OrganisationMember.status == STATUS_ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if present is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="that person is not a member of this organisation",
            )
    else:
        present = (
            await db.execute(
                select(Team.id).where(
                    Team.id == team_id, Team.organisation_id == ctx.organisation.id
                )
            )
        ).scalar_one_or_none()
        if present is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="team not found")

    row = BookMember(
        book_id=bctx.book.id,
        user_id=user_id,
        team_id=team_id,
        level=level,
        granted_by_user_id=granted_by.id,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="they already have access — change the level instead",
        ) from exc
    await db.refresh(row)

    if user_id and user_id != granted_by.id:
        await notifications.notify(
            db,
            user_id=user_id,
            kind=KIND_BOOK_SHARED,
            title=f"{_who(granted_by)} shared “{bctx.book.name}” with you",
            link_path=f"/orgs/{ctx.organisation.id}/kb/books/{bctx.book.id}",
            organisation_id=ctx.organisation.id,
        )
    return row


async def get_grant(db: AsyncSession, book_id: uuid.UUID, grant_id: uuid.UUID) -> BookMember:
    row = (
        await db.execute(
            select(BookMember).where(BookMember.id == grant_id, BookMember.book_id == book_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="grant not found")
    return row


async def change_grant(
    db: AsyncSession, bctx: BookContext, row: BookMember, *, level: str
) -> BookMember:
    bctx.require(
        access.can_administer(bctx.level), "only the book owner can change who has access"
    )
    if level not in GRANT_LEVELS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"level must be one of {', '.join(GRANT_LEVELS)}",
        )
    row.level = level
    await db.commit()
    await db.refresh(row)
    return row


async def revoke(db: AsyncSession, bctx: BookContext, row: BookMember) -> None:
    bctx.require(
        access.can_administer(bctx.level), "only the book owner can change who has access"
    )
    await db.delete(row)
    await db.commit()
