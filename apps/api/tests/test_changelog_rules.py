"""The changelog: who may change an entry, and what is allowed into one.

No database. These are the parts that must be obviously correct — the edit
bar, and the fact that an empty or oversized description is refused rather
than quietly stored or quietly cut — and they are pure functions precisely so
they can be tested like this. The SQL half (the newest-first order, the
organisation scope, 403-not-404, paging and `X-Total-Count`) is proved
through Postgres by `scripts/e2e-changelog.sh`; neither test can cover the
other's half, the same split `tests/test_access_matrix.py` documents for the
access model.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.models.changelog import MAX_DESCRIPTION_LENGTH
from app.services.changelog import can_edit, clean_description


def test_the_author_may_edit_their_own():
    mine = uuid.uuid4()
    assert can_edit(role="member", created_by_user_id=mine, user_id=mine)


def test_a_member_may_not_edit_somebody_elses():
    """Only testable between two plain members — an entry somebody else wrote
    down is not yours to rewrite."""
    assert not can_edit(role="member", created_by_user_id=uuid.uuid4(), user_id=uuid.uuid4())


def test_an_admin_may_edit_anybodys():
    """The ordinary escape hatch. Unlike a bookmark's pin, there is nothing
    here an admin can't do."""
    for role in ("owner", "admin"):
        assert can_edit(role=role, created_by_user_id=uuid.uuid4(), user_id=uuid.uuid4())


def test_an_orphaned_entry_is_editable_by_admins_alone():
    """`created_by_user_id` is NULL once its author is removed from the
    installation (SET NULL, see the model). Nobody it belongs to is left, so a
    plain member must not inherit it — a NULL author must never compare equal
    to the caller."""
    assert not can_edit(role="member", created_by_user_id=None, user_id=uuid.uuid4())
    assert can_edit(role="admin", created_by_user_id=None, user_id=uuid.uuid4())


def test_an_unknown_role_is_not_an_admin():
    """Fails closed rather than on a `ROLE_RANK` lookup that would raise."""
    assert not can_edit(role="guest", created_by_user_id=uuid.uuid4(), user_id=uuid.uuid4())


@pytest.mark.parametrize("raw", ["", "   ", "\n\t ", None])
def test_an_empty_description_is_refused(raw):
    """A date with nothing beside it is not an entry."""
    with pytest.raises(HTTPException) as exc:
        clean_description(raw)
    assert exc.value.status_code == 422


def test_a_description_is_trimmed():
    assert clean_description("  BingAds version lift  ") == "BingAds version lift"


def test_an_oversized_description_is_refused_not_truncated():
    """Refused, the same call `bookmarks.normalise_url` makes for a long URL:
    an entry cut in half says something other than what was written, and a
    changelog people can't trust literally is not one."""
    with pytest.raises(HTTPException) as exc:
        clean_description("x" * (MAX_DESCRIPTION_LENGTH + 1))
    assert exc.value.status_code == 422
    # Right at the limit is fine — the boundary is inclusive.
    assert len(clean_description("x" * MAX_DESCRIPTION_LENGTH)) == MAX_DESCRIPTION_LENGTH
