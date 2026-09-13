---
paths:
  - "apps/api/src/app/services/notifications.py"
  - "apps/api/src/app/services/notification_channels.py"
  - "apps/api/src/app/services/telegram.py"
  - "apps/api/src/app/services/telegram_commands.py"
  - "apps/api/src/app/models/notification.py"
  - "apps/api/src/app/api/routers/notifications.py"
  - "apps/api/src/app/api/routers/telegram_webhook.py"
  - "apps/web/src/views/Notifications.tsx"
  - "scripts/e2e-notification-*.sh"
---

# Notifications, channels, Telegram and webhooks

## Notification channels

Read `services/notification_channels.py`. Telegram and a generic webhook,
alongside email — configurable per notification kind, from `/account`.

**Which address, per organisation, with the account's as the fallback.**
`organisation_members.notification_email` is where one person wants *this*
organisation's mail to go. On the membership rather than in a table of its
own, because a membership already **is** "this person, in this
organisation" — the exact scope of the override — so it needs no cleanup
when somebody leaves. NULL means the account address; there is no third
state, and `resolve_email` treats blank, whitespace and absent as the same
intention, because a saved-but-empty field is how mail starts going
nowhere.

Reaching it at send time needed `notifications.organisation_id`, which is
new — every notification this product raises is organisation-scoped and
every call site had the id in hand (it had just built a `/orgs/{id}/…`
link with it), so this records something the sender already knew and used
to throw away. **A real column rather than parsing the id back out of
`link_path`**: a value recovered from a display string is a second answer
that can disagree with the first, and this one decides where mail goes.
The address is resolved in the worker, not stamped on the notification when
it was raised — an override changed this morning should apply to a nudge
queued last night, and the queue is exactly where a stale copy would sit.

**Set from the Account screen, never by an admin.**
`request_email_for_organisation` takes the caller's own `User` and looks up
their own active membership; there is no branch that lets somebody redirect
a colleague's mail, which would be a rather effective way to read it.

**And it is confirmed before it is used.** `notification_email` only ever
holds an address somebody has proved they can read: a newly typed one waits
in `notification_email_pending` with a hashed, single-use, 48-hour token,
and mail keeps going to the account address until the link is opened. That
ordering is the feature — a typo costs nothing, and pointing this at a
colleague's inbox achieves nothing, because only they can open the link and
they have no reason to. The confirm route is **unauthenticated**, the same
"the token is the authority" trade `services/invites.py` documents, and for
a sharper reason: the link is sent *to the address being confirmed*, which
is usually read in a different browser from the one that asked.

Three states, three fields on the wire (`email`, `pending`, `effective`) —
collapsing any two of them tells somebody something untrue, and the one
that matters is that a pending address must never render as though it were
in use. Two bugs found by testing exactly that: the Account card seeded its
draft state from the server, so a fetch landing after you typed replaced
what you wrote and the save then silently did nothing; and the "has this
changed?" guard compared only against the *confirmed* value, which made
clearing a pending request impossible — the one thing somebody who has just
mistyped an address wants to do.

**Email becomes a row in `notification_channels`, not a special case beside
it.** Every user gets one, auto-provisioned lazily the first time anything
needs to notify them (`get_or_create_email_channel`, the identical lazy
`get_or_create` shape `services/users.py` already uses for the local user
row) — not at signup, so existing accounts pick it up the moment they're
next notified rather than needing a backfill. `notify()` changed from
"always email" to "deliver to every channel with this `kind` enabled",
which is what makes adding Telegram and webhook *routing*, not two new
special cases bolted beside the old unconditional email send. A fresh
channel starts with every `NOTIFICATION_KINDS` value enabled — matching
today's "email always sends" default, so nobody who never opens the
settings screen notices anything changed.

**The webhook secret is stored in plaintext, deliberately — the one place
in this codebase a credential isn't hashed at rest, and that's a
considered exception, not an oversight.** A personal access token
(`services/tokens.py`) is a bearer credential the server only ever
*verifies*: hash it, and the server never needs the plaintext again. A
webhook signing secret is the opposite — a symmetric key the server has to
*use*, computing a fresh HMAC on every delivery, for the life of the
channel. There is no way to do that from a one-way hash. What makes this
an acceptable trade: the secret only ever signs nudges that carry no task
detail by design (the same "carries no detail" rule `services/
notifications.py`'s own docstring has always stated), it's scoped to one
channel and revocable independently of every other credential on the
account, and it is never sent back to the browser after creation — only a
preview (its own URL), the same "which one do I revoke" purpose
`PersonalAccessToken.prefix` already serves. Every delivery carries
`X-Ayeaye-Signature: sha256=...`, the same header shape GitHub and Stripe
already taught people to expect.

**Neither Telegram nor webhook gets the email job's per-notification
idempotency flag, and that's a scope trade, not an omission.**
`Notification.emailed` works because there's exactly one email channel per
person — one flag on the notification row is enough to say "this went."
Telegram and webhook are N channels per person, and a flag per
(notification, channel) pair was traded away: a webhook receiver is
expected to dedupe on the notification id in its own payload, the
identical at-least-once contract GitHub and Stripe already teach people to
expect, and a duplicate Telegram message on a worker retry is a minor
cosmetic cost, not a correctness one.

**Telegram linking is a two-step handshake through a pending channel row,
not a second table.** `POST /me/notification-channels/telegram/link-start`
deletes any existing Telegram channel for that person (linked or still
pending — a person has one Telegram account, and starting a fresh link is
how they'd re-point it at a different chat) and inserts a new one with
`verified_at IS NULL` and a one-time code in `config.link_code`. Tapping
`/start {code}` in the bot hits the new top-level `POST /api/telegram/
webhook` route — not organisation-scoped, not user-authenticated, because
Telegram has no session cookie and no idea what either concept is — which
resolves the code, sets `config.chat_id` and stamps `verified_at`. The
code expires after `LINK_CODE_TTL` (15 minutes); an expired or unknown
code is not an error, just nothing to do, and the route always 200s
regardless — Telegram retries a webhook call that doesn't, and there is
nothing here worth retrying.

**Two partial unique indexes, not a plain one, because webhook is the odd
one out.** `uq_notification_channels_user_email` and `_user_telegram` are
both `UNIQUE (user_id) WHERE kind = '...'` — at most one of each, the same
"a person has one inbox and one Telegram account" reasoning the linking
flow already relies on. Webhook carries no such index: several are
expected, one relay per destination. `get_or_create_email_channel`'s race
recovery — catch the `IntegrityError` from two concurrent `notify()` calls
provisioning email at once, then re-read what the winner inserted — is the
identical shape `tasks_service.grant()` already uses for its own
unique-grant race.

**`httpx` is now a direct dependency**, not just transitive via
supertokens-python — `services/telegram.py`'s Bot API calls and the
webhook delivery job both need a real HTTP client. `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_BOT_USERNAME` are both optional and empty by default, the
identical "optional infrastructure" contract `SMTP_HOST` already holds —
every function in `services/telegram.py` becomes a silent no-op with an
empty token, and `link-start` refuses with 422 rather than minting a code
for a bot that can't be reached, so the browser gets an honest reason
rather than a link nobody can ever open. Registering the webhook itself
(`setWebhook`, pointed at `{SITE_URL}/api/telegram/webhook`) is a one-time
operator step — see the README — because it needs `SITE_URL` to already
be a real HTTPS address Telegram's own servers can reach.

**`scripts/e2e-notification-channels.sh` proves the webhook path against a
real local HTTP listener** standing in for a receiver, the same "throwaway
local server standing in for a provider" precedent `diagnose.sh`'s own
CORS check already uses — and verifies the HMAC byte for byte, not just
"did a request arrive." Telegram's own Bot API isn't reachable from a dev
stack without a real bot token, so its linking logic is proved by calling
`services/notification_channels.py` directly rather than through the
router's `settings.telegram_bot_username` gate, alongside the HTTP-facing
parts that need no bot at all: the webhook route surviving a malformed
update, an irrelevant message, and a stale code without ever 500ing.

### Creating tasks from Telegram

Read `services/telegram_commands.py`. Four commands: `/start {code}` (the
linking handshake, unchanged), `/task <title>`, `/org <name>` and `/help`.
**A plain message creates nothing** — that was a deliberate call, not an
oversight: the ask was a `/task` command, not "every message is a task,"
because the second one is one accidental tap or stray reply away from a
task nobody meant to file.

**`/task`'s first line is the title, the rest is the description.**
`rest.partition("\n")`, title truncated to 300 (the column's own limit —
`tasks_service.create()` is called directly here, bypassing the `TaskCreate`
schema that would otherwise enforce it, so this module has to). Owner
defaults to the sender, exactly `tasks_service.create()`'s own "you own it
unless you say otherwise" rule — the identical shape `app/mcp/server.py`'s
own `create_task` tool already calls it with.

**Which organisation `/task` files into lives in `NotificationChannel.
config`, not a new table.** One more key, `default_organisation_id`,
alongside the `chat_id` a linked Telegram channel already carries — the
same "differs per kind, never queried on" reasoning the model's own
docstring already gives for `config`. `/org` is the *only* writer of it;
the Account screen shows it read-only ("/task creates tasks in {org
name}"), a deliberate design fork — organisation switching was asked to
happen inside Telegram, not from a second web picker duplicating the same
write.

**Membership is re-checked at `/task` time, not trusted from whenever
`/org` last ran.** Someone can be removed from their default organisation
between the two; `organisations_service.context_for` (the identical
"no access reads as 404" call every other organisation-scoped route
already makes) runs fresh on every `/task`, and its failure is a reply
asking to `/org` again, never a task silently filed into an organisation
the sender no longer belongs to.

**The single-organisation case never needs `/org` at all.** If `/task`
runs with no default set and the sender belongs to exactly one active
organisation, that one is used *and persisted* as the default — the
friction `/org` exists for only matters once there's an actual choice.
Zero organisations, or more than one with nothing chosen yet, both reply
pointing at `/org` with the real list of names.

**`/org`'s name matching is a pure function**, `match_organisation` — no
database, a real unit test (`tests/test_telegram_commands.py`), the same
"pure function over plain data" shape `services/tasks.py`'s own
notification rules already use. Exact (case-insensitive) match wins
outright even when it's also a substring of another choice — typing
"Acme" for an organisation literally named "Acme" must not get tangled up
with a second one named "Acme Corp." Only when there's no exact match does
a *unique* substring match get used; anything else (zero or several
candidates) is reported by name, never guessed at.

**A verified Telegram chat id is unique across every account, not just
within one — found live, not designed in from the start.** Re-linking the
same Telegram account to a *second* ayeaye account left two verified
`NotificationChannel` rows both claiming the same `chat_id`, and
`telegram_commands._channel_and_user`'s lookup by chat id had no way to
know which one governed — whichever the database happened to return
first, silently. `start_telegram_link` already deletes the *caller's own*
previous Telegram channel on re-link; `complete_telegram_link` now also
deletes any *other* account's channel already holding that exact chat id,
the identical "re-linking transfers the claim" rule, just extended across
accounts instead of within one — a real Telegram chat belongs to one
Telegram account, which can only sensibly be linked to one ayeaye account
at a time.

**No `update_id` de-duplication, on purpose.** Telegram retries a webhook
call that doesn't 200; this one (almost) always does, even on an internal
error (`handle_update`'s own errors are caught by the router, which still
replies `{"ok": true}`), so a retry double-filing a task is already rare.
Tracking processed update ids would be real infrastructure — a table, or
a Redis key — for a genuinely rare edge case on what is, at bottom, a
personal capture tool. The identical trade-off this same section already
makes for Telegram and webhook not getting the email job's
per-notification idempotency flag.

`scripts/e2e-notification-channels.sh` proves the whole loop against the
real HTTP route once a channel is linked at the service layer: `/task`
refusing with no default across two organisations, `/org` picking one,
`/task` filing into it, switching with a second `/org`, an unknown `/org`
query leaving the default untouched, and a 400-character title landing at
exactly 300.

## The notification inbox

- **The notification inbox's body span had no `whitespace-pre-wrap`, and it
  took the daily digest to notice.** Every notification before it was
  effectively one line, so the missing wrap was invisible; a digest body with
  real line breaks (`Planned for today:\n- …\n\nDone yesterday:\n- …`)
  rendered as one run-on sentence. Same fix as a comment or an announcement
  body — `views/Notifications.tsx`'s body `<span>` needed the class everyone
  else already has.
- **Each inbox row got its own Mark-as-read and Delete buttons, not just
  the page-level "Mark all read."** `DELETE /notifications/{id}` and
  `POST /notifications/{id}/read` (already existed) sit beside each other
  in `services/notifications.py` with the identical "not found is fine"
  shape — a foreign or already-gone id 204s rather than 404ing, since
  DELETE is supposed to be idempotent and there's nothing here worth a
  second person ever seeing (no org scoping, no access check beyond
  `user_id == caller`). The row itself couldn't stay a `<button>` once it
  needed to contain two more buttons — nested interactive elements are
  invalid HTML — so it's `role="button"` on a `<div>` with `tabIndex`/
  `onKeyDown`, the identical shape the notepad's own card already
  documents here, and for the identical reason: a Playwright role query for
  the inner button matches the outer row too, since its computed
  accessible name concatenates the row's own text with the nested button's
  `aria-label`. Scoped to the real `<button>` tag instead of a role query
  when this needed testing.
