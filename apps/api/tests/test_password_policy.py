"""The password strength rule. No database, no HTTP — `strong_password_validator`
is async only because SuperTokens' `InputFormField.validate` interface requires
it; it does no I/O, so `asyncio.run` is enough without pytest-asyncio.
"""

import asyncio

from app.security.authn import strong_password_validator


def check(value: str) -> str | None:
    return asyncio.run(strong_password_validator(value, "public"))


def test_too_short_is_refused():
    assert check("Ab1defgh") is not None


def test_supertokens_own_default_weak_password_is_now_refused():
    # "aaaaaaa1" passes SuperTokens' own default validator (8 chars, one
    # letter, one digit) — the whole reason this override exists.
    assert check("aaaaaaa1") is not None


def test_no_uppercase_is_refused():
    assert check("lowercase1") is not None


def test_no_lowercase_is_refused():
    assert check("UPPERCASE1") is not None


def test_no_digit_is_refused():
    assert check("NoDigitsHere") is not None


def test_a_strong_password_is_accepted():
    assert check("Correct1Horse") is None


def test_absurdly_long_is_refused():
    assert check("Aa1" + "a" * 100) is not None
