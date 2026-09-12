#!/usr/bin/env bash
#
# Phase 11: personal access tokens and the MCP endpoint.
#
#   docker compose up -d && ./scripts/e2e-mcp.sh
#
# MCP is a new *surface*, not a new access path — every tool goes through the
# same `services/access.py` as the REST API, as the token's owner. The checks
# that matter are therefore the refusals: a token must not see one row its
# owner can't, and a read-only token must not change anything.
#
# Creates real accounts and leaves them behind. Dev stacks only.
set -u
B=http://localhost
S=$(date +%s)
pass=0; fail=0
ok(){ if [ "$2" = "$3" ]; then echo "  ok   $1"; pass=$((pass+1)); else echo "  FAIL $1: expected [$3] got [$2]"; fail=$((fail+1)); fi; }

signup(){ curl -s -c "$1" -o /dev/null -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  -H 'st-auth-mode: cookie' -X POST $B/api/auth/signup \
  -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$2\"},{\"id\":\"password\",\"value\":\"Testpass123\"}]}"; }
code(){ curl -s -o /dev/null -w '%{http_code}' "$@"; }
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }

# One JSON-RPC call over the MCP transport. **No handshake**: the server is
# stateless, so every request stands alone — which is the property that lets
# any number of API workers serve it, and incidentally makes it testable with
# curl.
#
# The payload is assembled by python, not by nesting escaped quotes inside a
# shell string. That is not fussiness: the escaped-quote version silently
# mangled the JSON for the calls with the most arguments, the server correctly
# answered "Parse error", and it read as a lost write for an hour.
rpc(){ # $1 token  $2 method  $3 params-json
  python3 -c "import json,sys; print(json.dumps({'jsonrpc':'2.0','id':1,'method':sys.argv[1],'params':json.loads(sys.argv[2])}))" "$2" "$3" > /tmp/mcp-req.json
  curl -s -X POST $B/mcp \
    -H "Authorization: Bearer $1" -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'MCP-Protocol-Version: 2025-06-18' \
    --data-binary @/tmp/mcp-req.json
}
# Build a JSON object from key=value pairs. No escaped quotes in the script,
# which is the entire point — see the note on `rpc`.
args(){ python3 -c "
import json,sys
print(json.dumps(dict(p.split('=',1) for p in sys.argv[1:])))
" "$@"; }

planned_in_bucket(){ # $1 cookie-jar  $2 bucket  $3 task-id
  curl -s -b "$1" $B/api/organisations/$OID/planner \
    | j "sum(1 for e in d['buckets']['$2'] if e['task']['id']=='$3')"; }
planned_total(){ curl -s -b "$1" $B/api/organisations/$OID/planner | j "sum(len(v) for v in d['buckets'].values())"; }

tool(){ # $1 token  $2 tool-name  $3 arguments-json
  python3 -c "import json,sys; print(json.dumps({'name':sys.argv[1],'arguments':json.loads(sys.argv[2])}))" "$2" "$3" > /tmp/mcp-args.json
  rpc "$1" tools/call "$(cat /tmp/mcp-args.json)"
}

text(){ python3 -c "
import json,sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except ValueError:
    # Loudly: empty output would satisfy every \"expected 0 matches\" check
    # in this file, which is how a broken harness reads as a passing one.
    print('UNPARSEABLE:', raw[:300]); sys.exit(0)
r = d.get('result') or {}
c = r.get('content') or []
print((c[0].get('text','') if c else json.dumps(d))[:4000])
"; }

# A missing or bad token is refused at the *transport* layer now — a real
# HTTP 401 with WWW-Authenticate, before any tool call runs — not a 200
# JSON-RPC result with an error string buried in it. See CLAUDE.md's OAuth
# section for why: an OAuth-aware client needs that 401 to know to go start
# the flow at all, and a 200-with-embedded-error never gave it that signal.
mcp_status(){ # extra curl args, e.g. -H "Authorization: Bearer X"
  curl -s -o /dev/null -w '%{http_code}' -X POST $B/mcp \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -H 'MCP-Protocol-Version: 2025-06-18' "$@" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
}
mcp_www_authenticate(){ # same request, prints the WWW-Authenticate header
  curl -s -D - -o /dev/null -X POST $B/mcp \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -H 'MCP-Protocol-Version: 2025-06-18' "$@" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
    | grep -i '^www-authenticate:' | tr -d '\r'
}

ALICE=ma$S@example.com; BOB=mb$S@example.com
signup /tmp/ma.jar $ALICE; signup /tmp/mb.jar $BOB
OID=$(post /tmp/ma.jar $B/api/organisations "{\"name\":\"Fleet $S\"}" | j "d['id']")
TID=$(post /tmp/ma.jar $B/api/organisations/$OID/tasks '{"title":"Replace the anode","priority":"high"}' | j "d['id']")

echo "== minting a token"
CREATED=$(post /tmp/ma.jar $B/api/me/tokens '{"name":"Claude","scope":"write"}')
WRITE=$(echo "$CREATED" | j "d['token']")
ok "the plaintext comes back once" "$(echo "$CREATED" | j "d['token'].startswith('ayc_')")" "True"
ok "and is never listed again"     "$(curl -s -b /tmp/ma.jar $B/api/me/tokens | j "any('token' in t for t in d)")" "False"
ok "the prefix is, so you can tell them apart" "$(curl -s -b /tmp/ma.jar $B/api/me/tokens | j "d[0]['prefix'][:4]")" "ayc_"
READ=$(post /tmp/ma.jar $B/api/me/tokens '{"name":"Read only","scope":"read"}' | j "d['token']")

echo "== the endpoint answers"
ok "tools are advertised"       "$(rpc "$WRITE" tools/list '{}' | j "len(d['result']['tools']) >= 8")" "True"
ok "…each with a description"   "$(rpc "$WRITE" tools/list '{}' | j "all(t.get('description') for t in d['result']['tools'])")" "True"
ok "no token is refused, with a real 401" "$(mcp_status)" "401"
ok "...naming the resource metadata"      "$(mcp_www_authenticate | grep -c resource_metadata)" "1"
ok "a made-up token is refused, with a real 401" \
  "$(mcp_status -H 'Authorization: Bearer ayc_nonsense')" "401"

echo "== it acts as the person, and sees exactly what they see"
ok "alice's organisation"       "$(tool "$WRITE" organisations '{}' | text | grep -c "$OID")" "1"
ok "alice's task"               "$(tool "$WRITE" list_tasks "{\"organisation_id\":\"$OID\"}" | text | grep -c "Replace the anode")" "1"
# Bob is a stranger. His token must not reach Alice's organisation at all —
# and the refusal must not confirm that it exists.
BOBTOK=$(post /tmp/mb.jar $B/api/me/tokens '{"name":"Bob","scope":"write"}' | j "d['token']")
ok "a stranger's token sees no orgs"  "$(tool "$BOBTOK" organisations '{}' | text | grep -c "$OID")" "0"
ok "…and is refused by name"          "$(tool "$BOBTOK" list_tasks "{\"organisation_id\":\"$OID\"}" | text | grep -ci "no such organisation")" "1"
ok "…and cannot read the task"        "$(tool "$BOBTOK" task "{\"organisation_id\":\"$OID\",\"task_id\":\"$TID\"}" | text | grep -ci "no such")" "1"

echo "== a hidden task is hidden from MCP too"
# The one place access is subtracted. If the tools went round the service
# layer this is the check that would catch it.
curl -s -o /dev/null -b /tmp/ma.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/hidden -d '{"hidden":true}'
ADMIN=mc$S@example.com; signup /tmp/mc.jar $ADMIN
T=$(post /tmp/ma.jar $B/api/organisations/$OID/invites "{\"email\":\"$ADMIN\",\"role\":\"admin\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/mc.jar -X POST $B/api/invites/$T/accept
ADMTOK=$(post /tmp/mc.jar $B/api/me/tokens '{"name":"Admin","scope":"read"}' | j "d['token']")
ok "an org admin's token can't see it" "$(tool "$ADMTOK" list_tasks "{\"organisation_id\":\"$OID\"}" | text | grep -c "Replace the anode")" "0"
ok "…while the owner's still can"      "$(tool "$WRITE" list_tasks "{\"organisation_id\":\"$OID\"}" | text | grep -c "Replace the anode")" "1"
curl -s -o /dev/null -b /tmp/ma.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/hidden -d '{"hidden":false}'

echo "== mine_only means owned OR asked to act, not just owned"
# It used to pass owner_user_id alone, so a task somebody had asked you to
# act on was missing from "only tasks you own or have been asked to act on"
# — which is most of the point of being asked. The admin account is the
# handy second person here: they own nothing in this organisation.
#
# Every multi-key body below is built into a variable first, never written
# as a literal inside the `$(...)` capture. A `{...}` containing a comma,
# nested two quote-levels deep, is silently torn in two by brace expansion
# — the call then fails, `grep -c` answers 0, and an assertion expecting 0
# passes for entirely the wrong reason. Which is exactly what the first
# version of this block did.
ADMIN_ID=$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$ADMIN'][0]")
ASKED_BODY="{\"title\":\"Waiting on the admin\",\"action_required_user_id\":\"$ADMIN_ID\"}"
post /tmp/ma.jar $B/api/organisations/$OID/tasks "$ASKED_BODY" >/dev/null
MINE="{\"organisation_id\":\"$OID\",\"mine_only\":true}"
ADMIN_MINE=$(tool "$ADMTOK" list_tasks "$MINE" | text)
# Either answer proves the tool ran; only a torn-in-two request gives
# neither. Deliberately not "did it list something", which would conflate
# a mangled call with a filter that is simply wrong — and the point of
# this guard is to tell those two apart.
ok "the call itself worked"           "$(echo "$ADMIN_MINE" | grep -cE "task\(s\):|Nothing matches")" "1"
ok "they own nothing here"            "$(echo "$ADMIN_MINE" | grep -c "Replace the anode")" "0"
ok "…but being asked to act counts"   "$(echo "$ADMIN_MINE" | grep -c "Waiting on the admin")" "1"
OWNER_MINE=$(tool "$WRITE" list_tasks "$MINE" | text)
ok "and the owner sees it as theirs"  "$(echo "$OWNER_MINE" | grep -c "Waiting on the admin")" "1"

echo "== read-only means read only"
ok "a read token lists"         "$(tool "$READ" list_tasks "{\"organisation_id\":\"$OID\"}" | text | grep -c "Replace the anode")" "1"
ok "…and cannot create"         "$(tool "$READ" create_task "{\"organisation_id\":\"$OID\",\"title\":\"nope\"}" | text | grep -ci "read-only")" "1"
ok "…nor comment"               "$(tool "$READ" comment "$(args organisation_id=$OID task_id=$TID body=nope)" | text | grep -ci "read-only")" "1"
ok "nothing was created"        "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks | j "sum(1 for t in d if t['title']=='nope')")" "0"

echo "== writing, as the person"
NEW=$(tool "$WRITE" create_task "{\"organisation_id\":\"$OID\",\"title\":\"From the assistant\",\"priority\":\"urgent\"}" | text)
ok "creates a task"             "$(echo "$NEW" | grep -c 'From the assistant')" "1"
ok "…owned by the token holder" "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks | j "[t['owner']['email'] for t in d if t['title']=='From the assistant'][0]")" "$ALICE"
ok "…and recorded in history"   "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks | j "[t['priority'] for t in d if t['title']=='From the assistant'][0]")" "urgent"
ok "creating for a stranger is refused" "$(tool "$WRITE" create_task "{\"organisation_id\":\"$OID\",\"title\":\"x\",\"owner_email\":\"nobody@example.com\"}" | text | grep -ci "not a member")" "1"
CARGS=$(args organisation_id=$OID task_id=$TID "body=Ordered today $S")
ok "commenting works"           "$(tool "$WRITE" comment "$CARGS" | text | grep -c "Posted")" "1"
ok "…and it is a real comment"  "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks/$TID/comments | j "sum(1 for m in d['messages'] if m['body']=='Ordered today $S')")" "1"

echo "== a task reads back its own state, not just its history"
# The gap this closes, reported from a real day of agent-assisted work: an
# assistant resuming a task got its title, status and a list of event
# *kinds* — none of which say what was decided, what was corrected, or what
# is waiting on a person. All of that lives in the comment thread, so a task
# read without it looks like a task nobody has started, and the honest move
# after that is to begin again.
SECOND=$(post /tmp/ma.jar $B/api/organisations/$OID/tasks '{"title":"Order the zinc"}' | j "d['id']")
TASKARGS=$(args organisation_id=$OID task_id=$TID)
SECONDARGS=$(args organisation_id=$OID task_id=$SECOND)
READBACK=$(tool "$WRITE" task "$TASKARGS" | text)
ok "the comment comes back"            "$(echo "$READBACK" | grep -c "Ordered today $S")" "1"
ok "…saying who wrote it"              "$(echo "$READBACK" | grep -c "$ALICE")" "1"
ok "…under a heading that counts them" "$(echo "$READBACK" | grep -c 'comments (1, oldest first)')" "1"
ok "history is still there"            "$(echo "$READBACK" | grep -c 'history (oldest first)')" "1"
# Reading must not bring a thread into existence: `for_task` is called with
# create=False, and a task nobody has commented on has no conversation row.
ok "a task with no thread reads fine"  "$(tool "$WRITE" task "$SECONDARGS" | text | grep -c 'Order the zinc')" "1"
ok "…and grew no comments section"     "$(tool "$WRITE" task "$SECONDARGS" | text | grep -c 'comments (')" "0"

echo "== tasks can reference each other"
# `task_dependencies` existed with no MCP tool, so an assistant expressing
# "this is waiting on that" had to type a UUID into English prose on the
# parent. Both directions read back, because the reverse query is free.
DEPARGS=$(args organisation_id=$OID task_id=$TID depends_on_task_id=$SECOND)
ok "add a dependency"               "$(tool "$WRITE" add_dependency "$DEPARGS" | text | grep -c 'is now waiting on')" "1"
ok "it reads back on the task"      "$(tool "$WRITE" task "$TASKARGS" | text | grep -c "waiting on: \[$SECOND\]")" "1"
ok "…with the other one's status"   "$(tool "$WRITE" task "$TASKARGS" | text | grep -c 'Order the zinc (status=todo, open)')" "1"
ok "…and the far end says so too"   "$(tool "$WRITE" task "$SECONDARGS" | text | grep -c "blocking: \[$TID\]")" "1"
# The refusals matter more than the happy path, and they only reach a client
# at all because `Denied` is a `ToolError` and a service's HTTPException is
# converted to one — otherwise every sentence below arrives as the bare
# string "Error executing tool add_dependency".
REVERSE=$(args organisation_id=$OID task_id=$SECOND depends_on_task_id=$TID)
ok "a cycle is refused, and says why"  "$(tool "$WRITE" add_dependency "$REVERSE" | text | grep -ci 'cycle')" "1"
SELFDEP=$(args organisation_id=$OID task_id=$TID depends_on_task_id=$TID)
ok "…so is depending on itself"        "$(tool "$WRITE" add_dependency "$SELFDEP" | text | grep -ci 'cannot depend on itself')" "1"
ok "…and the same edge twice"          "$(tool "$WRITE" add_dependency "$DEPARGS" | text | grep -ci 'already linked')" "1"
ok "a task you can't see is 404-shaped" \
  "$(tool "$WRITE" add_dependency "$(args organisation_id=$OID task_id=$TID depends_on_task_id=$(uuidgen | tr 'A-Z' 'a-z'))" | text | grep -ci 'not found')" "1"
ok "a read-only token cannot link"     "$(tool "$READ" add_dependency "$DEPARGS" | text | grep -ci 'read-only')" "1"
ok "remove it again"                   "$(tool "$WRITE" remove_dependency "$DEPARGS" | text | grep -c 'no longer waiting on')" "1"
ok "…and it is gone from the task"     "$(tool "$WRITE" task "$TASKARGS" | text | grep -c 'waiting on:')" "0"
ok "…removing it twice is refused"     "$(tool "$WRITE" remove_dependency "$DEPARGS" | text | grep -ci 'not waiting on that one')" "1"

echo "== checklists, so progress is machine-readable"
# The steps were a markdown list inside a description: nothing could tick an
# item and nothing could be asked what was outstanding. `items` on create is
# the ergonomic half — filing seven steps should be one call, not eight.
CLARGS=$(python3 -c "
import json, sys
print(json.dumps({'organisation_id': sys.argv[1], 'task_id': sys.argv[2], 'title': 'Before we deploy',
                  'items': ['Set the flag', 'Rename the healthcheck']}))" "$OID" "$TID")
CLOUT=$(tool "$WRITE" add_checklist "$CLARGS" | text)
ok "creates a list with its items"       "$(echo "$CLOUT" | grep -c 'Set the flag')" "1"
CHECKLISTS=$B/api/organisations/$OID/tasks/$TID/checklists
CLID=$(curl -s -b /tmp/ma.jar $CHECKLISTS | j "d[0]['id']")
ITEM=$(curl -s -b /tmp/ma.jar $CHECKLISTS | j "d[0]['items'][0]['id']")
ok "a blank line is not an item"         "$(curl -s -b /tmp/ma.jar $CHECKLISTS | j "len(d[0]['items'])")" "2"
ok "it reads back on the task, unticked" "$(tool "$WRITE" task "$TASKARGS" | text | grep -c '\[ \] Set the flag')" "1"
ok "…with the list's own progress"       "$(tool "$WRITE" task "$TASKARGS" | text | grep -c '0/2 done')" "1"
TICK=$(python3 -c "
import json, sys
print(json.dumps({'organisation_id': sys.argv[1], 'task_id': sys.argv[2], 'item_id': sys.argv[3], 'done': True}))
" "$OID" "$TID" "$ITEM")
ok "ticking one reports what is left"    "$(tool "$WRITE" check_item "$TICK" | text | grep -c '1 left on that list')" "1"
ok "…and the task shows it ticked"       "$(tool "$WRITE" task "$TASKARGS" | text | grep -c '\[x\] Set the flag')" "1"
ADDITEM=$(args organisation_id=$OID task_id=$TID checklist_id=$CLID 'text=Back up first')
ok "adding one more item"                "$(tool "$WRITE" add_checklist_item "$ADDITEM" | text | grep -c 'Back up first')" "1"
ok "…counted in the list's progress"     "$(tool "$WRITE" task "$TASKARGS" | text | grep -c '1/3 done')" "1"
ok "an item id from nowhere is refused"  "$(tool "$WRITE" check_item "$(args organisation_id=$OID task_id=$TID item_id=$SECOND)" | text | grep -ci 'no checklist item')" "1"
ok "a checklist on another task too"     "$(tool "$WRITE" add_checklist_item "$(args organisation_id=$OID task_id=$SECOND checklist_id=$CLID text=nope)" | text | grep -ci 'not found')" "1"
# Read-only is the token's scope here, not the task's level — Alice's own
# read token against Alice's own task, so the only thing that differs is
# what the credential is allowed to do.
ok "a read-only token cannot tick"       "$(tool "$READ" check_item "$TICK" | text | grep -ci 'read-only')" "1"
ok "…nor start a list"                   "$(tool "$READ" add_checklist "$CLARGS" | text | grep -ci 'read-only')" "1"
ok "…and nothing changed"                "$(curl -s -b /tmp/ma.jar $CHECKLISTS | j "len(d)")" "1"

echo "== a write says what acted on the person's behalf"
# The friction this closes: everything an assistant wrote appeared to have
# been written by its owner, and the workaround was a convention — "prefix
# any comment with [Claude] so i know where it came from" — that only holds
# as long as one model remembers it. `via` is the token's own name, carried
# out of the verifier as RFC 8693's `act` claim.
#
# **Attribution, not authorship.** The comment is still Alice's: a token is
# a person, which is this whole surface's one rule. `via` only says how the
# words arrived.
VIAARGS=$(args organisation_id=$OID task_id=$TID "body=Posted by an assistant $S")
ok "posting says it was attributed" "$(tool "$WRITE" comment "$VIAARGS" | text | grep -c 'via Claude')" "1"
COMMENTS=$B/api/organisations/$OID/tasks/$TID/comments
ok "…and the API carries it"        "$(curl -s -b /tmp/ma.jar $COMMENTS | j "[m['via'] for m in d['messages'] if m['body']=='Posted by an assistant $S'][0]")" "Claude"
ok "…while the author is still you" "$(curl -s -b /tmp/ma.jar $COMMENTS | j "[m['author']['email'] for m in d['messages'] if m['body']=='Posted by an assistant $S'][0]")" "$ALICE"
# The web app sends no `via` at all, and a row written before this existed
# holds NULL for the same reason — "a person typed it" is what NULL means,
# which is why there was nothing to backfill.
PLAIN=$(post /tmp/ma.jar $COMMENTS "{\"body\":\"Typed in the browser $S\"}")
ok "a comment from the web app has none" \
  "$(curl -s -b /tmp/ma.jar $COMMENTS | j "[m['via'] for m in d['messages'] if m['body']=='Typed in the browser $S'][0] is None")" "True"
# Both read back on the task, one header each. Scoped with `grep -B1` to the
# body it belongs to rather than counting "via Claude" across the whole
# thread — every comment this suite posts goes through the same token, so a
# bare count is a number that grows whenever a test above adds a comment.
READOUT=$(tool "$WRITE" task "$TASKARGS" | text)
ok "the assistant's own line names it" \
  "$(echo "$READOUT" | grep -B1 "Posted by an assistant $S" | grep -c "$ALICE via Claude")" "1"
ok "…and the browser's line does not" \
  "$(echo "$READOUT" | grep -B1 "Typed in the browser $S" | grep -c ' via ')" "0"
# The name is whatever the person called the credential, not a hardcoded
# word — a second token proves the value is carried rather than invented.
OTHERTOK=$(post /tmp/ma.jar $B/api/me/tokens '{"name":"Scripted nightly","scope":"write"}' | j "d['token']")
OTHERARGS=$(args organisation_id=$OID task_id=$TID "body=From the nightly job $S")
ok "a differently-named token says so" "$(tool "$OTHERTOK" comment "$OTHERARGS" | text | grep -c 'via Scripted nightly')" "1"

echo "== retrying a write does not duplicate it"
# Agents retry. A timeout says nothing about whether the task was created,
# and the move that looks safest — call it again — is the one that files a
# duplicate. Same key, same answer, one row.
KEY="order-the-zinc-$S"
IDEM=$(args organisation_id=$OID title="Fit the new anode $S" idempotency_key=$KEY)
FIRST=$(tool "$WRITE" create_task "$IDEM" | text)
SECOND_TRY=$(tool "$WRITE" create_task "$IDEM" | text)
ok "the first call creates"           "$(echo "$FIRST" | grep -c "Fit the new anode $S")" "1"
ok "the second says already created"  "$(echo "$SECOND_TRY" | grep -ci 'already created')" "1"
ok "…naming the very same task"       "$(echo "$SECOND_TRY" | grep -c "$(echo "$FIRST" | sed 's/.*\[\(.*\)\].*/\1/')")" "1"
ok "…and there is exactly one task"   "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks | j "sum(1 for t in d if t['title']=='Fit the new anode $S')")" "1"
# Without a key the old behaviour is untouched: two calls, two tasks. Worth
# asserting, because a key that silently applied to every call would make
# "file two of these" impossible.
NOKEY=$(args organisation_id=$OID title="Unkeyed twice $S")
tool "$WRITE" create_task "$NOKEY" >/dev/null
tool "$WRITE" create_task "$NOKEY" >/dev/null
ok "no key still means no dedupe"     "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks | j "sum(1 for t in d if t['title']=='Unkeyed twice $S')")" "2"
# A key is scoped to the person: two people using the same obvious string
# must not collide, and Bob's own key must not resolve to Alice's task.
CKEY="comment-$S"
CIDEM=$(args organisation_id=$OID task_id=$TID "body=Only once please $S" idempotency_key=$CKEY)
tool "$WRITE" comment "$CIDEM" >/dev/null
ok "a retried comment says so"        "$(tool "$WRITE" comment "$CIDEM" | text | grep -ci 'already posted')" "1"
ok "…and was posted exactly once"     "$(curl -s -b /tmp/ma.jar $COMMENTS | j "sum(1 for m in d['messages'] if m['body']=='Only once please $S')")" "1"
# Reusing one key for a different operation is a caller bug. Answering it
# with the first operation's id would be confidently wrong, which is worse
# than a refusal that says what happened.
ok "the same key on another tool is refused" \
  "$(tool "$WRITE" create_task "$(args organisation_id=$OID title=nope idempotency_key=$CKEY)" | text | grep -ci "already used for 'comment'")" "1"

# The two states a *claimed but unfinished* key can be in, which curl alone
# cannot reach: the work is running right now, or the process died holding
# the claim. Age is the only thing that tells them apart, so this stages a
# bare claim and then ages it — the same "reach into the stack to move a
# clock" move `e2e-reminders.sh` makes for its own sweep, and for the same
# reason: five real minutes is not a test.
#
# `-e PYTHONPATH`: compose exec does not inherit the service's environment
# block, and the app lives under /app/src.
stage_claim(){ docker compose exec -T -e PYTHONPATH=/app/src api uv run python -c "
import asyncio, sys
from sqlalchemy import select, update
from app.db import SessionLocal
from app.models import User
from app.models.idempotency import IdempotencyKey
from app.services import idempotency

async def main(email, key, age_seconds):
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        await idempotency.claim(db, user.id, key, 'create_task')
        if int(age_seconds):
            # Backdate the claim rather than waiting out STALE_AFTER.
            await db.execute(
                update(IdempotencyKey)
                .where(IdempotencyKey.user_id == user.id, IdempotencyKey.key == key)
                .values(created_at=__import__('datetime').datetime.now(
                    __import__('datetime').UTC) - __import__('datetime').timedelta(seconds=int(age_seconds)))
            )
            await db.commit()

asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
" "$1" "$2" "$3" >/dev/null 2>&1; }

# A call that fails hands its key straight back, rather than leaving the
# caller locked out of their own corrected retry until STALE_AFTER.
BADKEY="bad-then-good-$S"
BAD=$(args organisation_id=$OID "title=Fixed on the second go $S" priority=enormous idempotency_key=$BADKEY)
ok "a bad argument is refused, readably" \
  "$(tool "$WRITE" create_task "$BAD" | text | grep -c 'priority must be one of')" "1"
GOOD=$(args organisation_id=$OID "title=Fixed on the second go $S" priority=high idempotency_key=$BADKEY)
ok "…and the same key still works"    "$(tool "$WRITE" create_task "$GOOD" | text | grep -c "Fixed on the second go $S")" "1"

LIVE="live-claim-$S"
stage_claim "$ALICE" "$LIVE" 0
ok "a claim still running says so, not a duplicate" \
  "$(tool "$WRITE" create_task "$(args organisation_id=$OID "title=Raced $S" idempotency_key=$LIVE)" | text | grep -ci 'already running')" "1"
ok "…and created nothing"             "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks | j "sum(1 for t in d if t['title']=='Raced $S')")" "0"
# Older than STALE_AFTER: the holder is a corpse, not a neighbour. Refusing
# for all time would punish the caller for our own crash.
DEAD="dead-claim-$S"
stage_claim "$ALICE" "$DEAD" 600
ok "an abandoned claim is taken over" \
  "$(tool "$WRITE" create_task "$(args organisation_id=$OID "title=Recovered $S" idempotency_key=$DEAD)" | text | grep -c "Recovered $S")" "1"

echo "== the lists a client needs to offer a choice"
# `create_task` names a project by id and a person by email, which is fine for
# an assistant reading prose and useless to anything drawing a dropdown — it
# has nowhere to get either. These two are what turn "pass an id you already
# know" into a list somebody can pick from.
#
# Every argument object is built into a variable first. Bash 3.2 — which is
# what macOS ships and what this file is run with — mis-parses a `\"` inside a
# `$(...)` inside a double-quoted string, and splits the result into two
# arguments: `ok` then compares its own $2 against a $3 that was never the
# expected value, and passes for no reason. There are older assertions in this
# file doing exactly that.
ORGARGS=$(args organisation_id=$OID)
PROJ=$(post /tmp/ma.jar $B/api/organisations/$OID/projects '{"name":"Refit"}' | j "d['id']")
PROJECTS=$(tool "$WRITE" list_projects "$ORGARGS" | text)
ok "projects list, with their ids"    "$(echo "$PROJECTS" | grep -c "$PROJ")" "1"
ok "…by name too"                     "$(echo "$PROJECTS" | grep -c "Refit")" "1"

# A plain member, because the access rule is the point of this tool and the
# admin already in this file is the wrong person to prove it with: an
# organisation admin sees every project by design. A project is private to its
# owner until shared, so this is the account that must not see Alice's.
MEMBER=md$S@example.com; signup /tmp/md.jar $MEMBER
MT=$(post /tmp/ma.jar $B/api/organisations/$OID/invites "{\"email\":\"$MEMBER\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/md.jar -X POST $B/api/invites/$MT/accept
MEMTOK=$(post /tmp/md.jar $B/api/me/tokens '{"name":"Member","scope":"read"}' | j "d['token']")
MEMBER_SEES=$(tool "$MEMTOK" list_projects "$ORGARGS" | text)
ok "a project you can't see isn't in it" "$(echo "$MEMBER_SEES" | grep -c "$PROJ")" "0"
ok "…while an org admin sees it, as everywhere else" \
  "$(tool "$ADMTOK" list_projects "$ORGARGS" | text | grep -c "$PROJ")" "1"
STRANGER_PROJECTS=$(tool "$BOBTOK" list_projects "$ORGARGS" | text)
ok "a stranger is refused by name"    "$(echo "$STRANGER_PROJECTS" | grep -ci "no such organisation")" "1"

MEMBERS=$(tool "$WRITE" list_members "$ORGARGS" | text)
ok "members list by email"            "$(echo "$MEMBERS" | grep -c "$ALICE")" "1"
ok "…including everyone who joined"   "$(echo "$MEMBERS" | grep -c "$ADMIN")" "1"
ok "…with their role"                 "$(echo "$MEMBERS" | grep "$MEMBER" | grep -c "role=member")" "1"
ok "…and says which one is you"       "$(echo "$MEMBERS" | grep "$ALICE" | grep -c "you")" "1"
ok "…but not a stranger"              "$(echo "$MEMBERS" | grep -c "$BOB")" "0"
# An invitation is somebody who cannot own a task or be asked to act on one
# yet, so offering them would only produce a choice every write tool then
# refuses with "not a member".
INVITED=mi$S@example.com
post /tmp/ma.jar $B/api/organisations/$OID/invites "{\"email\":\"$INVITED\",\"role\":\"member\"}" >/dev/null
STILL=$(tool "$WRITE" list_members "$ORGARGS" | text)
ok "an outstanding invitation is not offered" "$(echo "$STILL" | grep -c "$INVITED")" "0"

echo "== filing something straight onto your own planner"
PLANNED_BODY=$(args organisation_id=$OID "title=Chase the surveyor" planner_bucket=today)
PLANNED=$(tool "$WRITE" create_task "$PLANNED_BODY" | text)
PLANNED_ID=$(echo "$PLANNED" | sed -n 's/.*\[\([^]]*\)\].*/\1/p')
ok "the task is created"        "$(echo "$PLANNED" | grep -c "Chase the surveyor")" "1"
ok "…and it is in today"        "$(planned_in_bucket /tmp/ma.jar today "$PLANNED_ID")" "1"
BADBUCKET=$(args organisation_id=$OID "title=Guessed the bucket $S" planner_bucket=eventually)
REFUSED_BUCKET=$(tool "$WRITE" create_task "$BADBUCKET" | text)
ok "a bucket that isn't one is refused" "$(echo "$REFUSED_BUCKET" | grep -ci "not a planner bucket")" "1"
# The bucket is checked before anything is written. It used to be validated
# after the task had been created, so a guessed name refused the call *and*
# left the task behind — the worst of both.
ok "…and leaves no task behind"         "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks | j "sum(1 for t in d if t['title']=='Guessed the bucket $S')")" "0"
# A planner is one person's plan for their own week. Filing work for a
# colleague must not put it on their board — the caller's is the only board
# this argument can touch.
OTHER_BODY=$(args organisation_id=$OID "title=For the admin" owner_email=$ADMIN planner_bucket=today)
OTHER=$(tool "$WRITE" create_task "$OTHER_BODY" | text)
OTHER_ID=$(echo "$OTHER" | sed -n 's/.*\[\([^]]*\)\].*/\1/p')
ok "creating for somebody else plans it on *your* board" \
  "$(planned_in_bucket /tmp/ma.jar today "$OTHER_ID")" "1"
ok "…and not on theirs"         "$(planned_total /tmp/mc.jar)" "0"

echo "== tagging a task"
# Every step here is its own statement assigned to a plain variable before
# `ok` ever sees it — nesting a literal "{...}" with a comma inside a
# second layer of "$(...)" is the exact bash trap CLAUDE.md's own MCP
# section warns about, and this file already has a few pre-existing,
# silently-vacuous assertions from exactly that (comparing two
# independently-mangled values that happen to match). Not repeating it here.
TAGARGS=$(args organisation_id=$OID task_id=$TID tag=Billing)
TAGGED=$(tool "$WRITE" tag_task "$TAGARGS" | text)
ok "tagging creates and applies it" "$(echo "$TAGGED" | grep -c 'Billing')" "1"
ok "applying it again is idempotent, not an error" "$(echo "$TAGGED" | grep -ci error)" "0"

DUPARGS=$(args organisation_id=$OID task_id=$TID tag=billing)
tool "$WRITE" tag_task "$DUPARGS" >/dev/null
ok "same name different case reuses the tag, no twin created" \
  "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tags | j "sum(1 for t in d if t['name'].lower()=='billing')")" "1"

REFUSED=$(tool "$READ" tag_task "$TAGARGS")
ok "a read-only token is refused" "$(echo "$REFUSED" | j "d['result']['isError']")" "True"

# Write *scope*, read-only *access to the task* — a different refusal from
# the one above, which never reaches `tctx.require` at all because
# `_require_write` turns the credential away first. Until that `require` was
# wrapped in `_refusal`, this one arrived as the bare string "Error
# executing tool tag_task": a `tctx.require` raises an `HTTPException`,
# which the SDK treats as a crash and whose text it deliberately withholds.
#
# **The "Error executing tool X:" prefix is on every refusal, including a
# well-behaved one** — the SDK always writes it. So what distinguishes a
# refusal that reached the client from one that didn't is whether the
# sentence *after* the colon survived, which is why this asserts the whole
# string rather than the absence of the prefix.
MEMBER_ID=$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$MEMBER'][0]")
GRANTBODY="{\"user_id\":\"$MEMBER_ID\",\"level\":\"read\"}"
post /tmp/ma.jar $B/api/organisations/$OID/tasks/$TID/access "$GRANTBODY" >/dev/null
MEMWRITE=$(post /tmp/md.jar $B/api/me/tokens '{"name":"Member write","scope":"write"}' | j "d['token']")
MEMREFUSED=$(tool "$MEMWRITE" tag_task "$TAGARGS" | text)
ok "read-only access to the task refuses too" \
  "$(echo "$MEMREFUSED" | grep -c 'tag_task: you have read-only access to this task')" "1"

TASKARGS=$(args organisation_id=$OID task_id=$TID)
SHOWN=$(tool "$WRITE" task "$TASKARGS" | text)
ok "the task now shows the tag" "$(echo "$SHOWN" | grep -c 'tags: Billing')" "1"

UNTAGGED=$(tool "$WRITE" untag_task "$TAGARGS" | text)
ok "untagging removes it" "$(echo "$UNTAGGED" | grep -c Untagged)" "1"

BOGUSARGS=$(args organisation_id=$OID task_id=$TID tag=NoSuchTag)
BOGUS=$(tool "$WRITE" untag_task "$BOGUSARGS")
ok "untagging a name that was never applied is refused" "$(echo "$BOGUS" | j "d['result']['isError']")" "True"

echo "== the notification inbox"
# The count the menu bar badge is drawn from. Not organisation-scoped, on
# purpose — it is the same number the bell in the web app shows.
NONE=$(tool "$WRITE" notifications '{}' | text)
ok "says how many even when there are none" "$(echo "$NONE" | grep -c '^0 unread')" "1"
# Something that actually notifies somebody: being asked to act. Alice asks
# the admin, so the admin's inbox is the one that moves and hers is the one
# that must not.
ASK_BODY=$(args organisation_id=$OID "title=Look at the shackle" action_required_email=$ADMIN)
tool "$WRITE" create_task "$ASK_BODY" >/dev/null
ADMIN_INBOX=$(tool "$ADMTOK" notifications '{}' | text)
ok "being asked to act raises one"     "$(echo "$ADMIN_INBOX" | grep -c 'Look at the shackle')" "1"
ok "…and the count leads"              "$(echo "$ADMIN_INBOX" | head -1 | grep -cE '^[1-9][0-9]* unread:')" "1"
ok "…in the asked person's inbox only" "$(tool "$WRITE" notifications '{}' | text | grep -c '^0 unread')" "1"
ok "a stranger's inbox is their own"   "$(tool "$BOBTOK" notifications '{}' | text | grep -c '^0 unread')" "1"
# A read-only token must be able to read this: a status light is exactly what
# somebody should be able to point a read credential at.
ok "a read-only token can read it"     "$(tool "$MEMTOK" notifications '{}' | text | grep -c 'unread')" "1"

echo "== capturing a spark"
# The other thing the menu bar box can file. No organisation argument at all
# — the tool for the one record in this schema that has no organisation_id —
# and nobody but its author is ever meant to see it, which is what the two
# REST reads below are here to prove: there is no MCP read tool for sparks to
# check it with, on purpose.
SPARK=$(tool "$WRITE" create_spark "$(args 'body=Ask the yard about the shackle pin')" | text)
ok "a spark saves, and says so"       "$(echo "$SPARK" | grep -c 'Ask the yard about the shackle pin')" "1"
ok "…into your own list"              "$(curl -s -b /tmp/ma.jar $B/api/sparks | j "sum(1 for x in d if 'shackle pin' in x['body'])")" "1"
ok "…and nobody else's"               "$(curl -s -b /tmp/mb.jar $B/api/sparks | j "len(d)")" "0"
ok "an empty one is refused, and says why" \
  "$(tool "$WRITE" create_spark '{"body":"   "}' | text | grep -ci 'needs something in it')" "1"
ok "a read-only token can't capture one" \
  "$(tool "$READ" create_spark "$(args body=nope)" | text | grep -ci 'read-only')" "1"

echo "== the running timer"
# The menu bar draws a state light from this, so the line it answers with is
# a contract: `[task-id] | Title | organisation_id=… | elapsed=… | started=…`,
# and an installation that reworded it would leave the icon silently blank.
ok "nothing running says so, and names no task" \
  "$(tool "$WRITE" running_timer '{}' | text | grep -c '^Nothing is running\.$')" "1"
TIMERARGS=$(args organisation_id=$OID task_id=$TID)
STARTED=$(tool "$WRITE" start_timer "$TIMERARGS" | text)
ok "starting says which task"   "$(echo "$STARTED" | grep -c "\[$TID\]")" "1"
RUNNING=$(tool "$WRITE" running_timer '{}' | text)
ok "the running one is the task's id"    "$(echo "$RUNNING" | grep -c "^\[$TID\] |")" "1"
ok "…with its title, not just the id"   "$(echo "$RUNNING" | grep -c 'Replace the anode')" "1"
# The whole reason this tool takes no organisation: the caller has to be told
# which one it is in, because a timer left running in one is found from
# another — that is the field the menu bar builds a web link out of.
ok "…and the organisation it is in"     "$(echo "$RUNNING" | grep -c "organisation_id=$OID")" "1"
ok "…and how long it has been going"    "$(echo "$RUNNING" | grep -cE 'elapsed=[0-9]+[hm]')" "1"
ok "…and when it started, as a timestamp" "$(echo "$RUNNING" | grep -cE 'started=20[0-9]{2}-')" "1"
# Reading your own clock is a read. A status light is exactly the thing
# somebody should be able to point a read-only credential at — the same
# argument the notification count above makes.
ok "a read-only token can read it"      "$(tool "$MEMTOK" running_timer '{}' | text | grep -c 'Nothing is running')" "1"
# One per person, globally: a member's own timer is a different clock, and
# Alice's must not appear in it.
ok "…and sees its own, not somebody else's" \
  "$(tool "$MEMTOK" running_timer '{}' | text | grep -c "$TID")" "0"
# Starting elsewhere stops the first, rather than refusing — and the answer
# says so, which is the only way a caller can report it.
SECOND=$(tool "$WRITE" start_timer "$(args organisation_id=$OID task_id=$PLANNED_ID)" | text)
ok "starting another stops the first, and says which" \
  "$(echo "$SECOND" | grep -c "stopped the one running on \[$TID\]")" "1"
ok "…and the running one has moved"     "$(tool "$WRITE" running_timer '{}' | text | grep -c "^\[$PLANNED_ID\] |")" "1"
STOPPED=$(tool "$WRITE" stop_timer '{}' | text)
ok "stopping names what it stopped"     "$(echo "$STOPPED" | grep -c "\[$PLANNED_ID\]")" "1"
ok "…and then nothing is running"       "$(tool "$WRITE" running_timer '{}' | text | grep -c '^Nothing is running\.$')" "1"
ok "stopping nothing is not an error"   "$(tool "$WRITE" stop_timer '{}' | text | grep -c 'Nothing was running')" "1"
ok "a read-only token cannot start one" \
  "$(tool "$MEMTOK" start_timer "$TIMERARGS" | text | grep -ci 'read-only')" "1"

echo "== the changelog"
# Shared, unlike a spark: every member of the organisation reads the same
# log, so this is the one place here where Bob's own token is expected to
# see what Alice recorded rather than proving it can't.
CL=$(tool "$WRITE" record_change "$(args organisation_id=$OID 'description=BingAds version lift' happened_on=2026-03-02)" | text)
ok "records, and reports the date"    "$(echo "$CL" | grep -c '2026-03-02: BingAds version lift')" "1"
# The whole point of `happened_on`: Tuesday's change recorded on Thursday
# must be filed under Tuesday, not under today.
ok "…under the date it happened"      "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/changelog | j "d[0]['happened_on']")" "2026-03-02"
ok "an omitted date is your today"    "$(tool "$WRITE" record_change "$(args organisation_id=$OID 'description=Recorded with no date')" | text | grep -c "$(date -u +%F)")" "1"
ok "reading it back"                  "$(tool "$WRITE" changelog "$(args organisation_id=$OID)" | text | grep -c 'BingAds version lift')" "1"
ok "…says who recorded it"            "$(tool "$WRITE" changelog "$(args organisation_id=$OID)" | text | grep 'BingAds version lift' | grep -c "by $ALICE")" "1"
ok "a query narrows it"               "$(tool "$WRITE" changelog "$(args organisation_id=$OID query=BingAds)" | text | grep -c 'Recorded with no date')" "0"
ok "a colleague reads the same log"   "$(tool "$ADMTOK" changelog "$(args organisation_id=$OID)" | text | grep -c 'BingAds version lift')" "1"
ok "a stranger's org is 404-shaped"   "$(tool "$BOBTOK" changelog "$(args organisation_id=$OID)" | text | grep -ci 'no such organisation')" "1"
ok "a bad date is refused, and says why" \
  "$(tool "$WRITE" record_change "$(args organisation_id=$OID description=When happened_on=the-3rd)" | text | grep -ci 'YYYY-MM-DD')" "1"
ok "an empty description is refused"  "$(tool "$WRITE" record_change "$(args organisation_id=$OID 'description=   ')" | text | grep -ci 'needs a description')" "1"
ok "a read-only token can read it"    "$(tool "$MEMTOK" changelog "$(args organisation_id=$OID)" | text | grep -c 'BingAds version lift')" "1"
ok "…but cannot record one"           "$(tool "$MEMTOK" record_change "$(args organisation_id=$OID description=nope)" | text | grep -ci 'read-only')" "1"
# The kind has to reach `search` too, or the assistant can find a task by
# name and not the log entry about it.
ok "search finds a changelog entry"   "$(tool "$WRITE" search "$(args organisation_id=$OID query=BingAds)" | text | grep -c 'changelog: BingAds version lift')" "1"

echo "== the report tools"
ACTIVITY_ARGS=$(python3 -c "import json;print(json.dumps({'organisation_id':'$OID','days':7}))")
SEARCH_ARGS=$(args organisation_id=$OID query=anode)
ok "activity reports the week"  "$(tool "$WRITE" activity "$ACTIVITY_ARGS" | text | grep -ci "touched in the last 7 day")" "1"
ok "search finds by word"       "$(tool "$WRITE" search "$SEARCH_ARGS" | text | grep -c "Replace the anode")" "1"

echo "== revoking is immediate"
TOKID=$(curl -s -b /tmp/ma.jar $B/api/me/tokens | j "[t['id'] for t in d if t['name']=='Read only'][0]")
ok "revoke"                     "$(code -b /tmp/ma.jar -X DELETE $B/api/me/tokens/$TOKID)" "204"
ok "the token stops working, with a real 401" "$(mcp_status -H "Authorization: Bearer $READ")" "401"
ok "somebody else's token is not revocable" "$(code -b /tmp/mb.jar -X DELETE $B/api/me/tokens/$TOKID)" "404"
ok "last used is recorded"      "$(curl -s -b /tmp/ma.jar $B/api/me/tokens | j "any(t['last_used_at'] for t in d)")" "True"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
