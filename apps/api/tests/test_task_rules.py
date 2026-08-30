"""Task workflow and task access. No database, no HTTP.

Every rule here fails *silently* if it's wrong: a notification that doesn't
arrive, a notification that arrives twice, an access route that quietly opens.
None of them raise, so a test is the only thing that catches them.
"""

import itertools
import uuid

import pytest

from app.models.notification import NOTIFICATION_KINDS
from app.models.organisation import ROLE_ADMIN, ROLE_MEMBER, ROLE_OWNER
from app.models.task import EVENT_KINDS, STATUS_TODO, STATUSES
from app.services.access import effective_task_level, level_name, level_rank
from app.services.tasks import (
    can_close,
    can_edit,
    can_hide,
    can_manage_access,
    describe_status,
    is_valid_status,
    should_notify_action_required,
    should_notify_handback,
)

A, B, C = (uuid.uuid4() for _ in range(3))
LEVELS = (None, "read", "write")


# --- the status set ----------------------------------------------------------


def test_the_status_set_is_the_agreed_one():
    """Five, with TODO as the landing spot for new work. If ON HOLD were the
    default it would be the commonest status in the system and would stop
    meaning "deliberately parked"."""
    assert STATUSES == ("todo", "in_progress", "on_hold", "review", "blocker")
    assert STATUS_TODO == "todo"


def test_unknown_statuses_are_rejected():
    assert is_valid_status("todo")
    assert not is_valid_status("done")
    assert not is_valid_status("")


def test_there_is_no_done_status():
    """Finishing is `closed`, which is a separate field. A `done` status would
    give two contradictory answers to "is this finished"."""
    assert "done" not in STATUSES
    assert "closed" not in STATUSES


def test_every_status_has_a_label():
    for status in STATUSES:
        assert describe_status(status) != status or status == describe_status(status)
        assert describe_status(status)


# --- rule 1: only the owner closes -------------------------------------------


def test_only_the_owner_closes():
    assert can_close(level="owner", is_owner=True)
    # An editor can change everything about the task except finish it.
    assert not can_close(level="write", is_owner=False)
    assert not can_close(level="read", is_owner=False)


def test_an_org_admin_can_close_someone_elses_task():
    """`owner` level is what administering the organisation resolves to. This
    is the escape hatch for a task whose owner has left."""
    assert can_close(level="owner", is_owner=False)


def test_an_editor_can_edit_but_not_hand_over():
    assert can_edit("write")
    assert not can_manage_access(level="write", is_owner=False)
    assert can_manage_access(level="write", is_owner=True)


def test_a_reader_can_do_nothing_but_read():
    assert not can_edit("read")
    assert not can_close(level="read", is_owner=False)
    assert not can_manage_access(level="read", is_owner=False)


# --- rule 3: notify on the transition, not on the write ----------------------


def test_setting_action_required_notifies():
    assert should_notify_action_required(previous=None, incoming=B, actor=A)


def test_setting_it_to_the_same_person_does_not_re_notify():
    """The one that matters. Every save resubmits the whole form, so a naive
    "if incoming: send" pings that person on every keystroke-save."""
    assert not should_notify_action_required(previous=B, incoming=B, actor=A)


def test_clearing_it_notifies_nobody():
    assert not should_notify_action_required(previous=B, incoming=None, actor=A)


def test_putting_it_on_yourself_notifies_nobody():
    assert not should_notify_action_required(previous=None, incoming=A, actor=A)


def test_moving_it_to_someone_else_notifies_them():
    assert should_notify_action_required(previous=B, incoming=C, actor=A)


# --- the other half: notify the owner on handback -----------------------------


def test_clearing_it_notifies_the_owner():
    assert should_notify_handback(previous=B, incoming=None, owner_id=C, actor=A)


def test_the_owner_clearing_their_own_notifies_nobody():
    """The common case: an owner clears action-required on their own task.
    They already know."""
    assert not should_notify_handback(previous=B, incoming=None, owner_id=A, actor=A)


def test_setting_it_does_not_trigger_a_handback():
    assert not should_notify_handback(previous=None, incoming=B, owner_id=C, actor=A)


def test_moving_it_to_someone_else_is_not_a_handback():
    """Still with someone — just not this someone. The new assignee already
    gets their own notification from should_notify_action_required."""
    assert not should_notify_handback(previous=B, incoming=C, owner_id=A, actor=A)


def test_there_was_nothing_to_hand_back():
    assert not should_notify_handback(previous=None, incoming=None, owner_id=C, actor=A)


# --- task access: the routes in ------------------------------------------------


def test_a_loose_task_is_not_visible_to_the_organisation():
    """PLAN.md §4's open question, settled: "no project" is a deliberate
    choice, not a leak."""
    assert effective_task_level(org_role=ROLE_MEMBER) is None


def test_the_owner_of_a_loose_task_sees_it():
    assert effective_task_level(org_role=ROLE_MEMBER, is_owner=True) == "owner"


def test_being_asked_to_act_carries_its_own_access():
    """You cannot ask someone to act on something they can't open — including
    on a project they've never been given."""
    assert effective_task_level(org_role=ROLE_MEMBER, is_action_required=True) == "write"


def test_the_creator_keeps_sight_of_what_they_filed():
    assert effective_task_level(org_role=ROLE_MEMBER, is_creator=True) == "read"


def test_project_access_flows_down_to_tasks():
    assert effective_task_level(org_role=ROLE_MEMBER, project_level="write") == "write"
    assert effective_task_level(org_role=ROLE_MEMBER, project_level="read") == "read"


def test_a_task_grant_is_additive_to_the_project():
    """You can raise someone from read to write on one task…"""
    assert (
        effective_task_level(org_role=ROLE_MEMBER, project_level="read", direct="write")
        == "write"
    )


def test_a_task_grant_cannot_take_project_access_away():
    """…but not the reverse. That would be a deny rule, and there are none."""
    assert (
        effective_task_level(org_role=ROLE_MEMBER, project_level="write", direct="read")
        == "write"
    )


@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_OWNER])
def test_org_admins_see_every_task_including_loose_ones(role):
    assert effective_task_level(org_role=role) == "owner"


def test_ownership_beats_everything_else():
    assert (
        effective_task_level(
            org_role=ROLE_MEMBER, is_owner=True, project_level="read", direct="read"
        )
        == "owner"
    )


@pytest.mark.parametrize(
    ("project_level", "direct", "team"),
    list(itertools.product(LEVELS, LEVELS, LEVELS)),
)
def test_the_grid_is_the_max_of_every_route(project_level, direct, team):
    """Computed from scratch rather than by calling the implementation, so a
    bug that reorders the max can't satisfy both sides."""
    got = effective_task_level(
        org_role=ROLE_MEMBER,
        project_level=project_level,
        direct=direct,
        via_teams=(team,) if team else (),
    )
    expected = max(level_rank(project_level), level_rank(direct), level_rank(team))
    assert got == level_name(expected)


# --- hidden: the one place access is subtracted -------------------------------
#
# Every one of these would pass if `is_hidden` were quietly dropped from the
# signature, except that each asserts a *denial*. They are the tests that stop
# a refactor from turning "private to me" into "private from colleagues".


def test_a_hidden_task_is_invisible_to_everyone_but_its_owner():
    assert (
        effective_task_level(
            org_role=ROLE_MEMBER, is_hidden=True, project_level="write", direct="write"
        )
        is None
    )


def test_the_owner_still_sees_their_own_hidden_task():
    assert effective_task_level(org_role=ROLE_MEMBER, is_hidden=True, is_owner=True) == "owner"


@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_OWNER])
def test_hiding_beats_organisation_admin(role):
    """**The one deliberate hole in "an admin can do anything."**

    Stated as its own test because it contradicts a rule written down in three
    other places, and someone reading only those would 'fix' it. The recovery
    path when the owner leaves is offboarding, which reassigns ownership.
    """
    assert effective_task_level(org_role=role, is_hidden=True) is None


def test_hiding_beats_being_asked_to_act():
    """Which is why `set_hidden` refuses while somebody else is named: the
    access would go, and their notification would 404."""
    assert (
        effective_task_level(org_role=ROLE_MEMBER, is_hidden=True, is_action_required=True)
        is None
    )


def test_hiding_beats_having_created_it():
    assert effective_task_level(org_role=ROLE_MEMBER, is_hidden=True, is_creator=True) is None


@pytest.mark.parametrize(
    ("project_level", "direct", "team"),
    list(itertools.product(LEVELS, LEVELS, LEVELS)),
)
def test_no_combination_of_grants_survives_hiding(project_level, direct, team):
    """The whole grid again, with `is_hidden` on. Nothing gets through.

    Hiding is a precondition, not a route with a low rank — so this is the
    grid collapsing to a single answer rather than the max changing.
    """
    assert (
        effective_task_level(
            org_role=ROLE_MEMBER,
            is_hidden=True,
            project_level=project_level,
            direct=direct,
            via_teams=(team,) if team else (),
        )
        is None
    )


def test_only_the_owner_may_hide_not_an_admin():
    """`can_hide` is deliberately not `can_close`'s rule. An admin hiding a
    task they don't own would be hiding it from themselves."""
    assert can_hide(is_owner=True)
    assert not can_hide(is_owner=False)
    # …whereas closing still admits an org admin, resolved to `owner` level.
    assert can_close(level="owner", is_owner=False)


# --- closed sets that a migration could drift from ---------------------------


def test_event_kinds_cover_every_workflow_change():
    """A change with no event kind is a change that vanishes from the history —
    and the history IS the record of work (PLAN.md §3)."""
    for kind in (
        "created",
        "status_changed",
        "closed",
        "reopened",
        "owner_changed",
        "action_required_set",
        "action_required_cleared",
    ):
        assert kind in EVENT_KINDS


def test_notification_kinds_are_a_closed_set():
    """Pinned against the CHECK constraint in migration 0004 (extended in
    0013 and 0019). Adding a kind in Python without the matching migration
    raises an IntegrityError at the worst possible moment — while notifying
    somebody."""
    assert set(NOTIFICATION_KINDS) == {
        "task_action_required",
        # The other half of the loop — nobody is action-required anymore,
        # notify the owner it's back with them.
        "task_action_required_cleared",
        "task_owner_changed",
        "task_closed",
        "task_shared",
        "project_shared",
        # Reminders fire twice — the day before and on the day — and the two
        # read differently in an inbox, so they are two kinds.
        "reminder_soon",
        "reminder_due",
        # The deadline sweep: a not-closed task due tomorrow. Only ever one
        # kind — there is no "due today" nudge the way reminders have both.
        "task_deadline_tomorrow",
        # The daily digest: today's plan and yesterday's done, always
        # together in one notification, so there's nothing for a second kind
        # to distinguish.
        "daily_summary",
        # A data export finished — success and failure share this one kind,
        # distinguished by the notification's own title/body.
        "export_ready",
    }
