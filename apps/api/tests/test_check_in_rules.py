""" "Still working on this?" — the parts that need no database.

The failures here would be quiet: a question asked at a predictable minute, a
daily cap counted in the server's day rather than the person's, a Telegram
button whose data no longer parses and so silently does nothing.
"""

import random
import uuid
from datetime import UTC, date, datetime, timedelta

from app.services.check_ins import (
    ANSWER_STOP,
    ANSWER_YES,
    EVERY,
    GRACE,
    callback_data,
    has_allowance,
    local_day,
    parse_callback,
    pick,
)

NOW = datetime(2026, 10, 20, 23, 30, tzinfo=UTC)
TODAY = date(2026, 10, 20)


def test_picks_land_inside_their_range_and_vary():
    rng = random.Random(7)
    for span in (EVERY, GRACE):
        picks = {pick(span, rng) for _ in range(200)}
        assert all(span[0] <= p <= span[1] for p in picks)
        # Random to the second, not to the hour: a question that can be
        # anticipated can be answered in advance.
        assert len(picks) > 100


def test_the_ranges_are_the_ones_promised():
    assert EVERY == (timedelta(minutes=60), timedelta(minutes=120))
    assert GRACE == (timedelta(minutes=15), timedelta(minutes=30))


def test_the_day_is_the_persons_own():
    """23:30 UTC is already tomorrow in Warsaw — the cap resets at their
    midnight, not the server's."""
    assert local_day(NOW, "UTC") == TODAY
    assert local_day(NOW, "Europe/Warsaw") == TODAY + timedelta(days=1)


def test_an_unknown_zone_is_utc_not_an_error():
    assert local_day(NOW, None) == TODAY
    assert local_day(NOW, "Mars/Olympus_Mons") == TODAY


def test_allowance():
    assert has_allowance(day=TODAY, count=5, today=TODAY, per_day=6)
    assert not has_allowance(day=TODAY, count=6, today=TODAY, per_day=6)
    # Yesterday's count is no count at all today.
    assert has_allowance(day=TODAY - timedelta(days=1), count=6, today=TODAY, per_day=6)
    assert has_allowance(day=None, count=0, today=TODAY, per_day=1)


def test_callback_data_round_trips_and_fits_telegrams_limit():
    entry = uuid.uuid4()
    for action in (ANSWER_YES, ANSWER_STOP):
        data = callback_data(action, entry)
        assert len(data.encode()) <= 64
        assert parse_callback(data) == (action, entry)


def test_anything_else_parses_to_nothing():
    for data in (
        "",
        "checkin",
        "checkin:maybe:" + str(uuid.uuid4()),
        "checkin:yes:not-a-uuid",
        "other:yes:" + str(uuid.uuid4()),
        "checkin:yes:x:y",
    ):
        assert parse_callback(data) is None
