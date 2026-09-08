"""Bookmarks: the three bars, and URL normalisation.

No database. These are the parts that must be obviously correct — who may
pin, who may edit, and what is allowed into an `href` — and they are pure
functions precisely so they can be tested like this. The SQL half (ordering,
the organisation scope, 403-not-404) is proved through Postgres by
`scripts/e2e-bookmarks.sh`; neither test can cover the other's half, the
same split `tests/test_access_matrix.py` documents for the access model.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.services.bookmarks import can_edit, can_pin, normalise_url

ROLES = ["owner", "admin", "member"]


def test_only_an_owner_pins():
    """The one place this module is stricter than "an org admin can do
    anything" — a pinned link is what the whole organisation sees first."""
    assert can_pin("owner")
    assert not can_pin("admin")
    assert not can_pin("member")


def test_pinning_refuses_an_unknown_role():
    """A role that isn't in the set is not an owner. Fails closed rather than
    on a `ROLE_RANK` lookup that would raise or default."""
    assert not can_pin("")
    assert not can_pin("guest")


def test_the_author_may_edit_their_own():
    mine = uuid.uuid4()
    assert can_edit(role="member", created_by_user_id=mine, user_id=mine)


def test_a_member_may_not_edit_somebody_elses():
    assert not can_edit(role="member", created_by_user_id=uuid.uuid4(), user_id=uuid.uuid4())


def test_an_admin_may_edit_anybodys():
    """The ordinary escape hatch, unlike pinning above."""
    for role in ("owner", "admin"):
        assert can_edit(role=role, created_by_user_id=uuid.uuid4(), user_id=uuid.uuid4())


def test_an_orphaned_bookmark_is_editable_by_admins_alone():
    """`created_by_user_id` is NULL once its author is removed from the
    installation (SET NULL, see the model). Nobody it belongs to is left, so
    a plain member must not inherit it — a NULL author must never compare
    equal to the caller."""
    assert not can_edit(role="member", created_by_user_id=None, user_id=uuid.uuid4())
    assert can_edit(role="admin", created_by_user_id=None, user_id=uuid.uuid4())


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://example.com/docs", "https://example.com/docs"),
        ("http://example.com", "http://example.com"),
        ("  https://example.com  ", "https://example.com"),
        # A bare hostname: without a scheme this is a *relative* href and
        # navigates inside the app rather than out to the site.
        ("example.com", "https://example.com"),
        ("example.com/path?a=1&b=2", "https://example.com/path?a=1&b=2"),
        # Not a scheme, twice over: RFC 3986 allows dots and digits in one,
        # so a naive `^\w+:` pattern reads "example.com" and "localhost" as
        # schemes and refuses both as "not http". A dot in the candidate, or
        # a port number after the colon, is what rules that out.
        ("example.com:8080/admin", "https://example.com:8080/admin"),
        ("localhost:3000", "https://localhost:3000"),
        ("localhost:3000/dash", "https://localhost:3000/dash"),
        # Case is preserved; only the scheme is compared case-insensitively.
        ("HTTPS://Example.com/A", "HTTPS://Example.com/A"),
    ],
)
def test_normalise_url(raw, expected):
    assert normalise_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        # Stored XSS if any of these reached an href — which is exactly what
        # the bookmark list renders every row as.
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
    ],
)
def test_normalise_url_refuses_every_scheme_but_http(raw):
    with pytest.raises(HTTPException) as err:
        normalise_url(raw)
    assert err.value.status_code == 422


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_a_bookmark_needs_a_url(raw):
    with pytest.raises(HTTPException) as err:
        normalise_url(raw)
    assert err.value.status_code == 422


def test_a_url_too_long_is_refused_not_truncated():
    """Truncating a URL produces a link that goes somewhere else, which is
    worse than refusing it."""
    with pytest.raises(HTTPException) as err:
        normalise_url("https://example.com/" + "x" * 2000)
    assert err.value.status_code == 422
