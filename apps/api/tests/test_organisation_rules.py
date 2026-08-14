"""The membership rules, as a matrix. No database, no HTTP, no fixtures.

These are the four rules from the `services/organisations` docstring. They are
worth testing exhaustively and cheaply, because every one of them fails
*silently* — a privilege that's too generous doesn't raise, it just quietly
lets someone do something. The same discipline applies to the access matrix in
Phase 3, which is the reason this file is shaped the way it is.
"""

import pytest

from app.models.organisation import ROLE_ADMIN, ROLE_MEMBER, ROLE_OWNER, ROLES
from app.services.organisations import (
    can_act_on_member,
    can_delete_organisation,
    can_grant_role,
    can_manage_members,
    can_rename_organisation,
    role_at_least,
    slugify,
)

EVERY_PAIR = [(a, b) for a in ROLES for b in ROLES]


# --- rule 2: you may only hand out a role you hold ---------------------------


@pytest.mark.parametrize(
    ("actor", "grants"),
    [
        (ROLE_OWNER, {ROLE_MEMBER, ROLE_ADMIN, ROLE_OWNER}),
        (ROLE_ADMIN, {ROLE_MEMBER, ROLE_ADMIN}),
        (ROLE_MEMBER, set()),
    ],
)
def test_you_can_only_grant_a_role_you_hold(actor, grants):
    for role in ROLES:
        assert can_grant_role(actor, role) is (role in grants)


def test_an_admin_cannot_appoint_an_owner():
    """Otherwise `admin` is just a slower route to `owner`, and the distinction
    between the two stops meaning anything."""
    assert not can_grant_role(ROLE_ADMIN, ROLE_OWNER)


def test_an_unknown_role_can_never_be_granted():
    """A typo'd role must fail closed. It's rejected by the schema and the
    CHECK constraint too, but a rule that fails *open* on unknown input is the
    kind of thing that survives a refactor."""
    for actor in ROLES:
        assert not can_grant_role(actor, "superuser")
        assert not can_grant_role(actor, "")


def test_an_unknown_actor_role_grants_nothing():
    for role in ROLES:
        assert not can_grant_role("ghost", role)


# --- rule 3: you may not act on someone above you ----------------------------


@pytest.mark.parametrize(("actor", "subject"), EVERY_PAIR)
def test_acting_on_a_member_follows_rank(actor, subject):
    from app.models.organisation import ROLE_RANK

    assert can_act_on_member(actor, subject) is (ROLE_RANK[actor] >= ROLE_RANK[subject])


def test_equal_rank_can_act_on_each_other():
    """Two admins manage each other. This is what makes "an org admin can do
    anything" true in practice rather than only on paper."""
    assert can_act_on_member(ROLE_ADMIN, ROLE_ADMIN)
    assert can_act_on_member(ROLE_OWNER, ROLE_OWNER)


def test_an_admin_cannot_touch_an_owner():
    assert not can_act_on_member(ROLE_ADMIN, ROLE_OWNER)


def test_a_member_cannot_act_on_anyone():
    for subject in ROLES:
        assert not can_manage_members(ROLE_MEMBER) or can_act_on_member(ROLE_MEMBER, subject)
    assert not can_manage_members(ROLE_MEMBER)


# --- what each role may do to the organisation itself ------------------------


def test_only_an_owner_deletes_the_organisation():
    """Deleting destroys everyone's work, which is more than "anything an admin
    can do"."""
    assert can_delete_organisation(ROLE_OWNER)
    assert not can_delete_organisation(ROLE_ADMIN)
    assert not can_delete_organisation(ROLE_MEMBER)


def test_admins_and_owners_rename():
    assert can_rename_organisation(ROLE_OWNER)
    assert can_rename_organisation(ROLE_ADMIN)
    assert not can_rename_organisation(ROLE_MEMBER)


def test_managing_members_needs_admin_or_above():
    assert can_manage_members(ROLE_OWNER)
    assert can_manage_members(ROLE_ADMIN)
    assert not can_manage_members(ROLE_MEMBER)


def test_role_at_least_is_closed_against_unknown_roles():
    assert not role_at_least("ghost", ROLE_MEMBER)


# --- slugs -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Acme", "acme"),
        ("  Acme Corp  ", "acme-corp"),
        ("Acme & Co.", "acme-co"),
        ("A—B", "a-b"),
        ("acme---corp", "acme-corp"),
    ],
)
def test_slugify(name, expected):
    assert slugify(name) == expected


def test_a_name_with_nothing_sluggable_still_yields_a_slug():
    """A name in non-Latin script or pure punctuation would otherwise slugify
    to "", making the uniqueness suffix the whole identifier — so `/orgs/-2`."""
    assert slugify("!!!") == "org"
    assert slugify("日本語") == "org"


def test_slugs_are_bounded():
    """The column is 140 and the suffix has to fit."""
    assert len(slugify("x" * 500)) <= 100
