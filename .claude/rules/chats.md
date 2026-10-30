---
paths:
  - "apps/api/src/app/services/chats.py"
  - "apps/api/src/app/services/online.py"
  - "apps/api/src/app/api/routers/chats.py"
  - "apps/api/alembic/versions/0055_chats.py"
  - "apps/web/src/views/Chats*.tsx"
  - "apps/web/src/components/chat-*.tsx"
  - "scripts/e2e-chats.sh"
  - "e2e/tests/chats.spec.ts"
---

# Chats: DMs, groups, the one list, and who's online

Read the `services/chats.py` docstring; its five rules are the feature.
What follows is why it has the shape it has.

**A chat is a conversation with no anchor, not a second message system.**
`conversations.kind` is `task | project | direct | group`, and one CHECK
ties the anchor to the kind. Messages, attachments, voice notes, mentions,
edits, soft delete, the unread cursor and the socket are all
`services/conversations.py`, unchanged in shape — the same decision that
made comments the conversation system in the first place. Do not add a
`chat_messages` table.

**Membership is a chat's whole access rule, and the org admin is not in
it.** `conversation_members` exists only for direct and group rows; a task
thread with member rows would have two answers to "who can see this" that
could disagree. `conversations.for_conversation()` is the one resolver by
id: task → `tasks_service.context_for`, project → `projects_service`, chat →
membership. Every route that takes a conversation or message id goes through
it (`_own_message`, `_anchor_of`, every `/chats/{id}` route), so an id is
never the access. `can_modify(chat=True)` drops the admin override for the
same reason: an admin who can't see a DM can't have an editor's override in
it. `scripts/e2e-chats.sh` asserts 404 for the org owner on read, messages,
post, edit, delete, list and search — the leak would be silent otherwise.

**DMs are per organisation** (a product decision, 2026-10-30), one per pair
via `direct_key` under a partial unique index, find-or-create with the
`IntegrityError` re-read the task thread already uses. A DM with yourself is
"Saved messages".

**Kept forever unless deleted.** Deleting is the existing soft delete —
body cleared, tombstone kept, a reply's quote then says the original was
removed. There is no "delete the whole chat for both sides".

**A message may be only files.** `MessageIn.body` may be empty exactly when
`attachments.bindable()` — the same four conditions `bind_to_message`
applies — finds something to attach; nothing at all is still "say
something", and an edit still needs words. Clients render the empty body
as nothing and preview it as "File". Task comments still send "Voice note"
as a voice note's body, because the comment thread renders the body
unconditionally.

**"Saved messages" is matched by hand in search** (`_matching`), because
it's a title made up at read time and `ILIKE` on stored columns can't find
it.

**`message_reads` is your row in the chat list**, not just a cursor:
`last_read_at` (now nullable — NULL is "listed, nothing read"), `pinned_at`,
`muted`, `archived_at`. It is display, never access: the list statement
still runs every task/project row through `task_level_expression` /
`project_level_expression`, so losing access drops the thread whatever rows
point at it. A thread enters your list when you read it, post in it, or
`conversations.enlist()` puts you there as a stake-holder (owner,
action-required, named) — never "everything you can see", which for an
admin is the company.

**`conversations.last_message_at` is denormalised** so the list sorts
without scanning messages; `conversations.post` is its only writer.
Archived is checked at read time (`last_message_at > archived_at`), so a new
message un-archives without anybody rewriting your row.

**Mute silences everything but being named**, and leaves the chat's own
badge alone — it only drops out of the total (`/chats/unread`).

**Notifications:** `direct_message` is a new kind (one per unread run, the
existing rule 4), backfilled onto every existing channel in 0055 — a DM is
what people most expect to reach them on Telegram. A mention in a group is
the ordinary `comment_mention`.

**Realtime:** the existing content-free `message` event, now carrying
`organisation_id`; a chat's anchor is `{"kind": "chat"}` and its watch key
`chat:<id>`, verified by membership at watch time. Edits, removals, renames
and member changes publish the same event so lists and open chats refetch.

**Presence is `services/online.py`, Redis, per worker.** Each worker claims
the users it holds sockets for in a sorted set scored by expiry,
heartbeating every 20s with a 60s TTL, and removes its claim when their
last local socket closes. A crashed worker's claims lapse on their own.
`last_seen` is stamped on every heartbeat. Clients poll
`GET /organisations/{id}/presence`; there is no live presence event, and no
typing indicator by product decision. (`services/presence.py` is
out-of-office — the dashboard sense of the word.)
