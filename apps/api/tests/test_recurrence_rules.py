"""Recurring tasks: the date math. No database, no HTTP.

`advance()` is the one part of the recurrence sweep worth pinning without
infrastructure — everything else in `services/recurrence.py` is a query or a
conditional UPDATE, tested through `scripts/e2e-recurring-tasks.sh` instead,
the same split `test_access_matrix.py`'s own docstring explains.
"""

from datetime import date

from app.services.recurrence import advance


def test_a_day_is_a_day():
    assert advance(date(2026, 1, 1), "day", 1) == date(2026, 1, 2)
    assert advance(date(2026, 1, 1), "day", 10) == date(2026, 1, 11)


def test_a_week_is_seven_days():
    assert advance(date(2026, 1, 1), "week", 1) == date(2026, 1, 8)
    assert advance(date(2026, 1, 1), "week", 2) == date(2026, 1, 15)


def test_a_month_lands_on_the_same_day_next_month():
    assert advance(date(2026, 1, 15), "month", 1) == date(2026, 2, 15)


def test_a_month_crosses_a_year_boundary():
    assert advance(date(2026, 12, 5), "month", 1) == date(2027, 1, 5)
    assert advance(date(2026, 12, 5), "month", 13) == date(2028, 1, 5)


def test_the_31st_clamps_to_the_shorter_month_rather_than_overflowing():
    """The trap naive `+ timedelta(days=30)` arithmetic falls into: January
    31st plus a month is February 28th (or 29th), not March 2nd or 3rd."""
    assert advance(date(2026, 1, 31), "month", 1) == date(2026, 2, 28)
    assert advance(date(2024, 1, 31), "month", 1) == date(2024, 2, 29)  # leap year


def test_a_multi_month_interval_also_clamps():
    assert advance(date(2026, 1, 31), "month", 3) == date(2026, 4, 30)
