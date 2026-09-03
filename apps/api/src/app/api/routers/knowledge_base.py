"""The knowledge base: books, articles, and their revisions.

Thin, same as `structure.py`: every rule lives in `services/books.py` and
`services/articles.py`. Everything hangs off `/organisations/{org_id}/kb`,
so `CurrentOrg` resolves "are you even in here" once, same as everywhere
else.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models import ArticleRevision, Attachment, Book, BookMember, Team, User
from app.schemas.knowledge_base import (
    ArticleCreate,
    ArticleFileOut,
    ArticleOut,
    ArticleSetPrivate,
    ArticleTransferIn,
    BookAccessOut,
    BookCreate,
    BookOut,
    BookUpdate,
    RevisionOut,
    RevisionSave,
)
from app.schemas.structure import GrantIn, GrantLevelIn, GrantOut, PersonOut, TeamOut, TransferIn
from app.services import access as access_service
from app.services import articles as articles_service
from app.services import attachments as attachments_service
from app.services import books as books_service
from app.services import richtext

router = APIRouter(prefix="/organisations/{org_id}/kb", tags=["knowledge-base"])


def _person(user: User | None) -> PersonOut | None:
    if user is None:
        return None
    return PersonOut(id=str(user.id), email=user.email, display_name=user.display_name)


async def _owners(db: DbSession, books: list[Book]) -> dict[uuid.UUID, User]:
    ids = {b.owner_user_id for b in books}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


def _book_out(book: Book, level: str, *, owner: User | None) -> BookOut:
    return BookOut(
        id=str(book.id),
        name=book.name,
        description=book.description,
        owner=_person(owner),
        archived=book.archived_at is not None,
        created_at=book.created_at,
        access=level,
    )


@router.get("/books", response_model=list[BookOut])
async def list_books(
    ctx: CurrentOrg, user: CurrentUser, db: DbSession, include_archived: bool = False
):
    """Only what you can see — a book is private to its owner until it's
    shared, the identical rule a project follows."""
    visible = await books_service.list_visible(db, ctx, user.id, include_archived=include_archived)
    owners = await _owners(db, [b for b, _ in visible])
    return [_book_out(book, level, owner=owners.get(book.owner_user_id)) for book, level in visible]


@router.post("/books", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def create_book(body: BookCreate, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Any member may create one, and owns what they create."""
    bctx = await books_service.create(
        db, ctx, name=body.name, description=body.description, user=user
    )
    return _book_out(bctx.book, bctx.level, owner=user)


@router.get("/books/{book_id}", response_model=BookOut)
async def get_book(book_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    bctx = await books_service.context_for(db, ctx, book_id, user.id)
    owners = await _owners(db, [bctx.book])
    return _book_out(bctx.book, bctx.level, owner=owners.get(bctx.book.owner_user_id))


@router.patch("/books/{book_id}", response_model=BookOut)
async def update_book(
    book_id: uuid.UUID, body: BookUpdate, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    bctx = await books_service.context_for(db, ctx, book_id, user.id)
    book = await books_service.update(
        db, bctx, name=body.name, description=body.description, archived=body.archived
    )
    owners = await _owners(db, [book])
    return _book_out(book, bctx.level, owner=owners.get(book.owner_user_id))


@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(book_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    bctx = await books_service.context_for(db, ctx, book_id, user.id)
    await books_service.delete(db, bctx)


@router.post("/books/{book_id}/owner", status_code=status.HTTP_204_NO_CONTENT)
async def transfer_book(
    book_id: uuid.UUID, body: TransferIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Hand the book to someone else. Returns no body — the same "don't
    re-resolve a level a successful commit just took away" reasoning
    `transfer_project` documents; the client refetches instead."""
    bctx = await books_service.context_for(db, ctx, book_id, user.id)
    await books_service.transfer(db, bctx, ctx, new_owner_id=uuid.UUID(body.owner_user_id))


# --- who can see it -----------------------------------------------------------


def _grant_out(grant: BookMember, user: User | None, team: Team | None) -> GrantOut:
    return GrantOut(
        id=str(grant.id),
        level=grant.level,
        user=_person(user),
        team=TeamOut(id=str(team.id), name=team.name, member_count=0, created_at=team.created_at)
        if team
        else None,
        created_at=grant.created_at,
    )


@router.get("/books/{book_id}/access", response_model=BookAccessOut)
async def book_access(book_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    bctx = await books_service.context_for(db, ctx, book_id, user.id)
    grants = await books_service.list_grants(db, book_id)
    owner = (
        await db.execute(select(User).where(User.id == bctx.book.owner_user_id))
    ).scalar_one_or_none()
    admins = await books_service.list_implicit_viewers(
        db, ctx.organisation.id, bctx.book.owner_user_id
    )
    return BookAccessOut(
        owner=_person(owner),
        grants=[_grant_out(g, u, t) for g, u, t in grants],
        organisation_admins=[p for p in (_person(a) for a in admins) if p],
        can_manage=access_service.can_administer(bctx.level),
    )


@router.post(
    "/books/{book_id}/access", response_model=GrantOut, status_code=status.HTTP_201_CREATED
)
async def add_grant(
    book_id: uuid.UUID, body: GrantIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    bctx = await books_service.context_for(db, ctx, book_id, user.id)
    row = await books_service.grant(
        db,
        bctx,
        ctx,
        user_id=uuid.UUID(body.user_id) if body.user_id else None,
        team_id=uuid.UUID(body.team_id) if body.team_id else None,
        level=body.level,
        granted_by=user,
    )
    grants = await books_service.list_grants(db, book_id)
    return next(_grant_out(g, u, t) for g, u, t in grants if g.id == row.id)


@router.patch("/books/{book_id}/access/{grant_id}", response_model=GrantOut)
async def change_grant(
    book_id: uuid.UUID,
    grant_id: uuid.UUID,
    body: GrantLevelIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    bctx = await books_service.context_for(db, ctx, book_id, user.id)
    row = await books_service.get_grant(db, book_id, grant_id)
    await books_service.change_grant(db, bctx, row, level=body.level)
    grants = await books_service.list_grants(db, book_id)
    return next(_grant_out(g, u, t) for g, u, t in grants if g.id == grant_id)


@router.delete("/books/{book_id}/access/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_grant(
    book_id: uuid.UUID, grant_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    bctx = await books_service.context_for(db, ctx, book_id, user.id)
    row = await books_service.get_grant(db, book_id, grant_id)
    await books_service.revoke(db, bctx, row)


# --- articles ------------------------------------------------------------------


def _article_out(
    article, level: str, *, owner: User | None, title: str, caller_id: uuid.UUID
) -> ArticleOut:
    return ArticleOut(
        id=str(article.id),
        book_id=str(article.book_id),
        title=title,
        owner=_person(owner),
        is_private=article.is_private,
        can_make_private=articles_service.can_make_private(
            is_owner=article.owner_user_id == caller_id
        ),
        created_at=article.created_at,
        updated_at=article.updated_at,
        access=level,
    )


async def _article_owners(db: DbSession, articles: list) -> dict[uuid.UUID, User]:
    ids = {a.owner_user_id for a in articles}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


@router.get("/books/{book_id}/articles", response_model=list[ArticleOut])
async def list_articles(book_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """The table of contents. Your own private drafts are included; anyone
    else's simply never appear — the vanish-from-contents behaviour."""
    # Confirms the book itself is visible before listing what's in it — a
    # 404 here is "you can't see this book", distinct from "this book has
    # nothing you can see in it" (an empty list).
    await books_service.context_for(db, ctx, book_id, user.id)
    rows = await articles_service.list_for_book(db, ctx, book_id, user.id)
    owners = await _article_owners(db, [a for a, _, _ in rows])
    return [
        _article_out(
            a,
            level,
            owner=owners.get(a.owner_user_id),
            title=rev.title if rev else "",
            caller_id=user.id,
        )
        for a, level, rev in rows
    ]


@router.post(
    "/books/{book_id}/articles", response_model=ArticleOut, status_code=status.HTTP_201_CREATED
)
async def create_article(
    book_id: uuid.UUID, body: ArticleCreate, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Born private — see `services/articles.py::create`. Needs `write` on
    the book."""
    bctx = await books_service.context_for(db, ctx, book_id, user.id)
    article, revision = await articles_service.create(db, bctx, user, title=body.title)
    return _article_out(article, "owner", owner=user, title=revision.title, caller_id=user.id)


@router.get("/articles/{article_id}", response_model=ArticleOut)
async def get_article(article_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    actx = await articles_service.context_for(db, ctx, article_id, user.id)
    owners = await _article_owners(db, [actx.article])
    rev = await articles_service.latest_revision(db, actx.article.id)
    return _article_out(
        actx.article,
        actx.level,
        owner=owners.get(actx.article.owner_user_id),
        title=rev.title if rev else "",
        caller_id=user.id,
    )


@router.patch("/articles/{article_id}/private", response_model=ArticleOut)
async def set_article_private(
    article_id: uuid.UUID,
    body: ArticleSetPrivate,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """Publish (`is_private: false`) or un-publish. Owner-only — the button
    that would do anything else simply isn't shown, the same convention
    `can_close`/`can_hide` already establish."""
    actx = await articles_service.context_for(db, ctx, article_id, user.id)
    article = await articles_service.set_private(db, actx, user, is_private=body.is_private)
    owners = await _article_owners(db, [article])
    rev = await articles_service.latest_revision(db, article.id)
    return _article_out(
        article,
        actx.level,
        owner=owners.get(article.owner_user_id),
        title=rev.title if rev else "",
        caller_id=user.id,
    )


@router.post("/articles/{article_id}/owner", status_code=status.HTTP_204_NO_CONTENT)
async def transfer_article(
    article_id: uuid.UUID,
    body: ArticleTransferIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """No body, deliberately — the identical "don't re-resolve a level a
    successful commit just took away" reasoning `transfer_project`/
    `transfer_book` already document."""
    actx = await articles_service.context_for(db, ctx, article_id, user.id)
    await articles_service.transfer_owner(db, actx, ctx, new_owner_id=uuid.UUID(body.owner_user_id))


@router.delete("/articles/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(article_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    actx = await articles_service.context_for(db, ctx, article_id, user.id)
    actx.require(
        access_service.can_administer(actx.level), "only the article's owner can delete this"
    )
    await db.delete(actx.article)
    await db.commit()


# --- revisions -------------------------------------------------------------------


async def _revision_or_404(db: DbSession, revision_id: uuid.UUID) -> ArticleRevision:
    """Looked up by id alone — the article-scoped access check happens right
    after, via `articles_service.context_for(revision.article_id)`, the
    same two-step shape task comment/attachment lookups already use."""
    revision = (
        await db.execute(select(ArticleRevision).where(ArticleRevision.id == revision_id))
    ).scalar_one_or_none()
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="revision not found")
    return revision


async def _rendered_body(db: DbSession, article_id: uuid.UUID, body: str) -> str:
    """Swap `data-attachment-id` markers for fresh presigned URLs. Scoped
    across every revision of the article, not just this one — see
    `attachments_service.image_urls_for_article`."""
    wanted = set(richtext.image_ids(body))
    urls = await attachments_service.image_urls_for_article(db, article_id, wanted)
    return richtext.render(body, urls) or ""


async def _revision_out(
    db: DbSession, rev: ArticleRevision, *, edited_by: User | None, is_current: bool
) -> RevisionOut:
    return RevisionOut(
        id=str(rev.id),
        article_id=str(rev.article_id),
        title=rev.title,
        body=await _rendered_body(db, rev.article_id, rev.body),
        edited_by=_person(edited_by),
        created_at=rev.created_at,
        updated_at=rev.updated_at,
        is_current=is_current,
    )


@router.post("/articles/{article_id}/edit-session", response_model=RevisionOut)
async def start_edit_session(
    article_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Resolve (or start) the mutable "current" revision for the editor to
    load. See `services/articles.py::start_editing_session` for exactly
    when a fresh one starts rather than reusing the last one."""
    actx = await articles_service.context_for(db, ctx, article_id, user.id)
    revision = await articles_service.start_editing_session(db, actx, user)
    return await _revision_out(db, revision, edited_by=user, is_current=True)


@router.patch("/revisions/{revision_id}", response_model=RevisionOut)
async def save_revision(
    revision_id: uuid.UUID, body: RevisionSave, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """The autosave endpoint — the debounced call the editor already knows
    the shape of from the notepad. 409s if this revision has been
    superseded by a newer session."""
    revision = await _revision_or_404(db, revision_id)
    actx = await articles_service.context_for(db, ctx, revision.article_id, user.id)
    new_body = body.body
    if new_body and body.body_format == "markdown":
        new_body = richtext.from_markdown(new_body)
    saved = await articles_service.autosave_revision(
        db, actx, revision, title=body.title, body=new_body
    )
    return await _revision_out(db, saved, edited_by=user, is_current=True)


@router.get("/articles/{article_id}/revisions", response_model=list[RevisionOut])
async def list_revisions(article_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    actx = await articles_service.context_for(db, ctx, article_id, user.id)
    rows = await articles_service.list_revisions(db, actx)
    current = await articles_service.latest_revision(db, actx.article.id)
    return [
        await _revision_out(
            db, r, edited_by=u, is_current=current is not None and r.id == current.id
        )
        for r, u in rows
    ]


@router.get("/revisions/{revision_id}", response_model=RevisionOut)
async def get_revision(revision_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    revision = await _revision_or_404(db, revision_id)
    actx = await articles_service.context_for(db, ctx, revision.article_id, user.id)
    edited_by = (
        await db.execute(select(User).where(User.id == revision.edited_by_user_id))
    ).scalar_one_or_none()
    current = await articles_service.latest_revision(db, actx.article.id)
    return await _revision_out(
        db,
        revision,
        edited_by=edited_by,
        is_current=current is not None and current.id == revision.id,
    )


# --- files -------------------------------------------------------------------
# The three-step handshake, identical shape to the task Files panel, just
# anchored to a revision. Step 3 (confirm) is deliberately NOT here — it's
# the one shared `/organisations/{org_id}/attachments/{id}/confirm` route in
# `conversations.py`, which already resolves an attachment's anchor (task,
# conversation, or now an article revision) generically via `_anchor_of`.


def _article_file_out(attachment: Attachment, who: User | None) -> ArticleFileOut:
    return ArticleFileOut(
        id=str(attachment.id),
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        url=attachments_service.view_url(attachment),
        thumbnail_url=attachments_service.thumbnail_url(attachment),
        uploaded_by=_person(who),
        created_at=attachment.created_at,
    )


@router.get("/revisions/{revision_id}/files", response_model=list[ArticleFileOut])
async def revision_files(revision_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Standalone files on this exact revision — scoped to the revision being
    viewed, not the whole article. See `services/articles.py`'s own
    docstring for why a fresh session starts with none."""
    revision = await _revision_or_404(db, revision_id)
    await articles_service.context_for(db, ctx, revision.article_id, user.id)
    files = await attachments_service.for_article_revision(db, revision.id)
    people = {}
    ids = {f.user_id for f in files if f.user_id}
    if ids:
        rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
        people = {u.id: u for u in rows}
    return [_article_file_out(f, people.get(f.user_id)) for f in files]


@router.post(
    "/revisions/{revision_id}/files", response_model=dict, status_code=status.HTTP_201_CREATED
)
async def stage_revision_file(
    revision_id: uuid.UUID, body: dict, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Step 1 of the handshake. `write` on the article, and the revision must
    still be the mutable "current" one — attaching to frozen history would
    silently misrepresent what that revision looked like when it was live."""
    revision = await _revision_or_404(db, revision_id)
    actx = await articles_service.context_for(db, ctx, revision.article_id, user.id)
    actx.require(
        access_service.can_write(actx.level), "you have read-only access to this article"
    )
    current = await articles_service.latest_revision(db, actx.article.id)
    if current is None or current.id != revision.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this revision is no longer the current one — reload and start a new session",
        )
    attachment, upload_url = await attachments_service.create(
        db,
        user,
        article_revision=revision,
        filename=str(body.get("filename") or ""),
        content_type=str(body.get("content_type") or ""),
    )
    return {
        "attachment": {"id": str(attachment.id), "filename": attachment.filename},
        "upload_url": upload_url,
        "content_type": attachment.content_type,
    }


@router.delete(
    "/revisions/{revision_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_revision_file(
    revision_id: uuid.UUID, file_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Yours, or the article owner's call — same convention `delete_task_file`
    already establishes."""
    revision = await _revision_or_404(db, revision_id)
    actx = await articles_service.context_for(db, ctx, revision.article_id, user.id)
    attachment = (
        await db.execute(
            select(Attachment).where(
                Attachment.id == file_id, Attachment.article_revision_id == revision_id
            )
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    mine = attachment.user_id == user.id
    actx.require(
        mine or access_service.can_administer(actx.level),
        "you can only remove files you added",
    )
    await attachments_service.delete(db, attachment)
