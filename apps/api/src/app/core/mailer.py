"""Sending mail.

Deliberately thin: the product only ever sends "something happened, go and look"
nudges, never the content itself. That keeps anything sensitive behind the login
rather than in an inbox we don't control. The one exception is the password
reset, which has to carry its link.

**Email is optional, on purpose.** With `SMTP_HOST` unset this logs what it
would have sent and carries on. A self-hoster must be able to run the whole
product without configuring SMTP first, so every flow that mails someone also
has a path that doesn't — invites surface a copyable link in the UI, and a
password reset can be recovered from the log. See PLAN.md §2.4.

In dev, `docker compose up` runs Mailpit and everything lands in its web UI at
http://localhost:8025 — nothing leaves the machine.
"""

import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger("app.mailer")


def is_configured() -> bool:
    return bool(settings.smtp_host)


def from_address() -> str:
    """`MAIL_FROM` if set, otherwise built from the brand name."""
    return settings.mail_from or f"{settings.brand_name} <no-reply@{settings.brand_name}.local>"


async def send(*, to: str, subject: str, text: str) -> None:
    """Send one plain-text message.

    Raises on failure so a taskiq caller retries rather than silently dropping
    mail. Callers that must not fail (a password reset, an invite that already
    has a copyable link) catch it themselves.
    """
    if not to:
        logger.info("skipping mail %r: no recipient", subject)
        return
    if not is_configured():
        # Not an error: a deployment without SMTP is a valid configuration and
        # the app must keep working. Log enough to see what would have gone —
        # for a password reset this log line is the recovery path.
        logger.info("mail not configured, would have sent %r to %s:\n%s", subject, to, text)
        return

    message = EmailMessage()
    message["From"] = from_address()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)

    # 465 is implicit TLS (wrapped from the first byte); 587 and 1025 are plain
    # connections that may then upgrade with STARTTLS. Handing aiosmtplib the
    # wrong one doesn't error clearly — it hangs until the timeout.
    implicit_tls = settings.smtp_port == 465
    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username or None,
        password=settings.smtp_password or None,
        use_tls=implicit_tls,
        # Mailpit and most local catchers speak plain SMTP on 1025; Mailgun and
        # friends want STARTTLS on 587.
        start_tls=False if implicit_tls else settings.smtp_start_tls,
    )
    logger.info("sent %r to %s", subject, to)
