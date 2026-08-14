"""Password-reset delivery — pure, no SMTP or database needed.

The reference project had to rewrite reset links per recipient because it had
three auth surfaces across two hosts. This product has one, so the link
SuperTokens builds is already correct and there is nothing to retarget. What's
left worth pinning is the part that goes wrong silently: the body, and the
promise that a broken mail server never costs someone their account.
"""

import asyncio
import logging

from app.core import mailer
from app.core.config import settings
from app.security.email import MailerEmailDelivery, reset_email_body, reset_email_subject

LINK = "https://tasks.example.com/auth/reset-password?token=abc123&tenantId=public"


def test_the_body_carries_the_link():
    """Without it the mail is an alarming notice with no way to act on it."""
    assert LINK in reset_email_body(LINK)


def test_the_body_is_plain_text():
    """A reset mail has to be legible in any client and obviously not a
    phishing attempt. HTML with a styled button is neither."""
    assert "<" not in reset_email_body(LINK)


def test_the_subject_carries_the_brand():
    """So it's findable in a full inbox, and so a rebrand doesn't leave the old
    name in everyone's mail."""
    assert settings.brand_name in reset_email_subject()


class _Vars:
    """The shape SuperTokens hands to the delivery service."""

    def __init__(self, email: str, link: str):
        self.user = type("U", (), {"email": email})()
        self.password_reset_link = link


def _deliver(email: str = "someone@example.com") -> None:
    asyncio.run(MailerEmailDelivery().send_email(_Vars(email, LINK), None))


def test_unconfigured_smtp_logs_the_link_rather_than_failing(monkeypatch, caplog):
    """SMTP is optional (PLAN.md §2.4). With none configured the link must
    still reach a human somehow, and the log is that somehow — otherwise a
    self-hoster who hasn't set up a mail provider can never recover an
    account."""
    monkeypatch.setattr(settings, "smtp_host", "")
    with caplog.at_level(logging.INFO, logger="app.mailer"):
        _deliver()
    assert LINK in caplog.text


def test_a_broken_mail_server_does_not_fail_the_reset(monkeypatch, caplog):
    """The token is issued before we're called. Raising here would tell the
    user their reset failed while a perfectly good link sat in the void."""

    async def boom(**kwargs):
        raise ConnectionRefusedError("no smtp here")

    monkeypatch.setattr(mailer, "send", boom)
    with caplog.at_level(logging.ERROR, logger="app.security.email"):
        _deliver()
    # Logged loudly, with the link, so the account is still recoverable.
    assert LINK in caplog.text
