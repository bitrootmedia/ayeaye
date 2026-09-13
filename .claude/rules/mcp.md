---
paths:
  - "apps/api/src/app/mcp/**"
  - "apps/api/src/app/services/oauth.py"
  - "apps/api/src/app/services/tokens.py"
  - "apps/api/src/app/services/idempotency.py"
  - "apps/api/src/app/api/routers/oauth.py"
  - "apps/api/src/app/api/routers/wellknown.py"
  - "apps/api/src/app/models/oauth.py"
  - "apps/api/src/app/models/token.py"
  - "apps/api/src/app/models/idempotency.py"
  - "apps/web/src/views/OAuthAuthorize.tsx"
  - "scripts/e2e-mcp.sh"
  - "scripts/e2e-agent-queue.sh"
  - "scripts/e2e-oauth.sh"
  - "e2e/tests/mcp.spec.ts"
  - "e2e/tests/attribution.spec.ts"
---

# MCP and OAuth 2.1

## MCP — somebody's own assistant

Read `app/mcp/server.py`. **Every tool resolves through `services/access.py`,
as the token's owner** — there is deliberately not a single `select()` in that
module. A query written there would be a second access path, and the moment
there are two, one of them is wrong and nobody knows which. `scripts/e2e-mcp.sh`
proves the refusals: a stranger's token, an org admin against a hidden task,
and a read-only token against every write.

**Two credential shapes, not the session cookie either way.** A personal
access token from the account screen (`Authorization: Bearer ayc_…`) — shown
once, SHA-256 at rest, scoped `read`/`write`, revocable from the screen that
made it — or an OAuth access token from the flow at `/oauth/authorize`, see
the "OAuth" section below. An MCP client is not a browser, so neither path
uses the cookie. `require_write` is the single place a read-only credential
is turned away, and it doesn't care which shape produced it — see
`_Principal` in `app/mcp/server.py`.

**`attach_file` is the one place a file's bytes pass through the API**, and
that is a deliberate, narrow exception to Attachments' "browser → storage
directly" rule below — an MCP client has no browser and no direct route to
the bucket, so the three-step handshake collapses into one call: create the
`pending` row, write the bytes with `s3.put_object_bytes` (the same primitive
the thumbnail worker uses — same class of caller, not a browser subject to
its own bandwidth), then run the *same* `confirm()` the browser path runs, so
the real size and the real content-type still win over whatever was declared.
Base64 costs roughly a third more than the file's own size, both on the wire
and in the calling assistant's context, which is the reason this isn't
positioned as a bulk-transfer channel — it exists for what someone would
plausibly paste into a chat, not for shipping a phone video through an LLM's
context window.

**Knowledge-base tools reuse `services/books.py`/`services/articles.py`
exactly like every other tool reuses its service** — `list_books`,
`list_articles`, `read_article`, `create_book`, `create_article`,
`edit_article`, `publish_article`, `unpublish_article`,
`attach_article_file`. `edit_article` is the one with a real wrinkle:
`autosave_revision` has no partial-update shape (unlike, say, `update_task`),
so passing only `body` still has to resend the *current* `title` — the tool
calls `start_editing_session` first specifically to have that value on hand,
the identical reason the frontend's own autosave keeps a `titleRef` rather
than trusting a stale closure (see "The knowledge base" section). No
`share_book` tool: sharing has no MCP tool for tasks or projects either, so
there was nothing to match parity with. `attach_article_file` is `attach_file`
with one extra step — `start_editing_session` first, to land on the article's
current revision, since attachments anchor to a revision, not the article.

**`update_task` only exposed a quarter of what `create_task` did, for no
reason beyond having been written first — found auditing MCP against the
REST API for parity, not by anyone hitting the gap while using it.**
`create_task` took title, description, project, owner, action-required,
priority and due date; `update_task` exposed only `status`/`priority`/
`due_on`/`action_required_email` — meaning a task fully specified at
creation had no MCP path to rename, move, re-describe or reassign
afterward, despite the REST `TaskUpdate` schema supporting all of it. Now
carries `title`, `description` (markdown, matching `create_task`),
`project_id` and `owner_email` too. Two of those needed a clearing
convention `create_task` never had to think about, because create has
nothing yet to clear: `project_id=""` makes the task loose again
(`tasks_service.update` already treats an explicit `None` as "make it
loose," so the tool only has to turn `""` into that `None`) — but
`owner_email` is never sent as an explicit `None`, because a task always
has an owner and `tasks_service.update` raises if asked to clear one, so
`if owner_email:` (not `is not None`) is what keeps an omitted field from
being confused with a clearing attempt that isn't a real operation here.

**Closing was missing entirely, and it's one of the most ordinary things
someone would ask an assistant to do.** `close_task`/`reopen_task` both
call `tasks_service.set_open()` — the identical owner-or-admin rule,
identical 403-not-404 for anyone else, `set_open`'s own — and are separate
tools rather than a `closed: bool` parameter on `update_task`, matching
this file's own `tag_task`/`untag_task` precedent for a boolean-shaped
action written as two verbs instead of one flag.

**`mine_only` on `list_tasks` and `activity` said "tasks you own **or have
been asked to act on**" and passed only `owner_user_id`** — so being asked
to act on something was not enough for it to appear in "what needs doing",
which is most of the point of being asked. Fixed with a third person filter
on `access.visible_tasks_stmt`: `mine_user_id`, which **ORs** owner against
action-required where the existing `owner_user_id`/`action_required_user_id`
each narrow to one route and AND together. Both shapes are wanted — the task
list's two separate Owner and Action-required filters are the AND ones, and
this is the same OR `my_priority_tasks_stmt` already writes out for the
dashboard's escalation cards. There is deliberately no equivalent in the web
task list: "mine, either way" is a dashboard question, and the list offers
the two filters separately instead.

**Reminders and time tracking were read-only or entirely absent.**
`create_reminder` covers both of `services/reminders.py`'s two create
paths — task-anchored (`task_id` given) or standalone (`title` given
instead) — behind one tool rather than two, since the only difference is
which one argument was supplied; `update_reminder` mirrors the REST
`PATCH`'s field-presence shape (`done` maps to the same `done_at` stamp).
`start_timer`/`stop_timer`/`log_time` call `time_tracking.start`/`stop`/
`log_manual` directly with no extra access check in the tool itself —
those service functions already resolve the task through
`_readable_task()` internally, the identical reason `set_open` needed no
separate `context_for` call either.

**`list_projects`, `list_members`, and `planner_bucket` on `create_task`
exist for a client that draws a form rather than reads prose.** Every write
tool here names a project by id and a person by email — right for an
assistant, which is quoting back an id it was just given or an address
somebody said out loud, and useless to the menu bar app in the
`ayeaye-menubar` repo, which has to *offer* the choice and had nowhere to
get either list. Both are ordinary tools over the ordinary services
(`projects_service.list_visible`, `organisations_service.list_members`), so
the access rules come free: a project stays private to its owner until
shared, and an organisation admin sees every one, exactly as everywhere
else.

`list_members` returns only people who have **actually joined**. An
outstanding invitation is somebody `_member_by_email` will refuse with "not
a member", so listing them would offer a choice every write tool then
turns down.

`planner_bucket` is **the caller's board, never the owner's**, even when
creating a task for somebody else. A planner is one person's plan for their
own week (see `models/planner.py`) — putting work on a colleague's board
because you filed a ticket for them is not a thing to do quietly, and the
REST API has no route that does it either without `?user_id=` and an admin
check. It places with `position=None`, appending: the same trade the task
screen's own bucket picker makes, since fetching a whole board to compute a
midpoint for a task nobody has looked at yet would be a strange one.

**`notifications` is the inbox, and it is the one read tool that takes no
organisation.** Added for the menu bar app's badge, which needs a number
before it needs a list. It leads with the unread count on its own line
(`3 unread:`) so a caller that only wants the number doesn't have to count
rows, and states the count even when nothing is listed — "how many" and
"which ones" are different questions and some callers only ask the first.
Deliberately not organisation-scoped, unlike almost everything else here: a
notification is addressed to a person, not filed in a place — some carry an
organisation and some don't — and `notifications_service.unread_count` is
what the web app's own bell polls. A count that disagreed with the bell
would be a second, quieter answer to the same question. `my_reminders` is
the existing precedent for a tool with no organisation id.

**`running_timer` is the third tool that takes no organisation, and the
reason is a database constraint rather than a preference.** There is one
running timer per person across the whole installation — a partial unique
index on `(user_id) WHERE ended_at IS NULL`, see `services/time_tracking.py`
— so "which organisation" is something this tool *answers* rather than asks,
and it answers it in the line (`organisation_id=…`) because a timer started
yesterday in one organisation has to be findable today from another. It
existed already as `GET /me/timer`, which the web shell polls for exactly
that reason; MCP had `start_timer` and `stop_timer` and no way to ask what
was running, which is fine for an assistant told to start one and useless to
the menu bar app in the `ayeaye-menubar` repo, which draws a state light on
its icon and cannot draw state it can't read. `read` is enough: knowing what
your own clock is on is not a write, the same argument `notifications` makes
for a status light being pointable at a read-only credential.

The join it needs — the entry plus the task, for a title and an organisation
— is `time_tracking.running_with_task`, added for this and adopted by
`GET /me/timer`, which was doing the same two reads inline. That is not
tidying: `app/mcp/server.py` has no `select()` of its own on purpose, so the
second read had to live in the service or the tool would have been the
module's first exception to its own rule. It loads the task **without an
access check**, deliberately — the entry is the caller's own, so they could
read the task when they started it, and a timer whose task has since gone out
of view (hidden, or a project unshared) still has to say what it is on and
still has to be stoppable. A clock running that nothing in the interface will
name is the worse failure.

**`changelog` and `record_change` are the organisation's dated log.** The
read tool takes an optional `query` (the same matcher ⌘K uses) and states
what its page is a page *of* when there is more — the text equivalent of
`X-Total-Count`, and the same "a caller that believes it has everything and
doesn't" failure the REST list avoids. `record_change`'s docstring leans on
`happened_on` hard on purpose: an assistant told on Thursday that something
happened on Tuesday will otherwise file it under Thursday, which is the one
mistake that column exists to prevent. Both pre-validate emptiness and length
into `Denied` rather than letting `clean_description`'s 422 become a crash
with its text withheld, exactly as `create_spark` documents. **No edit or
delete tool**, deliberately — correcting a log is a person's judgement about
their own record, and nothing asked for it.

**`create_spark` takes no organisation at all**, and unlike `stop_timer` or
`update_reminder` — which merely don't need one to find what they act on —
it is because the record itself has none, ever. See the Sparks section.
Added for the menu bar app, whose whole box is one field and a Return, and
which had a way to file a task and no way to file the thought that isn't
one yet. One argument, `body`. It refuses an empty one as a
`Denied` rather than letting `services/sparks.py`'s own 422 through, since
an `HTTPException` reaches an MCP client as a crash with its text withheld
— the `class Denied(ToolError)` distinction the gotcha list below records.
**There is deliberately no read tool to go with it**: a spark list is a
person's unsorted notebook, `search` doesn't reach it (the ⌘K palette doesn't
either — see Sparks), and nothing asked for one. `scripts/e2e-mcp.sh`
proves the isolation through the REST list instead, which is the only
reader there is.

**`task_versions` is read-only, and restoring is deliberately not a tool.**
It reports the earlier versions of a task's title and description (see the
Task versions section above), stripped to prose with `richtext.to_plain_text`
the same way `task` reads `description_text` rather than stored HTML — there
is no generated column on a revision, so the converter does that job on
demand. What it won't do is put one back: a restore silently replaces text
somebody may be working on, and a person asking "what did this say before"
is better served by the words in front of them than by an assistant picking
a version on their behalf. If they genuinely want it back, the text is right
there to pass to `update_task`.

**`task` reads the comment thread back, and that is the whole point of it.**
Reported from a real day of agent-assisted work: an assistant resuming a
task got its title, status and a list of event *kinds* — and a task read
that way looks like a task nobody has started, so the honest next move is to
begin again rather than continue. The state was never in the columns. It was
in the thread: the decisions taken, the corrections, what is waiting on a
person. `task` now also reports dependencies (both directions), checklists
with each item's own tick and id, and files, so one call answers "where did
this get to" instead of four. Four things about the shape:

- **The thread is capped at `MAX_THREAD` (40, newest kept) and says so when
  it truncates** — "the last 40 of 112". A silent cap on a recovery surface
  is the failure `/tasks`'s own no-default-limit rule exists to avoid, just
  spent on a model's context rather than a person's screen.
- **Reading must not create a thread.** `conversations.for_task` is called
  with `create=False` (its default), so `thread.conversation` is None until
  somebody actually comments, and both `list_messages` and
  `attachments.for_task` already take that. A read that writes a row is a
  read that makes `GET`-shaped tools unsafe to retry.
- **A removed comment is left out, not shown as a tombstone** — `remove()`
  has already cleared the body, so there is nothing of the person's own
  words left to read back. The same call `conversations.for_tasks` makes for
  the data export.
- **`_edge_line` renders an invisible dependency as "a task you can't
  see".** Task access has six routes in, so the far end of an edge can be
  perfectly invisible to somebody who can see this end — `list_dependencies`
  already returns `task=None` for that case, and naming it here would leak
  exactly what `effective_task_level` refuses to.

**Dependencies and checklists were built and then not exposed, which is a
failure mode worth naming.** `services/dependencies.py` and
`services/checklists.py` both had full REST surfaces, e2e suites and access
rules, and no MCP tool — so an assistant expressing "this is waiting on
that" typed a UUID into English prose on the parent, and filed production
steps as a markdown list inside a description where nothing could tick an
item or be asked what was outstanding. `add_dependency`/`remove_dependency`
and `add_checklist`/`add_checklist_item`/`check_item` are ordinary tools over
those services, with no rule restated. Three decisions in them:

- **Both dependency tools name the two tasks, never the link's own id.**
  `remove_dependency` resolves the edge through `list_dependencies` rather
  than asking for a `dependency_id` — the two task ids are what the caller
  already has, and a third kind of id to carry around is friction for
  nothing. Still no `select()` in this module.
- **`add_checklist` takes its items with it.** Filing seven steps should be
  one call, not eight; a blank line in a pasted list is skipped rather than
  422ing and losing every item after it.
- **`check_item` finds the item across every checklist on the task**, so the
  id `task` printed beside it is the only one needed. `for_task` eager-loads
  items, so the walk touches no lazy relationship — see
  `checklists.get_checklist_or_404`'s own docstring for what happens when
  one does.

**The `Denied` lesson had a second half, and this is it.** `_refusal` turns
a service's `HTTPException` into a `Denied`, because an `HTTPException`
escaping a tool is an *unhandled* exception as far as the SDK is concerned
and its text is withheld on exactly the same grounds. `tag_task`,
`untag_task` and `attach_file` were calling `tctx.require` bare, so
"you have read-only access to this task" — the one sentence saying what to
do — was being discarded for anybody with a write-scope credential and
read-only access to the task. Fixed alongside the new tools, since shipping
better-behaved neighbours would have been the odd outcome.

**A correction to the note above, found asserting it:** the string
`Error executing tool <name>: ` prefixes *every* refusal, a well-behaved
`ToolError` included — the SDK always writes it. What distinguishes a
refusal that reached the client is whether the sentence *after* the colon
survived, so a test for this asserts the whole string and never the absence
of the prefix. (Which is also why the menu bar client's workaround keyed on
that prefix: it was there either way.)


**A write records what acted on the person's behalf — `messages.via`.**
Reported as a workaround somebody had already invented: *"next time you
comment prefix any comment with [Claude] so i know where it came from"*. A
convention holds only as long as one model remembers it, and it was papering
over a missing field. The name of the personal access token, or the OAuth
client's own `client_name`, now rides out of `OAuthTokenVerifier` as RFC
8693's **`act` claim** — the SDK's `AccessToken.claims` is the field for
exactly this, so nothing had to be subclassed or smuggled through
`client_id` — and `_Principal.via` carries it to the one tool that writes
prose.

- **Attribution, not authorship, and the distinction is load-bearing.**
  `user_id` is still whose comment it is: a token *is* a person, which is
  this whole surface's one rule. `via` only says how the words arrived. So
  it is a second field beside the author, never a replacement for one, and
  the thread renders "Alice · via Claude".
- **Only comments carry it.** A status change is an action, already
  attributed to the person and already authorised by them; a comment is the
  one place an assistant produces prose that a colleague will read as
  somebody's own words. Threading a principal down through every service
  that writes a `task_events` row would be a large change for a much
  smaller problem — if that's ever wanted, the shape is the same column on
  `task_events` and a `via=` kwarg on `tasks_service.record`.
- **NULL is "a person typed it", so there was nothing to backfill.** The
  web app sends no `via` at all, which is what every row written before
  this holds anyway.
- **`task` reads it back**, so an assistant can tell its own earlier notes
  from what a colleague actually wrote — the thing it could not do when
  every comment looked like the token owner's.
- **`e2e/tests/attribution.spec.ts` is the browser half, and it goes the
  whole way round on purpose** — mint a real token through the account
  screen, post over the real `/mcp` transport, then read the thread as a
  person. A test that inserted the row directly would still pass with the
  verifier's `act` claim removed, which is most of what could break. It
  asserts the author's address *and* the badge (attribution is two facts,
  not one) and posts a second comment from the browser as the control case,
  without which "via Claude" appearing on everything would read as a pass.
  The HTTP suite can prove the column and the API field; only this one can
  prove a colleague actually sees which lines came through an assistant,
  which is the whole feature.

**Idempotency keys, so a retried write repeats the answer and not the
work.** `create_task` and `comment` take an optional `idempotency_key`; read
`services/idempotency.py` for the three rules. The one worth knowing before
touching it: **a claim with no `entity_id` has two meanings, and only its
age tells them apart.** In flight, or a process that died holding it — so a
young one is reported as in progress (the caller waits and retries with the
same key, which is what a retry already was) and an old one is taken over.
Refusing forever would punish a caller for our crash; honouring immediately
would let the genuine concurrent retry through, which is the duplicate this
exists to prevent.

- **A table, not a column per thing that can be created.** A key is a fact
  about a request, not about the row the request made — a column would mean
  a new nullable field and a new partial unique index for every future
  write that wants one. Scoped to (person, key): two people using the same
  obvious string must not collide.
- **Claim commits before the work starts.** Recording the key afterwards
  would mean two concurrent retries both do the work and only *then*
  discover one was a duplicate, by which point the constraint can report
  the fact and not prevent it.
- **A failed call hands its key straight back.** Without `release()`,
  somebody who sent a bad priority, read the refusal and fixed it would be
  told their own failed call was still running — for five minutes, over a
  request that had already finished. Scoped to `entity_id IS NULL` so it
  can never delete a finished claim however it gets called.
- **No key means no dedupe, and that is not an oversight.** Filing two
  identical tasks on purpose has to stay possible, so the behaviour is
  untouched unless a key is supplied. `scripts/e2e-mcp.sh` asserts both
  directions.
- **The same key on a different tool is refused**, rather than answered
  with the first operation's id — a confidently wrong answer is worse than
  an error.
- **Three states, and two of them need the clock moved to test at all.**
  The suite stages a bare claim and backdates it, the same "reach into the
  stack rather than wait" move `e2e-reminders.sh` makes for its own sweep.

**The planner tools are the agent queue, and the story lives in
`planner-calendar.md`, not here.** `next_task`, `my_planner`, `plan_task` and
`unplan_task` are what turn this surface into a feed an assistant works down
rather than a thing somebody prompts at — but the design is a *planner*
design (no queue table; a `planner_entries` row is what queued means; bucket
and position are the order), so it is documented with the planner. Three
facts that belong to this module: `_task_detail` is shared by `task` and
`next_task` rather than duplicated, `plan_task` has no `user_id` argument on
purpose (your own board only, like `planner_bucket` on `create_task`), and
`next_task`'s description carries the finishing order — comment, unplan, hand
back last — because handing work back can take away the only route you had
into the task, and the tool that frames the loop is the only place that
warning would be read in time.

**`create_task` and `comment` convert `HTTPException` too, and the second
one had been lying.** `comment` flattened *every* failure into "No such
task, or you can't comment on it" — so a 10,001-character comment was told
its task did not exist. Both now go through `_refusal` for HTTP errors and
keep a generic `Denied` only for the genuinely unrecognisable (a malformed
UUID), so "that comment is too long" and "priority must be one of …" reach
the caller who can act on them.


**Every tool is registered with `@tool()`, never a bare `@mcp.tool()`, and a
test fails the build if one appears.** `_refusing` converts an escaping
`HTTPException` into a `Denied`; doing that per tool worked and was
forgettable, which is not a character flaw but a design one — the five tools
that had it were the five somebody had happened to touch, and the other
thirty-six silently discarded the sentence that says what to do. `close_task`
was the worst of them: `set_open` answers **403 rather than 404** precisely so
a non-owner is told they can see the task but may not close it, and that whole
distinction arrived as `Error executing tool close_task`.

- **It only ever sees what a tool did not handle.** A reader's deliberate
  "No such task, or you can't see it" — which must not confirm that a task
  exists — still wins, because its own `except` runs inside this one. So no
  existing handler needed changing, and eight hand-written `except
  HTTPException` blocks could come *out*. The two that remain
  (`create_task`, `comment`) are the two that also hand an idempotency key
  back.
- **Deliberately not the SDK's middleware chain**, which would need no
  per-tool decoration at all: it is documented as expected to change before
  v2 is final, and the tool layer converts an exception before middleware
  would see it. `tests/test_mcp_tools.py` is the cheaper, version-proof
  version of the same guarantee.

**`tests/test_mcp_tools.py` also pins the module's one rule, and immediately
caught it being broken.** The docstring has always said "there is
deliberately not a single `select()` in it"; there was one —
`_member_by_email` had grown its own join against `organisation_members`, a
second answer to "is this address an active member". It now lives in
`organisations.active_member_id_by_email`. The test is an **AST walk, not a
grep**, because both obvious false positives are real: the module's own
docstring argues about `select()` at length, and `_caller` does a
`db.get(User, …)` — a primary-key fetch of the caller's own row, with no
WHERE clause to get an access rule wrong in.

**The line is *building* a statement, not executing one.** `my_reminders`
runs `reminders_service.mine_stmt(...)`, exactly as the routers do; the
access rule is the service's. What must not happen in this module is the
WHERE clause being written here.

**What an agent may do on its own is stated in the descriptions, because
there is nowhere else to put it.** The field report that prompted all of
this noted the author wouldn't have moved a status, set a due date or closed
anything unasked — and that *their own judgement* was the only thing
enforcing it, so a different model would draw the line elsewhere. A
propose/accept tier is the heavyweight answer (every mutation grows a
proposal path, a review surface and a notification kind); this codebase
already has evidence the cheap one works, since `planner_bucket`'s
description does exactly this job and was singled out as the best-written
one on the surface.

So the server `instructions` carry the principle once — *recording is yours,
deciding is theirs*: comments, checklist items, dependencies, time and notes
describe what you found and can be written freely; closing a task, moving
its status, or putting it on a named person's plate are statements a
colleague acts on. `update_task` names the three fields that qualify
(`status`, `owner_email`, `action_required_email`) and explicitly places
`title`/`description`/`priority`/`due_on`/`project_id` in between, and
`close_task` says to comment instead when a task merely *looks* finished.
**Nothing enforces any of it, and the text says so** — pretending otherwise
would be the worse failure, since a client can ignore every word.


Four things cost real time here, all of them non-obvious:

- **There are two classes called `Context` in the SDK.** The tool decorator
  only recognises `mcp.server.mcpserver.context.Context`; passing the other
  type-checks fine and then fails at registration with a Pydantic
  `IsInstanceSchema` error that says nothing about the actual mistake.
- **`Mount` never matches its own bare path.** Mounting the transport at
  `/mcp` puts the endpoint at `/mcp/`, and a POST to `/mcp` gets a 307 that
  the client doesn't follow — surfacing as "Unexpected content type:", the
  empty body of the redirect. `MCPPath` in `main.py` rewrites the one path.
- **DNS-rebinding protection defaults to 127.0.0.1.** Behind Caddy the Host is
  whatever `SITE_URL` says, so every call is refused with "Invalid Host
  header", which reads like a proxy fault. `SITE_URL` feeds it, as it feeds
  everything else.
- **Stateless, on purpose.** A stateful transport hands out a session id and
  expects the next call to reach the worker that issued it — but uvicorn runs
  several and nothing is shared. Same reasoning as putting realtime through
  Redis; here the cheaper answer is to need no session at all.
- **claude.ai's and ChatGPT's own "Add custom connector" flows now work —
  this used to be flatly untrue, and the fix wasn't OAuth, at first.** The
  original symptom ("Couldn't register with ayeaye's sign-in service…")
  looked like this server needed to run an authorisation server, but the
  actual bug was a Caddy misconfiguration: every `/.well-known/oauth-*`
  path fell through the SPA catch-all and answered `200` with the app's own
  HTML instead of `404`. An OAuth-aware client reads that `200` as "this
  server publishes protected-resource metadata," tries to parse the HTML as
  JSON, fails, and falls back to Dynamic Client Registration against an
  authorisation server that doesn't exist —
  [anthropics/claude-ai-mcp#457](https://github.com/anthropics/claude-ai-mcp/issues/457)
  traced the identical symptom on a different server to exactly this, fixed
  with a plain 404, no OAuth involved. See `infra/caddy/Caddyfile`'s
  `@openid_discovery`/`@oauth_metadata` matchers. **Separately, and worth
  keeping distinct**: this server *now also* runs real OAuth 2.1 with
  Dynamic Client Registration (see the section below), because ChatGPT's
  connector has no bearer-token fallback at all and mandates it — the Caddy
  fix alone was necessary but not sufficient for that client.
- **A `Denied` refusal's own message didn't reach the client, and the cause
  was here, not in the SDK.** Every refusal — "no such organisation", "not a
  member", "this credential is read-only" — arrived as the bare string
  `Error executing tool <name>`, with the one sentence saying what to do
  about it dropped. This was written up here as an installed dependency's
  behaviour and left; it wasn't. The SDK draws a deliberate line between a
  failure a tool *anticipated* and a crash: raise `ToolError` and your
  message reaches the model in the `is_error` result, raise anything else
  and it is treated as an unhandled exception, whose text is kept on the
  server precisely so a crash cannot leak internals. `Denied` subclassed
  plain `Exception`, so every refusal in this module took the crash path and
  got the generic string it is designed to produce. **`class Denied(ToolError)`
  is the whole fix**, and the assertions in `scripts/e2e-mcp.sh` that grep
  for refusal wording pass on their own terms now.

  The two things that hid it are both worth keeping: the client this most
  affected — the menu bar app in the `ayeaye-menubar` repo — had already
  worked around it by *substituting a guess* ("if your token is read-only,
  make a write one") whenever the text began `Error executing tool`, which
  is a plausible sentence in front of somebody at the cost of never showing
  the real one. And `e2e-mcp.sh`'s own assertions for it were reading as
  passes: **bash 3.2, which is what macOS ships, mis-parses a `\"` inside a
  `$(...)` inside a double-quoted string** and splits the result into two
  words, so `ok` compared its own `$2` against a `$3` that was never the
  expected value. Any new assertion in that file builds its argument object
  into a variable first (`args key=value …`) — see the note on this at the
  top of the "lists a client needs" section there.

**A warning about testing it from a shell.** `e2e-mcp.sh` builds every payload
with `python3 -c json.dumps`, never with escaped quotes inside a shell string.
The inline form silently mangled the request for the calls with the most
arguments — the shell passed a fragment, the server correctly answered
"Parse error", and the harness's own helper swallowed it. It looked exactly
like MCP was losing writes, and it cost an hour of hunting a bug that was
never in the product.

## OAuth 2.1, for Claude.ai and ChatGPT's own connectors

Read `services/oauth.py`. Dynamic Client Registration (RFC 7591), PKCE-only
authorization codes, and rotating refresh tokens — what lets Claude.ai and
ChatGPT add this server as a custom connector with nobody pasting a
personal access token, which their own "connect an MCP server" flows both
expect and (for ChatGPT) mandate outright.

**Hand-rolled, the identical call already made for MFA.** SuperTokens'
`OAuth2Provider` recipe is a paid add-on on the self-hosted core — a
license key, a minimum $100/month, activated against SuperTokens' own
license servers — and even paid for, its "create a client" operation is an
*admin*-authenticated API call, not the public self-registration these
connectors actually need at connect time. Same shape of decision this
codebase already made for `services/mfa.py` (`pyotp`, after SuperTokens'
MFA recipe returned a 402): pay for infrastructure this project's whole
self-hosting philosophy is built around not needing, or hand-roll the
piece that's actually missing.

**No new dependency, because `mcp` already ships one.** The MCP Python SDK
— already a mandatory dependency of `app/mcp/server.py` — carries a
complete, async-native OAuth toolkit: RFC-correct Pydantic wire models
(`mcp.shared.auth`: `OAuthClientMetadata`, `OAuthMetadata`,
`ProtectedResourceMetadata`, `OAuthToken`) and the resource-server
verification primitive (`mcp.server.auth.provider.TokenVerifier`). Every
one of these was confirmed against the actually-installed package before
being relied on, not assumed from documentation. Client registration,
PKCE, and code/token issuance are still plain `async def`s against
SQLAlchemy — the identical idiom `services/tokens.py` already uses for
personal access tokens.

**A missing or bad token needs a real 401 — this codebase almost got it
wrong regardless of OAuth.** `_caller()` used to raise `Denied` *inside* a
tool call, which the MCP protocol turns into an ordinary `200 OK`
JSON-RPC result with an error string in the body — never an HTTP 401. An
OAuth-aware client never sees that as "go start OAuth"; it needs
`WWW-Authenticate` on its very first touch of `/mcp`. Fixing this needed
transport-layer middleware composed by hand around the bare `_mcp_asgi` in
`main.py` — `mcp.streamable_http_app()`'s own return value (a Starlette app
with its own auth routes) is discarded and never mounted, for the `/mcp`
vs `/mcp/` reason `MCPPath` already documents, so its own wiring never ran
either way. `RequireAuthMiddleware` → `AuthContextMiddleware` →
`AuthenticationMiddleware(backend=BearerAuthBackend(token_verifier))`,
wrapped around `_mcp_asgi` before `MCPPath`. `_caller()` now just resolves
the already-verified principal (`get_access_token()`) to a `User` row; a
`_Principal` shim carrying only `.scope` is what lets `_require_write()`
stay unchanged regardless of which credential shape verified the call.

**Four rules**, mirroring `services/tokens.py`'s own three almost exactly:

1. **A client is public unless it proves otherwise.** DCR has no admin
   step, so `client_secret_hash` is NULL for most clients — PKCE is the
   whole proof of possession, OAuth 2.1's own preferred shape.
2. **Every code and refresh token is claimed, not read then trusted.**
   `redeem_code`/`redeem_refresh_token` both use the identical
   `UPDATE … WHERE … RETURNING` shape `reminders.claim` and
   `exports.claim_expired` already use — select-then-update would leave a
   window where two racing requests both succeed, which for a refresh
   token is exactly the reuse this exists to catch.
3. **A rotated refresh token presented again is treated as theft.**
   `replaced_at` is set, not the row deleted, specifically so reuse is
   recognisable — and the whole grant is revoked defensively when it
   happens, not just the one request refused.
4. **A grant's scope is a ceiling, not a promise.** `OAuthClient.scope` is
   what a client may ever be granted; the person consenting narrows it
   further at `/oauth/authorize`, and whatever they chose is copied onto
   each token *at issuance* — a later re-consent never reaches back into a
   token already handed out.

**The consent screen is a real React page, not server-rendered HTML** —
this codebase's firm "browser-facing = React, API = JSON" boundary (the
same reasoning that moved interactive docs under `/api/docs` rather than
breaking it). `views/OAuthAuthorize.tsx` is modelled on `AcceptInvite.tsx`
exactly: outside the signed-in shell, an unauthenticated preview (a
client's name and scope ceiling are public metadata), "sign in, then come
straight back" via `redirectToPath` carrying every original query param,
Allow/Deny once signed in. `POST /api/oauth/authorize/decision`
re-validates everything server-side — nothing the SPA merely echoed back
is ever trusted outright.

**Only the two spec-fixed `.well-known` documents live at the bare
root** (`api/routers/wellknown.py`, mounted in `main.py` like `/health`):
RFC 8414's authorization-server metadata and RFC 9728's protected-resource
metadata (both the bare form and the path-inserted
`/.well-known/oauth-protected-resource/mcp`, the exact request an
OAuth-aware connector makes). Everything else — `/register`, the
`/authorize/preview`+`/decision` pair, `/token`, `/revoke` — lives under
`/api/oauth/*` like the rest of the JSON API, even though the *browser*
lands on the bare `/oauth/authorize` page first; the metadata document is
free to point at whichever URL shape each endpoint actually needs.
`openid-configuration` stays 404 forever (see `infra/caddy/Caddyfile`) —
this is an OAuth 2.1 authorization server issuing scoped API access
tokens, not an OIDC identity provider, and a 200 there would claim a
capability that doesn't exist.

**The Account screen's "Connected apps" card is the revocation surface**,
structurally copied from the Access Tokens card beside it — same
`role="region"`, same row shape, same ghost Revoke button. It's a
different list from Access Tokens on purpose: a personal access token is
something *you* minted; a connected app is a client that registered
itself and went through consent.
