"""Work report arithmetic. No database — `now` and the zone are injected.

The failure a report has is a chart that adds up but says the wrong *when*:
a three-hour block drawn in the hour it began, an overnight entry counted
wholly on one day, a running timer counted into the future.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.organisation import ROLE_ADMIN, ROLE_MEMBER, ROLE_OWNER
from app.services.work_reports import (
    MAX_RANGE_DAYS,
    Row,
    aggregate,
    require_admin,
    spread,
    window,
    zone,
)

UTC_Z = zone("UTC")
NOW = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


def at(h, m=0, day=27):
    return datetime(2026, 10, day, h, m, tzinfo=UTC)


def row(started, ended, *, user=None, project=None):
    user = user or SimpleNamespace(id=uuid.uuid4(), display_name="Ann", email="a@x")
    task = SimpleNamespace(id=uuid.uuid4(), title="Sand the hull")
    entry = SimpleNamespace(started_at=started, ended_at=ended)
    return Row(entry, user, task, project, "Refit" if project else None)


# --- the gate ----------------------------------------------------------------


@pytest.mark.parametrize("role", [ROLE_OWNER, ROLE_ADMIN])
def test_admins_may_read_a_report(role):
    from app.services.organisations import OrgContext

    require_admin(OrgContext(None, SimpleNamespace(role=role)))


def test_a_member_is_refused_with_a_403_not_a_404():
    """They can see the organisation, just not at this level."""
    from app.services.organisations import OrgContext

    with pytest.raises(HTTPException) as exc:
        require_admin(OrgContext(None, SimpleNamespace(role=ROLE_MEMBER)))
    assert exc.value.status_code == 403


# --- the window --------------------------------------------------------------


def test_the_window_is_inclusive_of_both_dates():
    start, end = window(date(2026, 10, 1), date(2026, 10, 7), UTC_Z, now=NOW)
    assert start == datetime(2026, 10, 1, tzinfo=UTC)
    assert end == datetime(2026, 10, 8, tzinfo=UTC)


def test_a_window_including_today_ends_now():
    _, end = window(date(2026, 10, 21), date(2026, 10, 27), UTC_Z, now=NOW)
    assert end == NOW


def test_the_window_is_midnight_in_the_viewers_zone():
    start, _ = window(date(2026, 7, 1), date(2026, 7, 1), zone("Europe/Warsaw"), now=NOW)
    assert start.astimezone(UTC) == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)


def test_backwards_and_oversized_ranges_are_refused():
    with pytest.raises(HTTPException):
        window(date(2026, 10, 7), date(2026, 10, 1), UTC_Z, now=NOW)
    with pytest.raises(HTTPException):
        window(date(2025, 1, 1), date(2025, 1, 1) + timedelta(days=MAX_RANGE_DAYS), UTC_Z, now=NOW)


def test_a_zone_that_isnt_one_falls_back_to_utc():
    assert zone("Mars/Olympus").key == "UTC"
    assert zone(None).key == "UTC"


# --- spreading an entry across hours -----------------------------------------


def test_an_entry_lands_in_every_hour_it_covers():
    cells = list(spread(at(9, 30), at(12, 15), start=at(0), end=NOW, tz=UTC_Z, now=NOW))
    assert [(h.hour, s) for h, s in cells] == [(9, 1800), (10, 3600), (11, 3600), (12, 900)]


def test_an_entry_is_clipped_to_the_window():
    cells = list(spread(at(22, day=26), at(2), start=at(0), end=NOW, tz=UTC_Z, now=NOW))
    assert sum(s for _, s in cells) == 2 * 3600


def test_a_running_entry_counts_up_to_now_and_no_further():
    cells = list(spread(at(14), None, start=at(0), end=at(23), tz=UTC_Z, now=NOW))
    assert sum(s for _, s in cells) == 3600


def test_a_half_hour_zone_lands_on_its_own_hours():
    """India is UTC+5:30, so a UTC hour straddles two of its own."""
    cells = list(
        spread(at(4, 30), at(5, 30), start=at(0), end=NOW, tz=zone("Asia/Kolkata"), now=NOW)
    )
    assert [(h.hour, s) for h, s in cells] == [(10, 3600)]


# --- aggregating ---------------------------------------------------------------


def test_an_overnight_entry_is_split_across_both_days():
    start, end = window(date(2026, 10, 26), date(2026, 10, 27), UTC_Z, now=NOW)
    data = aggregate([row(at(23, 30, day=26), at(1, 15))], start=start, end=end, tz=UTC_Z, now=NOW)
    assert [(d["date"].day, d["seconds"]) for d in data["by_day"]] == [(26, 1800), (27, 4500)]
    assert data["total_seconds"] == 6300


def test_every_figure_adds_up_to_the_same_total():
    ann = SimpleNamespace(id=uuid.uuid4(), display_name="Ann", email="a@x")
    bob = SimpleNamespace(id=uuid.uuid4(), display_name=None, email="b@x")
    rows = [
        row(at(9), at(11), user=ann, project=uuid.uuid4()),
        row(at(13), None, user=bob),
        row(at(10, day=25), at(10, 45, day=25), user=ann),
    ]
    start, end = window(date(2026, 10, 21), date(2026, 10, 27), UTC_Z, now=NOW)
    data = aggregate(rows, start=start, end=end, tz=UTC_Z, now=NOW)
    total = data["total_seconds"]
    assert total == 2 * 3600 + 2 * 3600 + 45 * 60
    assert sum(r["seconds"] for r in data["by_person"]) == total
    assert sum(r["seconds"] for r in data["by_project"]) == total
    assert sum(d["seconds"] for d in data["by_day"]) == total
    assert sum(map(sum, data["by_hour"])) == total
    # A person with no display name is still named.
    assert {r["name"] for r in data["by_person"]} == {"Ann", "b@x"}
    # Loose tasks are grouped, not dropped.
    assert "No project" in {r["name"] for r in data["by_project"]}


def test_every_day_of_the_window_is_present_even_empty_ones():
    start, end = window(date(2026, 10, 21), date(2026, 10, 27), UTC_Z, now=NOW)
    data = aggregate([], start=start, end=end, tz=UTC_Z, now=NOW)
    assert len(data["by_day"]) == 7
    assert data["by_day"][0]["date"] == date(2026, 10, 21)
    assert data["by_day"][-1]["date"] == date(2026, 10, 27)


def test_the_grid_is_monday_first():
    start, end = window(date(2026, 10, 26), date(2026, 10, 27), UTC_Z, now=NOW)
    # 2026-10-26 is a Monday.
    data = aggregate([row(at(9, day=26), at(10, day=26))], start=start, end=end, tz=UTC_Z, now=NOW)
    assert data["by_hour"][0][9] == 3600


def test_slices_with_fractional_seconds_still_add_up_to_the_whole():
    """A 2h 30m entry starting at :54.6 is cut into four slices; truncating
    each one used to report it as 2h 29m."""
    begin = at(9, 54) + timedelta(seconds=0.6)
    start, end = window(date(2026, 10, 27), date(2026, 10, 27), UTC_Z, now=NOW)
    data = aggregate(
        [row(begin, begin + timedelta(minutes=150))], start=start, end=end, tz=UTC_Z, now=NOW
    )
    assert data["total_seconds"] == 150 * 60
