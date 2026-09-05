"""Where a notification's email goes — the fallback rule, as pure functions.

The rule is one line of code and several ways to get wrong, all of which end
with somebody's mail going nowhere and nobody finding out. So it lives in
`resolve_email`/`normalise_override` where it can be tested without a
database, the same split `tests/test_access_matrix.py` explains for the
access model: the SQL around it is proved end to end by
`scripts/e2e-notification-channels.sh`, and the decision itself is proved
here.
"""

import pytest
from fastapi import HTTPException

from app.services.notification_channels import normalise_override, resolve_email

ACCOUNT = "person@example.com"
OTHER = "work@example.com"


def test_no_override_uses_the_account_address():
    assert resolve_email(ACCOUNT, None) == ACCOUNT


def test_an_override_wins():
    assert resolve_email(ACCOUNT, OTHER) == OTHER


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
def test_a_blank_override_is_not_an_override(blank):
    """The failure this exists to prevent: a saved-but-empty field that reads
    as "set" and addresses mail to nobody."""
    assert resolve_email(ACCOUNT, blank) == ACCOUNT


def test_surrounding_whitespace_is_not_part_of_an_address():
    assert resolve_email(ACCOUNT, f"  {OTHER}  ") == OTHER


def test_nothing_to_send_to_is_none_not_empty_string():
    """An empty string is an address as far as an SMTP library is concerned.
    The caller has to be able to tell "nowhere" from "somewhere"."""
    assert resolve_email(None, None) is None
    assert resolve_email("", "") is None


def test_an_override_still_works_for_an_account_with_no_address():
    assert resolve_email(None, OTHER) == OTHER


def test_storing_lowercases_and_trims():
    assert normalise_override("  Work@Example.COM ") == "work@example.com"


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_storing_blank_clears_the_override(blank):
    assert normalise_override(blank) is None


@pytest.mark.parametrize("bad", ["notanemail", "@example.com", "person@", "a" * 330 + "@b.com"])
def test_obvious_nonsense_is_refused(bad):
    """Deliberately shallow — this catches a typo, not a determined liar.
    Full RFC validation rejects addresses that genuinely work, and the
    address is checked properly by the only authority that matters: whether
    mail to it arrives."""
    with pytest.raises(HTTPException) as raised:
        normalise_override(bad)
    assert raised.value.status_code == 422
