---
paths:
  - "apps/api/src/app/security/**"
  - "apps/api/src/app/services/mfa.py"
  - "apps/api/src/app/services/verification.py"
  - "apps/api/src/app/services/login_history.py"
  - "apps/api/src/app/models/mfa.py"
  - "apps/api/src/app/models/login_event.py"
  - "apps/web/src/lib/auth-theme.ts"
  - "apps/web/src/components/mfa-*.tsx"
  - "apps/web/src/main.tsx"
  - "apps/web/src/views/Landing.tsx"
  - "apps/web/src/views/NotFound.tsx"
  - "scripts/e2e-mfa.sh"
  - "scripts/e2e-email-verification.sh"
  - "scripts/reset-mfa.sh"
  - "e2e/tests/auth.spec.ts"
  - "e2e/tests/theme.spec.ts"
  - "e2e/tests/landing.spec.ts"
---

# Auth: SuperTokens, MFA, email verification, login history

## The auth screens

SuperTokens' pre-built UI ships its own look, and left alone it is the first
screen anyone sees telling them this is two products bolted together.
`lib/auth-theme.ts` restyles it — and **restates no colours**. Every rule
reaches for the same custom properties as the rest of the app, so the auth
screens follow a token change and dark mode without anyone remembering they
exist. A second palette there is a palette that drifts.

That works because **custom properties inherit through a shadow root**, and
SuperTokens renders inside one. The variables on `:root` are visible to rules
injected into the shadow DOM even though the markup is isolated.

Three things learned doing it, all pinned by `e2e/tests/theme.spec.ts`:

- **`applyStoredTheme()` runs before React mounts** (`main.tsx`). `useTheme`
  only runs inside the signed-in shell, so without it someone who works in
  dark mode signs out and gets a full-brightness page.
- **Their divider paints a background on a box with padding**, so `height: 1px`
  still renders about 7px. A `border-top` draws a hairline regardless of the
  box around it.
- **They layer an opacity on secondary text**, which lands under the contrast
  floor once the background is dark. `opacity: 1` alongside the colour.
- **`primaryText` — the body of every "it worked" screen across every
  recipe** ("a reset email has been sent", "your password has been updated",
  email verification, TOTP — grep `data-supertokens~="primaryText"` across
  the SDK and it is the same class everywhere — ships with no colour rule of
  its own. That is invisible, not merely low-contrast: it defaults to
  near-black text on what is, in dark mode, a near-black card. One rule
  (`color: var(--foreground)`) fixes every recipe at once, which is also why
  it was worth finding rather than patching just the reset-password screen
  that surfaced it.

The selectors are SuperTokens' own `data-supertokens` hooks — the documented
styling surface, but still someone else's markup. A test asserts the hooks
still exist, because an upgrade that renames one reverts the screen to stock
rather than breaking it, and that is exactly the regression nobody notices.
The button label is literally the string "SIGN UP"; that is their copy, not a
`text-transform`, and it is not worth overriding.

## Email verification

Read `settings.email_verification_required` first — the mode is a product
decision more than a config one.

**Required only where SMTP is configured** (`EMAIL_VERIFICATION=auto`, the
default). Enforcing it with no mail server would mean a fresh self-hoster
signs up and is immediately locked out, recoverable only by reading the link
out of `docker compose logs api` — and "two commands to a working install"
is a bar this project actually holds (PLAN.md §8). Password reset degrades
that way because it is an exceptional path; signing up is *the* path.
`required` and `off` force it either way for an operator who knows better.

Unlike MFA and OAuth, **this recipe is free** — no hand-rolling. What it
needed was the same treatment password reset already had: its own delivery
service (`MailerVerificationDelivery`) so mail goes through this product's
SMTP and from its own domain, rather than SuperTokens' managed sender.

**The server sends on sign-up; SuperTokens doesn't.** It sends when a
*client* asks it to, which the prebuilt UI does on its way to the verify
screen — leaving an API sign-up (curl, a script, the e2e suites) with no
email at all, and even a browser being told "we sent you a link" before
anything had been sent. `_override_emailpassword_apis` wraps the sign-up API
and sends it. It never fails the sign-up: the account exists by then, and
refusing the request would leave somebody with an account they were told
they don't have.

**The gate is `App.tsx`'s, not the recipe's.** `EmailVerification.init` runs
at module load, before anything is fetched, so it cannot know whether *this
server* enforces — hardcoding `REQUIRED` would strand a self-hoster on a
screen their server was never going to demand. So the frontend registers the
recipe as `OPTIONAL` (the routes and screen still exist, because the link in
the email has to land somewhere) and `App.tsx` renders `VerifyEmailGate`
when `GET /me` actually comes back refused, matching on the `st-ev` claim id
exactly as it already does for `st-mfa-ok`.

**Confirming needs a session refresh, and the gate does it.** Verification is
recorded against the account, but the browser's access token still carries
the claim's old value — and SuperTokens' fetch interceptor refreshes on a
401, not on a 403 that says a claim failed. Without
`Session.attemptRefreshingSession()` the "I've confirmed it" button re-checks,
gets the same stale answer, and puts you back on the same screen forever.
`scripts/e2e-email-verification.sh` asserts this explicitly, because a test
that skipped it would report a working feature as broken.

**Existing accounts are grandfathered, and not by the migration.**
Verification lives in SuperTokens' own database — a schema this project
doesn't own — so migration 0040 flags every account that exists at that
moment and `services/verification.py` completes it at startup, claiming rows
with the same `UPDATE … RETURNING` shape `reminders.claim` uses so several
uvicorn workers can't do it twice. It is a background task, never awaited: a
SuperTokens core that isn't up yet is not a reason for the API to refuse to
boot, and anything left flagged is picked up next start.

**A checkout runs with it off**, unlike production's `auto`. Every e2e suite
signs up accounts by the dozen and each would otherwise have to fish a link
out of Mailpit before doing the thing it is actually testing. The feature has
its own suite, which turns it on for the duration and puts it back — so the
enforced path is covered without every other suite paying for it. That suite
is the only one that restarts the API.

## Two-factor authentication

Read `services/mfa.py`. Optional per person, forceable per organisation —
and **hand-rolled**, not SuperTokens' own `totp`/`multifactorauth` recipes.
Both were tried first and both registered cleanly, but the first live call
to create a device answered:

```
SuperTokens core threw an error … status code: 402 … MFA feature is not
enabled. Please subscribe to a SuperTokens core license key to enable this
feature.
```

That's a licensing gate in the self-hosted core binary itself, confirmed
against a real core and against SuperTokens' own docs — not a config
mistake, and not something a self-hoster can route around. It conflicts
directly with this product's own bar (`docker compose up -d`, no paid
dependency, no backoffice), so the paid recipes were pulled out entirely
and TOTP was rebuilt on `pyotp` plus a **free** primitive the base `session`
recipe already provides: a custom session claim.

**One rule decides who needs a second factor**, in exactly one place —
`account_requires_mfa`. TOTP is required for an account if *either* they
already have a device (`mfa_totp_devices`, one per person — personal opt-in
is sticky, that's what "enabling 2FA" means) *or* they're an active member
of an organisation with `organisations.require_mfa` set. Union, not
override: turning an organisation's requirement off never revokes someone's
own enrollment, and enrolling personally is never a substitute for a
different organisation's requirement.

**Enforcement is a custom `BooleanClaim`, not the paid recipe's claim** —
`security/authn.py`'s `MfaSatisfiedClaim`. `BooleanClaim` is part of the
free, open-source `session` recipe (it's what "build your own MFA" looks
like in SuperTokens' own docs), and it gives the identical shape a paid
claim would: a value fetched into the access token payload, checked by a
validator on every `verify_session()` call. The validator is added
explicitly on the one shared `VerifiedSession` dependency
(`_add_mfa_validator`, `override_global_claim_validators=`) rather than
arriving for free the way a recipe's own claim would — there's no "default
global validator" registration hook to attach to for a claim that isn't a
recipe's own. That's the real security boundary; the frontend's `MfaGate`
is UX only, same as every other place this codebase draws that line.

**`default_max_age_in_sec=None` is deliberate.** With no max age, the claim
framework only refetches `_fetch_mfa_satisfied` when the access token
payload has no value yet — a brand-new session — never on a timer. The
requirement is decided **once, at first use per session**, and completing
TOTP or a backup code (`mark_mfa_satisfied`, calling `set_claim_value`
directly) sticks for that session's whole life. An organisation turning
`require_mfa` on reaches an already-open session at its *next* sign-in, not
mid-session — `scripts/e2e-mfa.sh`'s "not kicked mid-session" case pins
this on purpose, because it's the one behaviour most likely to read as a bug
report from someone who just flipped the toggle and expected it instant.

**No SuperTokens prebuilt UI is registered for this, on purpose.** Backup
codes aren't a concept the prebuilt TOTP screen knows about, and there's no
supported way to inject a "use a backup code instead" link into it. Both
SDKs expose the low-level primitives instead (`TOTP.createDevice` and
friends, on the paid recipe — unused here — but the same "build your own"
shape applies to a hand-rolled one): `components/mfa-enroll.tsx`'s
`TotpEnroll` (QR from a server-rendered `data:image/png;base64,…` URI, a
secret fallback, a code field, then the backup-codes reveal) is shared
between the Account screen's `TwoFactorCard` (turning 2FA on voluntarily)
and `components/mfa-gate.tsx`'s `MfaGate` (an organisation forcing it and
the account not enrolled yet) — one implementation of "scan a QR, confirm a
code," not two. `MfaGate` itself is rendered by `App.tsx` in place of the
whole shell whenever `GET /me` comes back with SuperTokens' own "invalid
claim" shape naming `st-mfa-ok` (`isMfaClaimError` checks the shape, not
just the status code, so an unrelated 403 doesn't get misread as "needs
2FA") — the identical top-level-gating shape the `ErrorBoundary` already
uses for "don't render a half-built app."

**Every `/me/mfa/*` route uses `MfaPendingSession`, not `CurrentUser`.** Not
just the challenge endpoints (verifying a code, redeeming a backup code —
both are *how* the claim gets satisfied, so the route that does it can't
itself require it) but plain enrollment too: turning 2FA on can itself be
what satisfies a freshly forced organisation's requirement, in the same
session, with no second sign-in. A session that already satisfies the claim
reaches these routes exactly the same way — skipping a check nobody fails
is a no-op for them.

**The secret is stored in the clear**, deliberately — see `models/mfa.py`'s
own comment. A TOTP secret can't be hashed the way a password or backup
code can (verifying a code requires computing one *from* the secret), and
it sits behind the identical trust boundary every other row in this
database already sits behind. Encrypting one column would need its own
key-management story — generation, a new required `.env` var, rotation —
for a bar this product doesn't hold anywhere else yet.

**Recovery, three layers, most to least self-service:**
1. **Backup codes** — ten single-use codes (`secrets.token_hex`, ~40 bits
   each), shown once at enrollment and on regeneration, hashed with
   `services.tokens.hash_token` — reused, not reimplemented, the same
   "plaintext exists once" rule access tokens already follow.
2. **Admin reset** — an org admin clears a member's device and codes from
   the People roster (`reset-mfa`, rank-checked the identical way
   `disable_member`/`remove_member` are, unlike the org-wide toggle which
   only needs admin rank with no target to rank-compare against). The same
   "an org admin can do anything" escape hatch offboarding already grants.
3. **`scripts/reset-mfa.sh <email>`** — an operator running
   `services.mfa.reset_totp` directly from a shell, for the one gap an
   admin can't reach: a lone owner locked out of their own account. Unlike
   `diagnose.sh`'s Storage checks, this needs no SuperTokens call at all —
   TOTP devices and backup codes are hand-rolled in this app's own tables,
   not held by SuperTokens' core — so it's pure database work.

**A bash gotcha that cost real time writing `scripts/e2e-mfa.sh`.** A
multi-key JSON literal built inline — `-d "{\"a\":\"$x\",\"b\":\"$y\"}"` —
and nested inside a `"$(...)"` capture (the `ok "label" "$(code … -d
"{...}")" "status"` shape every `e2e-*.sh` script uses) is silently torn in
two by bash: the comma inside `{...}` reads as a brace-expansion separator
once it's nested two quote-levels deep, turning one `curl` call into two
malformed ones — no error, no warning, just a request whose body is missing
half its fields. It reproduces even though the *exact same shape with one
key* (no comma, nothing to expand) is fine, which is what makes it so easy
to write once and then hit the moment a second field is added. The fix,
applied throughout `e2e-mfa.sh`: build the body into a variable first
(`BODY="{\"a\":\"$x\",\"b\":\"$y\"}"; … -d "$BODY"`) rather than ever
writing a literal `{…}` containing a comma inside a nested capture.

## Login history

Read `models/login_event.py` and `services/login_history.py`. Every
successful sign-in is recorded — IP, user agent, timestamp — with
**deliberately no UI reading it yet**. The data exists so a screen built
later starts with history already in it, rather than starting the clock
the day someone finally asks for one.

**Not foreign-keyed to `users`, on purpose.** The local `users` row is
created lazily on first authenticated request
(`services/users.get_or_create`) — on a brand-new signup, that hasn't
happened yet at the exact moment a session is created. Keying on
`supertokens_user_id` instead (already assigned by then, indexed, joinable
to `users.supertokens_user_id` whenever something reads this) sidesteps the
ordering problem rather than working around it.

**Hooked into `create_new_session`, not the emailpassword sign-in API.** A
session is created exactly once per successful sign-in, regardless of which
recipe did the authenticating — so this covers Google sign-in for free the
day that's added (see the "social login" reconnaissance elsewhere in this
file), instead of needing a second override the day it lands. `security/
authn.py`'s override calls the original implementation first and records
*after* — a failed sign-in never reaches this code at all, so there's
nothing to distinguish success from failure here; SuperTokens already did
that filtering by not calling `create_new_session` for a rejected password.

**Must never fail a sign-in**, the identical contract
`notifications.notify()` already has: a login event is a side effect of
something that already succeeded, so a database hiccup recording it must
not turn a working sign-in into a 500. `record()` catches broadly and logs
a warning rather than raising.

**The IP is read from `X-Forwarded-For`, not the socket peer.** Single
origin means Caddy fronts every request, so the raw connection's client is
always Caddy's own container — `get_request_from_user_context(user_context)`
(a SuperTokens SDK helper, not something built here) is what recovers the
underlying request from inside a `functions` override at all, and
`X-Forwarded-For` off *that* is what recovers the visitor behind it.
