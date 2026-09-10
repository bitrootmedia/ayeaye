"""Reading `@Name` out of a comment. No database, no HTTP — the fiddly half of
mentions is a pure function, the same "pure function over plain data" shape
`test_telegram_commands.py` already uses for `/org`'s name matching.

The access half is proved through Postgres instead (`scripts/e2e-comments.sh`),
the same split `test_access_matrix.py`'s own docstring explains: neither test
can cover the other's job.
"""

from app.services.mentions import find_mentions, needles


def pairs(*people: tuple[str, str | None, str]) -> list[tuple[str, str]]:
    """(display_name, email, key) → the (needle, key) pairs the parser takes."""
    return [
        (needle, key)
        for display_name, email, key in people
        for needle in needles(display_name, email)
    ]


ALICE = ("Alice Fisher", "alice@example.com", "alice")
BOB = ("Bob", "bob@example.com", "bob")
CREW = pairs(ALICE, BOB)


def test_a_display_name_with_a_space_is_matched_whole():
    assert find_mentions("@Alice Fisher can you look?", CREW) == ["alice"]


def test_matching_is_case_insensitive():
    assert find_mentions("@alice fisher please", CREW) == ["alice"]


def test_an_email_names_somebody_too():
    assert find_mentions("@bob@example.com ping", CREW) == ["bob"]


def test_so_does_the_local_part_alone():
    """What somebody types when a colleague has never set a display name."""
    assert find_mentions("@bob have a look", CREW) == ["bob"]


def test_an_email_address_in_prose_is_not_a_mention():
    """The `@` follows a word character, so it is an address, not a name."""
    assert find_mentions("write to alice@example.com about it", CREW) == []


def test_punctuation_right_after_a_name_still_matches():
    assert find_mentions("thanks @Bob, that's fixed", CREW) == ["bob"]


def test_a_name_inside_a_longer_word_does_not_match():
    assert find_mentions("@Bobby is somebody else", CREW) == []


def test_the_longest_candidate_wins():
    """Two people whose names are prefixes of each other is the ordinary
    case, not the edge one — an organisation with a Sam and a Samantha."""
    crew = pairs(("Sam", None, "sam"), ("Samantha", None, "samantha"))
    assert find_mentions("@Samantha please", crew) == ["samantha"]
    assert find_mentions("@Sam please", crew) == ["sam"]


def test_several_names_come_back_in_the_order_they_appear():
    assert find_mentions("@Bob and @Alice Fisher, thoughts?", CREW) == ["bob", "alice"]


def test_the_same_person_twice_is_one_mention():
    assert find_mentions("@Bob — sorry @Bob, one more thing", CREW) == ["bob"]


def test_somebody_who_cannot_see_it_is_simply_not_a_candidate():
    """The access check isn't a filter applied afterwards: a person with no
    route into the task never reaches this function, so their name is
    ordinary prose."""
    assert find_mentions("@Carol Danvers should know", CREW) == []


def test_a_bare_at_sign_names_nobody():
    assert find_mentions("meet @ 5pm", CREW) == []


def test_a_name_at_the_very_end_of_the_body_matches():
    """There is no character after the match to test for a word boundary,
    which is exactly where an off-by-one lives."""
    assert find_mentions("over to you @Bob", CREW) == ["bob"]


def test_a_mention_on_its_own_line_matches():
    assert find_mentions("Blocked on the survey.\n@Alice Fisher", CREW) == ["alice"]


def test_needles_skip_an_empty_display_name():
    """Nobody has to have one — the email carries it instead."""
    assert needles(None, "bob@example.com") == ("bob@example.com", "bob")
    assert needles("  ", None) == ()
