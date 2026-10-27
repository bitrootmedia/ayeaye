"""The weekly report's pure half: which week, how it reads.

The claim, the access scoping and the send are proved through Postgres by
`scripts/e2e-weekly-report.sh`.
"""

import uuid
from datetime import date

from app.services.weekly_report import (
    ADMIN_ROLES,
    OrgWeek,
    last_week,
    preview,
    render,
    week_label,
)


def test_last_week_from_any_day_is_the_previous_monday_to_sunday():
    # Monday 26 Oct 2026, the day it is sent.
    assert last_week(date(2026, 10, 26)) == (date(2026, 10, 19), date(2026, 10, 25))
    # Any later day in the same week still means the week before it.
    assert last_week(date(2026, 11, 1)) == (date(2026, 10, 19), date(2026, 10, 25))


def test_last_week_across_a_year():
    assert last_week(date(2027, 1, 4)) == (date(2026, 12, 28), date(2027, 1, 3))


def test_week_label():
    assert week_label(date(2026, 10, 19), date(2026, 10, 25)) == "19–25 Oct 2026"
    assert week_label(date(2026, 10, 26), date(2026, 11, 1)) == "26 Oct – 1 Nov 2026"
    assert week_label(date(2026, 12, 28), date(2027, 1, 3)) == "28 Dec 2026 – 3 Jan 2027"


def test_only_owners_and_admins_get_one():
    assert set(ADMIN_ROLES) == {"owner", "admin"}


def test_preview_keeps_a_short_fact_whole_and_cuts_a_long_one_at_a_word():
    assert preview("Short.\n  Two lines.") == "Short. Two lines."
    long = "word " * 60
    out = preview(long, 40)
    assert len(out) <= 40 and out.endswith("…") and "wor…" not in out


def _week(**kw) -> OrgWeek:
    return OrgWeek(uuid.uuid4(), "IntentLab", date(2026, 10, 19), date(2026, 10, 25), **kw)


def test_a_week_with_nothing_in_it_is_quiet():
    assert _week().is_quiet
    assert not _week(facts_count=1).is_quiet
    assert not _week(total_seconds=60).is_quiet


def test_render_says_the_whole_week_first_and_leaves_out_empty_sections():
    title, body = render(
        _week(
            total_seconds=9000,
            by_person=[("Alice", 5400), ("Bob", 3600)],
            closed=["Fix login (Alice)"],
            closed_count=1,
        )
    )
    assert title == "Week of 19–25 Oct 2026 in IntentLab"
    first = body.splitlines()[0]
    assert first == "2h 30m logged · 0 tasks opened · 1 closed · 0 articles · 0 facts"
    assert "- Alice: 1h 30m" in body and "- Bob: 1h" in body
    assert "Tasks closed (1):\n- Fix login (Alice)" in body
    assert "Tasks opened" not in body and "Facts added" not in body


def test_render_says_how_many_more_when_the_list_is_cut():
    _, body = render(_week(opened=["a", "b"], opened_count=12))
    assert "Tasks opened (12):" in body and "- …and 10 more" in body
