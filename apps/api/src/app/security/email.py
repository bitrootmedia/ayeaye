"""Password-reset email, sent by us rather than by SuperTokens.

By default the SuperTokens SDK posts password-reset mail through *their* managed
sending service. It works out of the box, which is the point of it, but it isn't
something to run a product on:

* the mail arrives from a SuperTokens domain, not yours, which is bad for both
  trust and deliverability;
* the reset link — a credential — travels through a third party's
  infrastructure;
* you have no control over the template, the envelope sender, or bounces.

So this module replaces the delivery service with one that hands the message to
`app.core.mailer`, the same aiosmtplib path everything else uses. One mail route
for the whole product, pointed at whatever SMTP provider is configured — or at
nothing at all, which is a supported deployment.

**A failure here must not break password reset.** With no SMTP configured the
mailer logs the message (link included) instead of sending it, so a self-hoster
can still recover an account from `docker compose logs api`. If the SMTP server
is configured but broken we swallow the error rather than returning a 500,
because SuperTokens would otherwise tell the user their reset failed when the
token was in fact issued. See PLAN.md §2.4.
"""

import logging

from supertokens_python.ingredients.emaildelivery.types import EmailDeliveryInterface
from supertokens_python.recipe.emailpassword.types import EmailTemplateVars

from app.core import mailer
from app.core.config import settings

logger = logging.getLogger("app.security.email")


def reset_email_body(link: str) -> str:
    """Plain text, deliberately.

    A password-reset mail is the one message that has to be legible in any
    client and obviously not a phishing attempt. HTML with a styled button is
    neither.
    """
    return (
        "Someone asked to reset the password for this email address.\n\n"
        f"{link}\n\n"
        "The link is single-use and expires shortly.\n\n"
        "If it wasn't you, ignore this — nothing has changed and your password "
        "stays as it is.\n"
    )


def reset_email_subject() -> str:
    return f"Reset your {settings.brand_name} password"


class MailerEmailDelivery(EmailDeliveryInterface[EmailTemplateVars]):
    """Routes SuperTokens' outbound mail through `app.core.mailer`."""

    async def send_email(self, template_vars: EmailTemplateVars, user_context) -> None:
        link = template_vars.password_reset_link
        try:
            await mailer.send(
                to=template_vars.user.email,
                subject=reset_email_subject(),
                text=reset_email_body(link),
            )
        except Exception as exc:
            # The token has already been issued; failing the request now would
            # tell the user to try again when a perfectly good link exists.
            # Log it at a level someone will actually see, link included, so
            # the account is still recoverable.
            logger.error(
                "could not send the password reset for %s: %s — the link was %s",
                template_vars.user.email,
                exc,
                link,
            )
