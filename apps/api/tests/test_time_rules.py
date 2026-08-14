"""Time tracking rules. No database, no clock of its own — `now` is injected.

A time tracker's failures are quiet: a duration that's off by an hour, an entry
that survives validation and poisons every rollup it lands in, a correction
somebody else was allowed to make. None of them raise at the time.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models.organisation import ROLE_ADMIN, ROLE_MEMBER, ROLE_OWNER
from app.services.time_tracking import (
    MAX_ENTRY_HOURS,
    can_edit_entry,
    duration_seconds,
    format_duration,
    validate_manual,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
ME, THEM = uuid.uuid4(), uuid.uuid4()


# --- durations ---------------------------------------------------------------


def test_a_finished_entry_measures_itself():
    assert duration_seconds(NOW - timedelta(minutes=90), NOW, now=NOW) == 5400


def test_a_running_entry_measures_against_now():
    """`ended_at IS NULL` is what "running" means, so its length is a function
    of the current time rather than of anything stored."""
    assert duration_seconds(NOW - timedelta(minutes=5), None, now=NOW) == 300


def test_a_clock_that_went_backwards_yields_zero_not_a_negative():
    """Server and client clocks disagree. A negative duration would subtract
    from a rollup, which is worse than a zero."""
    assert duration_seconds(NOW + timedelta(minutes=5), None, now=NOW) == 0


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0m"),
        (59, "0m"),
        (60, "1m"),
        (3600, "1h"),
        (5400, "1h 30m"),
        (86400, "24h"),
        (90, "1m"),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_a_whole_number_of_hours_has_no_stray_minutes():
    """"2h 0m" reads as a rounding error rather than as two hours."""
    assert format_duration(7200) == "2h"


# --- validating a manual entry ------------------------------------------------


def test_a_normal_entry_passes():
    validate_manual(started_at=NOW - timedelta(hours=2), ended_at=NOW, now=NOW)


def test_an_entry_that_ends_before_it_starts_is_refused():
    with pytest.raises(HTTPException) as exc:
        validate_manual(started_at=NOW, ended_at=NOW - timedelta(hours=1), now=NOW)
    assert exc.value.status_code == 422


def test_a_zero_length_entry_is_refused():
    """Always a mistake, and it makes averages lie."""
    with pytest.raises(HTTPException):
        validate_manual(started_at=NOW, ended_at=NOW, now=NOW)


def test_logging_time_in_the_future_is_refused():
    with pytest.raises(HTTPException) as exc:
        validate_manual(
            started_at=NOW + timedelta(days=1),
            ended_at=NOW + timedelta(days=1, hours=1),
            now=NOW,
        )
    assert "future" in exc.value.detail


def test_a_little_clock_skew_is_tolerated():
    """Browser and server clocks drift. Rejecting an entry stamped two minutes
    ahead would fail for reasons the person cannot see or fix."""
    validate_manual(
        started_at=NOW + timedelta(minutes=2),
        ended_at=NOW + timedelta(minutes=32),
        now=NOW,
    )


def test_an_absurdly_long_entry_is_refused():
    """A manual entry longer than a day is a typo — "800" minutes meant 80.
    Caught at the door, because afterwards it just looks like data."""
    with pytest.raises(HTTPException) as exc:
        validate_manual(
            started_at=NOW - timedelta(hours=MAX_ENTRY_HOURS + 1), ended_at=NOW, now=NOW
        )
    assert "24 hours" in exc.value.detail


def test_exactly_the_limit_is_allowed():
    validate_manual(started_at=NOW - timedelta(hours=MAX_ENTRY_HOURS), ended_at=NOW, now=NOW)


# --- who may correct an entry --------------------------------------------------


def test_you_can_edit_your_own():
    assert can_edit_entry(entry_user_id=ME, actor_id=ME, org_role=ROLE_MEMBER)


def test_you_cannot_edit_someone_elses():
    assert not can_edit_entry(entry_user_id=THEM, actor_id=ME, org_role=ROLE_MEMBER)


@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_OWNER])
def test_an_org_admin_can_correct_anyone(role):
    """The escape hatch for a timesheet whose owner has left."""
    assert can_edit_entry(entry_user_id=THEM, actor_id=ME, org_role=role)


def test_the_task_owner_is_not_special_here():
    """Deliberate: someone else's timesheet is not yours to edit, even on work
    you're responsible for. Task ownership grants nothing on this axis, which
    is why the function doesn't take it as an argument at all."""
    assert not can_edit_entry(entry_user_id=THEM, actor_id=ME, org_role=ROLE_MEMBER)


def test_an_unknown_role_grants_no_override():
    assert not can_edit_entry(entry_user_id=THEM, actor_id=ME, org_role="superuser")
