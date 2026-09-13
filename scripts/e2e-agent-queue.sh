#!/usr/bin/env bash
#
# The agent queue: a planner somebody else arranged, read back over MCP.
#
#   docker compose up -d && ./scripts/e2e-agent-queue.sh
#
# There is no queue table in this product. Work is handed to an assistant by
# arranging its planner — a `planner_entries` row is what "queued" means, and
# its bucket and position are the order — so what this proves is that the
# board an admin drags into shape and what `next_task` hands back are the same
# list, read the same way round.
#
# The whole loop, in the order an assistant actually walks it: read the top,
# say what you did, take it off your board, hand it back. That last step is
# the one with a trap in it, and the last three assertions are about it.
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
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
put(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PUT "$2" -d "$3"; }

# Stateless transport, no handshake — see scripts/e2e-mcp.sh for why this is
# testable with curl at all. Every payload is assembled by python: the
# escaped-quote form silently mangles the calls with the most arguments, and
# bash 3.2 (what macOS ships) mis-splits a `\"` nested inside `$(...)`, which
# turns a broken assertion into a passing one.
rpc(){ # $1 token  $2 method  $3 params-json
  python3 -c "import json,sys; print(json.dumps({'jsonrpc':'2.0','id':1,'method':sys.argv[1],'params':json.loads(sys.argv[2])}))" "$2" "$3" > /tmp/aq-req.json
  curl -s -X POST $B/mcp \
    -H "Authorization: Bearer $1" -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'MCP-Protocol-Version: 2025-06-18' \
    --data-binary @/tmp/aq-req.json
}
args(){ python3 -c "
import json,sys
print(json.dumps(dict(p.split('=',1) for p in sys.argv[1:])))
" "$@"; }
tool(){ # $1 token  $2 tool-name  $3 arguments-json
  python3 -c "import json,sys; print(json.dumps({'name':sys.argv[1],'arguments':json.loads(sys.argv[2])}))" "$2" "$3" > /tmp/aq-args.json
  rpc "$1" tools/call "$(cat /tmp/aq-args.json)"
}
text(){ python3 -c "
import json,sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except ValueError:
    print('UNPARSEABLE:', raw[:300]); sys.exit(0)
r = d.get('result') or {}
c = r.get('content') or []
print((c[0].get('text','') if c else json.dumps(d))[:6000])
"; }
# Which of two titles `next_task` actually returned. Printing the answer
# rather than grepping for one of them, so a call that returned *neither*
# fails loudly instead of quietly satisfying a "0 matches" check.
head_of_queue(){ tool "$1" next_task "$(args organisation_id=$OID)" | text | head -3; }

echo "== two people: the one who queues, and the one who works"
HUMAN=aq$S@example.com; AGENT=ag$S@example.com
signup /tmp/aq.jar $HUMAN; signup /tmp/ag.jar $AGENT
OID=$(post /tmp/aq.jar $B/api/organisations "{\"name\":\"Queue $S\"}" | j "d['id']")
INV=$(post /tmp/aq.jar $B/api/organisations/$OID/invites "{\"email\":\"$AGENT\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/ag.jar -X POST $B/api/invites/$INV/accept
AGENT_ID=$(curl -s -b /tmp/aq.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$AGENT'][0]")
WRITE=$(post /tmp/ag.jar $B/api/me/tokens '{"name":"Claude","scope":"write"}' | j "d['token']")
READONLY=$(post /tmp/ag.jar $B/api/me/tokens '{"name":"Claude, reading","scope":"read"}' | j "d['token']")
ok "the agent joined"  "$(tool "$WRITE" organisations '{}' | text | grep -c "$OID")" "1"

echo "== an empty planner says so, rather than 'nothing to do'"
EMPTY=$(tool "$WRITE" next_task "$(args organisation_id=$OID)" | text)
ok "next_task on an empty board"  "$(echo "$EMPTY" | grep -ci 'nothing on your planner')" "1"

echo "== the human queues three tasks onto the agent's board"
# Each is action-required on the agent, which is what grants it write on a
# loose task it has no project route into — the six routes in.
mk(){ post /tmp/aq.jar $B/api/organisations/$OID/tasks "{\"title\":\"$1\",\"action_required_user_id\":\"$AGENT_ID\"}" | j "d['id']"; }
FIRST=$(mk "Rotate the staging credentials")
SECOND=$(mk "Backfill the missing invoices")
LATER=$(mk "Rewrite the onboarding doc")
plan(){ put /tmp/aq.jar "$B/api/organisations/$OID/planner/$1?user_id=$AGENT_ID" "{\"bucket\":\"$2\",\"position\":$3}" >/dev/null; }
# Deliberately out of creation order: FIRST is queued second and still comes
# back first, because position is the order and nothing else is.
plan "$SECOND" today 2000
plan "$FIRST"  today 1000
plan "$LATER"  tomorrow 1000
ok "the agent's own board has all three" \
  "$(curl -s -b /tmp/ag.jar $B/api/organisations/$OID/planner | j "sum(len(v) for v in d['buckets'].values())")" "3"

echo "== next_task is the top of that board, not the newest task"
HEAD=$(head_of_queue "$WRITE")
ok "position decides, not creation order" "$(echo "$HEAD" | grep -c 'Rotate the staging credentials')" "1"
ok "…and it says which bucket it came from" "$(echo "$HEAD" | grep -c 'Next on your planner (today)')" "1"

echo "== the buckets rank by urgency, not by spelling"
# `bucket` is a string column: ordered alphabetically it reads next_week,
# someday, this_week, today, tomorrow — so a Someday task would be handed
# back ahead of everything in Today, silently and forever. BUCKET_RANK is
# the only place that order is written down, and this is what pins it.
SOMEDAY=$(mk "Look into the log volume one day")
plan "$SOMEDAY" someday 1
ok "someday does not jump the queue" "$(head_of_queue "$WRITE" | grep -c 'Rotate the staging credentials')" "1"

echo "== my_planner is the whole board, in the same order"
BOARD=$(tool "$WRITE" my_planner "$(args organisation_id=$OID)" | text)
ok "today is listed"        "$(echo "$BOARD" | grep -c '^today (2):')" "1"
ok "…before tomorrow"       "$(echo "$BOARD" | awk '/^today/{t=NR} /^tomorrow/{m=NR} END{print (t>0 && m>t) ? 1 : 0}')" "1"
ok "…and someday last"      "$(echo "$BOARD" | awk '/^tomorrow/{m=NR} /^someday/{s=NR} END{print (m>0 && s>m) ? 1 : 0}')" "1"
# An empty board otherwise reads as an empty organisation. Alice owns a task
# nobody queued, and the agent can see it — being asked to act is a route in.
UNPLANNED=$(mk "Not queued for anybody")
ok "unplanned work is counted, not hidden" \
  "$(tool "$WRITE" my_planner "$(args organisation_id=$OID)" | text | grep -c 'you have not planned')" "1"

echo "== it does not step over work it already started"
STARTED=$(args organisation_id=$OID task_id=$FIRST status=in_progress)
tool "$WRITE" update_task "$STARTED" >/dev/null
RESUMED=$(head_of_queue "$WRITE")
ok "an in-progress task is still the next one"  "$(echo "$RESUMED" | grep -c 'Rotate the staging credentials')" "1"
ok "…and the status is on the face of it"       "$(tool "$WRITE" next_task "$(args organisation_id=$OID)" | text | grep -c 'status=in_progress')" "1"

echo "== planning something yourself"
SELF=$(args organisation_id=$OID task_id=$UNPLANNED bucket=today)
ok "plan_task puts it on your board"  "$(tool "$WRITE" plan_task "$SELF" | text | grep -c 'Not queued for anybody')" "1"
ok "…and the board agrees" \
  "$(curl -s -b /tmp/ag.jar $B/api/organisations/$OID/planner | j "sum(1 for e in d['buckets']['today'] if e['task']['id']=='$UNPLANNED')")" "1"
BADBUCKET=$(args organisation_id=$OID task_id=$UNPLANNED bucket=eventually)
ok "a bucket that isn't one is refused" "$(tool "$WRITE" plan_task "$BADBUCKET" | text | grep -ci 'not a planner bucket')" "1"
ok "a read-only credential cannot plan" "$(tool "$READONLY" plan_task "$SELF" | text | grep -ci 'read-only')" "1"
ok "…but can read the queue"            "$(head_of_queue "$READONLY" | grep -c 'Rotate the staging credentials')" "1"

echo "== a planner reaches nothing its owner cannot see"
# A stranger's own task, and a member's private one. Planning either would be
# a second access path; `place` resolves visibility against the target, so it
# is the ordinary 404.
STRANGER=$(mk "irrelevant")   # same org, but the next one is not
PRIVATE=$(post /tmp/aq.jar $B/api/organisations/$OID/tasks '{"title":"The human keeps this one"}' | j "d['id']")
curl -s -o /dev/null -b /tmp/aq.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$PRIVATE/hidden -d '{"hidden":true}'
HIDDEN=$(args organisation_id=$OID task_id=$PRIVATE bucket=today)
ok "a hidden task cannot be planned"  "$(tool "$WRITE" plan_task "$HIDDEN" | text | grep -ci 'not found')" "1"
NONSENSE=$(args organisation_id=$OID task_id=not-a-uuid bucket=today)
ok "a malformed id refuses, and says so" "$(tool "$WRITE" plan_task "$NONSENSE" | text | grep -ci "no such task")" "1"

echo "== somebody else's board is never reachable from here"
# An admin arranges a colleague's planner from the web app, deliberately.
# Over MCP there is no `user_id` to pass at all, and the agent's own token
# must not be able to read what the human planned for themselves.
put /tmp/aq.jar "$B/api/organisations/$OID/planner/$PRIVATE" '{"bucket":"today","position":1}' >/dev/null
ok "the human planned it for themselves" \
  "$(curl -s -b /tmp/aq.jar $B/api/organisations/$OID/planner | j "sum(1 for e in d['buckets']['today'] if e['task']['id']=='$PRIVATE')")" "1"
ok "…and the agent's board does not show it" \
  "$(tool "$WRITE" my_planner "$(args organisation_id=$OID)" | text | grep -c 'The human keeps this one')" "0"

echo "== finishing: comment, unplan, hand back — in that order"
SAID=$(args organisation_id=$OID task_id=$FIRST "body=Rotated both keys; the old pair is revoked.")
ok "the agent records what it did"  "$(tool "$WRITE" comment "$SAID" | text | grep -c 'Posted')" "1"
CLEAR=$(args organisation_id=$OID task_id=$FIRST)
ok "and takes it off its own board" "$(tool "$WRITE" unplan_task "$CLEAR" | text | grep -c 'Off your planner')" "1"
ok "unplanning it twice is a quiet success, not an error" \
  "$(tool "$WRITE" unplan_task "$CLEAR" | text | grep -c 'Off your planner')" "1"
ok "the queue has moved on"         "$(head_of_queue "$WRITE" | grep -c 'Backfill the missing invoices')" "1"
# The trap. Action-required was the agent's *only* route into a loose task,
# so handing the work back takes the task away in the same call that reports
# success — which is why unplanning has to happen first, and why unplan_task
# deliberately checks no access of its own.
HANDBACK=$(args organisation_id=$OID task_id=$FIRST status=review action_required_email=$HUMAN)
ok "handing it back succeeds"       "$(tool "$WRITE" update_task "$HANDBACK" | text | grep -c 'Updated')" "1"
ok "…and the task is gone from the agent"  "$(tool "$WRITE" task "$CLEAR" | text | grep -ci 'no such task')" "1"
ok "…while the human has it back in review" \
  "$(curl -s -b /tmp/aq.jar $B/api/organisations/$OID/tasks/$FIRST | j "d['status']")" "review"
# `via` is the token's own name — attribution, not authorship. It is what
# lets the human tell an assistant's note from one a colleague typed, and
# what lets the assistant tell its own earlier notes apart on the way back in.
ok "…with the agent's note on it" \
  "$(curl -s -b /tmp/aq.jar $B/api/organisations/$OID/tasks/$FIRST/comments | j "sum(1 for m in d['messages'] if 'Rotated both keys' in m['body'])")" "1"
ok "…attributed to what posted it" \
  "$(curl -s -b /tmp/aq.jar $B/api/organisations/$OID/tasks/$FIRST/comments | j "[m['via'] for m in d['messages'] if 'Rotated both keys' in m['body']][0]")" "Claude"
# Closing is the owner's, and nothing here did it.
ok "and nothing was closed"         "$(curl -s -b /tmp/aq.jar $B/api/organisations/$OID/tasks/$FIRST | j "d['is_open']")" "True"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
