"""The knowledge base access rules. No database, no fixtures.

`effective_article_level` is the pure statement of rule 2 for an article —
see `services/access.py`'s own docstring on it. A book's own rule needs no
new function at all: `effective_level` already is `effective_book_level`,
since a project's and a book's grants are the identical shape. That's tested
exhaustively for projects already in `test_access_matrix.py`; nothing here
repeats it.
"""

import itertools

import pytest

from app.models.organisation import ROLE_ADMIN, ROLE_MEMBER, ROLE_OWNER
from app.services.access import effective_article_level, level_name, level_rank

LEVELS = (None, "read", "write")
ORG_ROLES = (ROLE_MEMBER, ROLE_ADMIN, ROLE_OWNER)


# --- a private article: the one place access is subtracted -------------------


def test_a_new_articles_default_is_private_and_owner_only():
    assert effective_article_level(org_role=ROLE_MEMBER, is_private=True, is_owner=True) == "owner"
    assert effective_article_level(org_role=ROLE_MEMBER, is_private=True) is None


def test_private_beats_every_book_grant():
    assert (
        effective_article_level(org_role=ROLE_MEMBER, is_private=True, book_level="write") is None
    )


@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_OWNER])
def test_private_beats_organisation_admin(role):
    """The identical deliberate hole a hidden task has: an admin cannot see a
    private article either. The recovery path is the same as everywhere
    else this hole exists — there isn't a colleague-facing one."""
    assert effective_article_level(org_role=role, is_private=True) is None


@pytest.mark.parametrize(
    "book_level",
    LEVELS,
)
def test_no_book_grant_survives_privacy(book_level):
    assert (
        effective_article_level(org_role=ROLE_MEMBER, is_private=True, book_level=book_level)
        is None
    )


# --- published: the book's own rule flows down --------------------------------


def test_a_published_article_follows_the_books_level():
    assert (
        effective_article_level(org_role=ROLE_MEMBER, is_private=False, book_level="write")
        == "write"
    )
    assert (
        effective_article_level(org_role=ROLE_MEMBER, is_private=False, book_level="read")
        == "read"
    )


def test_no_book_access_means_no_article_access():
    assert effective_article_level(org_role=ROLE_MEMBER, is_private=False) is None


def test_ownership_beats_the_books_own_level():
    assert (
        effective_article_level(
            org_role=ROLE_MEMBER, is_private=False, is_owner=True, book_level="read"
        )
        == "owner"
    )


@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_OWNER])
def test_org_admins_see_every_published_article(role):
    """Folded in through `book_level_expression`'s own admin override — an
    admin who can see every book can see every non-private article in it."""
    assert effective_article_level(org_role=role, is_private=False) == "owner"


@pytest.mark.parametrize(
    ("book_level", "is_owner"),
    list(itertools.product(LEVELS, (False, True))),
)
def test_the_grid_is_the_max_of_book_level_and_ownership(book_level, is_owner):
    got = effective_article_level(
        org_role=ROLE_MEMBER, is_private=False, is_owner=is_owner, book_level=book_level
    )
    expected = max(level_rank(book_level), level_rank("owner") if is_owner else -1)
    assert got == level_name(expected)
