"""`/org`'s name matching. No database, no HTTP — the same "pure function
over plain data" shape `test_task_rules.py` already uses for its own
notification rules.
"""

from app.services.telegram_commands import match_organisation

ACME = ("11111111-1111-1111-1111-111111111111", "Acme")
ACME_CORP = ("22222222-2222-2222-2222-222222222222", "Acme Corp")
BLUE_HORIZON = ("33333333-3333-3333-3333-333333333333", "Blue Horizon")
CHOICES = [ACME, ACME_CORP, BLUE_HORIZON]


def test_an_exact_match_wins_outright():
    result = match_organisation("Acme", CHOICES)
    assert result.organisation_id == ACME[0]
    assert result.ambiguous == []


def test_exact_match_is_case_insensitive():
    result = match_organisation("acme", CHOICES)
    assert result.organisation_id == ACME[0]


def test_exact_match_beats_being_a_substring_of_another_choice():
    """"Acme" is also a substring of "Acme Corp" — the exact match must win,
    not get reported as ambiguous."""
    result = match_organisation("Acme", CHOICES)
    assert result.organisation_id == ACME[0]


def test_a_unique_substring_matches_when_no_exact_match_exists():
    result = match_organisation("Blue", CHOICES)
    assert result.organisation_id == BLUE_HORIZON[0]


def test_a_substring_that_is_unique_still_matches():
    result = match_organisation("Corp", CHOICES)
    assert result.organisation_id == ACME_CORP[0]


def test_a_substring_matching_more_than_one_choice_is_ambiguous():
    """"Ac" matches neither name exactly, and is a substring of both —
    nothing here should be guessed at."""
    result = match_organisation("Ac", [ACME, ACME_CORP])
    assert result.organisation_id is None
    assert set(result.ambiguous) == {"Acme", "Acme Corp"}


def test_exact_match_among_several_identically_named_choices_is_ambiguous():
    """Two organisations can't collide on a name in this product, but the
    function shouldn't assume that — two exact matches is still reported,
    not picked arbitrarily."""
    result = match_organisation("Acme", [ACME, (ACME_CORP[0], "Acme")])
    assert result.organisation_id is None
    assert result.ambiguous == ["Acme", "Acme"]


def test_no_match_reports_nothing_rather_than_guessing():
    result = match_organisation("Nonexistent", CHOICES)
    assert result.organisation_id is None
    assert result.ambiguous == []


def test_no_choices_at_all_is_a_clean_no_match():
    result = match_organisation("Anything", [])
    assert result.organisation_id is None
    assert result.ambiguous == []
