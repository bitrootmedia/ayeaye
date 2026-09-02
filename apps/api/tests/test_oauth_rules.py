"""The pure logic behind services/oauth.py. No database, no HTTP.

PKCE and scope-clamping are worth pinning here because both fail *silently*
in the wrong direction: a PKCE check that's too lenient accepts a stolen
authorization code, and a scope clamp that's too generous hands out write
access a client never registered for.
"""

import base64
import hashlib

from app.models.token import SCOPE_READ, SCOPE_WRITE
from app.services.oauth import _clamp_scope, _pkce_ok


def _challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# --- PKCE --------------------------------------------------------------------


def test_the_correct_verifier_is_accepted():
    verifier = "a-real-verifier-with-enough-entropy"
    assert _pkce_ok(verifier, _challenge_for(verifier)) is True


def test_the_wrong_verifier_is_rejected():
    challenge = _challenge_for("the-real-one")
    assert _pkce_ok("an-impostor", challenge) is False


def test_a_plain_challenge_is_never_accepted():
    # S256 only — OAuth 2.1 drops `plain` entirely, so a verifier equal to
    # its own "challenge" (what `plain` would do) must still fail.
    verifier = "whatever-somebody-sends"
    assert _pkce_ok(verifier, verifier) is False


def test_an_empty_verifier_or_challenge_is_rejected():
    assert _pkce_ok("", _challenge_for("x")) is False
    assert _pkce_ok("x", "") is False


# --- scope clamping ------------------------------------------------------------


def test_a_read_ceiling_always_wins():
    assert _clamp_scope(SCOPE_READ, ceiling=SCOPE_READ) == SCOPE_READ
    assert _clamp_scope(SCOPE_WRITE, ceiling=SCOPE_READ) == SCOPE_READ


def test_a_write_ceiling_allows_the_persons_own_choice():
    assert _clamp_scope(SCOPE_READ, ceiling=SCOPE_WRITE) == SCOPE_READ
    assert _clamp_scope(SCOPE_WRITE, ceiling=SCOPE_WRITE) == SCOPE_WRITE


def test_garbage_scope_defaults_to_read():
    assert _clamp_scope("admin", ceiling=SCOPE_WRITE) == SCOPE_READ
    assert _clamp_scope("", ceiling=SCOPE_WRITE) == SCOPE_READ
