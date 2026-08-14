"""The access matrix. No database, no fixtures, no infrastructure.

This is the test that earns the most in the whole suite, and it must stay
infra-free — the moment it needs a container, it stops being run on every save
and starts being run before releases.

It exercises `effective_level`, which is the Python statement of rule 2. The
SQL in `project_level_expression` is the same rule expressed for the planner;
the end-to-end script is what proves the two agree. Keeping both is deliberate:
this file catches the rule being wrong, the script catches the SQL being wrong.
"""

import itertools

import pytest

from app.models.organisation import ROLE_ADMIN, ROLE_MEMBER, ROLE_OWNER
from app.services.access import (
    administers_organisation,
    can_administer,
    can_read,
    can_write,
    effective_level,
    level_name,
    level_rank,
)

LEVELS = (None, "read", "write")
ORG_ROLES = (ROLE_MEMBER, ROLE_ADMIN, ROLE_OWNER)


# --- rule 1: private until shared -------------------------------------------


def test_a_plain_member_sees_nothing_by_default():
    """The headline rule. Being in the organisation is not access to its work."""
    assert effective_level(is_owner=False, org_role=ROLE_MEMBER) is None


def test_creating_a_project_does_not_publish_it():
    """The owner sees it; nobody else does until they're named."""
    assert effective_level(is_owner=True, org_role=ROLE_MEMBER) == "owner"
    assert effective_level(is_owner=False, org_role=ROLE_MEMBER) is None


def test_no_access_is_absence_not_a_level():
    """None, not "none" — a truthy string would sail through `can_read`."""
    assert effective_level(is_owner=False, org_role=ROLE_MEMBER) is None
    assert not can_read(None)


# --- rule 2: most-permissive-wins -------------------------------------------


@pytest.mark.parametrize(("direct", "team"), list(itertools.product(LEVELS, LEVELS)))
def test_the_best_route_wins(direct, team):
    expected = max(level_rank(direct), level_rank(team))
    got = effective_level(
        is_owner=False,
        org_role=ROLE_MEMBER,
        direct=direct,
        via_teams=(team,) if team else (),
    )
    assert got == level_name(expected)


def test_several_teams_take_the_best():
    assert (
        effective_level(is_owner=False, org_role=ROLE_MEMBER, via_teams=("read", "write", "read"))
        == "write"
    )


def test_a_weaker_direct_grant_cannot_reduce_a_team_grant():
    """The consequence people don't expect, so it gets its own test: you cannot
    carve an exception out of a broader grant. Naming someone `read` while
    their team has `write` leaves them at `write`. That needs deny rules, and
    we deliberately have none."""
    assert (
        effective_level(is_owner=False, org_role=ROLE_MEMBER, direct="read", via_teams=("write",))
        == "write"
    )


def test_ownership_beats_any_grant():
    assert (
        effective_level(is_owner=True, org_role=ROLE_MEMBER, direct="read", via_teams=("read",))
        == "owner"
    )


# --- organisation admins ------------------------------------------------------


@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_OWNER])
def test_org_admins_see_everything(role):
    """Stops "the only person who could see it has left" from being terminal."""
    assert effective_level(is_owner=False, org_role=role) == "owner"


def test_a_member_is_not_an_administrator():
    assert not administers_organisation(ROLE_MEMBER)
    assert administers_organisation(ROLE_ADMIN)
    assert administers_organisation(ROLE_OWNER)


def test_an_unknown_org_role_administers_nothing():
    """Fails closed. A typo'd or removed role must not become a skeleton key."""
    assert not administers_organisation("superuser")
    assert effective_level(is_owner=False, org_role="superuser") is None


# --- what each level lets you do ---------------------------------------------


@pytest.mark.parametrize(
    ("level", "read", "write", "administer"),
    [
        (None, False, False, False),
        ("read", True, False, False),
        ("write", True, True, False),
        ("owner", True, True, True),
    ],
)
def test_capabilities_per_level(level, read, write, administer):
    assert can_read(level) is read
    assert can_write(level) is write
    assert can_administer(level) is administer


def test_a_writer_cannot_change_who_else_can_see_it():
    """The product decision: a `write` grantee edits the work, but access stays
    with the person responsible for it."""
    assert can_write("write")
    assert not can_administer("write")


def test_an_unknown_level_grants_nothing():
    assert not can_read("superuser")
    assert level_rank("superuser") == -1


# --- the whole grid, as one table --------------------------------------------


@pytest.mark.parametrize(
    ("is_owner", "org_role", "direct", "team"),
    list(itertools.product((False, True), ORG_ROLES, LEVELS, LEVELS)),
)
def test_the_full_matrix_is_monotonic(is_owner, org_role, direct, team):
    """Whatever the combination, adding a route can only ever increase access.

    Checked against a from-scratch computation rather than the implementation,
    so a bug that reorders the max can't satisfy both.
    """
    got = effective_level(
        is_owner=is_owner,
        org_role=org_role,
        direct=direct,
        via_teams=(team,) if team else (),
    )
    routes = [level_rank(direct), level_rank(team)]
    if is_owner or org_role in (ROLE_ADMIN, ROLE_OWNER):
        routes.append(2)
    assert got == level_name(max(routes))
