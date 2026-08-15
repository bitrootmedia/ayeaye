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
ok "no token is refused"        "$(tool "" organisations '{}' | text | grep -ci 'access token')" "1"
ok "a made-up token is refused" "$(tool "ayc_nonsense" organisations '{}' | text | grep -ci 'access token')" "1"

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

echo "== the report tools"
ok "activity reports the week"  "$(tool "$WRITE" activity "{\"organisation_id\":\"$OID\",\"days\":7}" | text | grep -ci "touched in the last 7 day")" "1"
ok "search finds by word"       "$(tool "$WRITE" search "{\"organisation_id\":\"$OID\",\"query\":\"anode\"}" | text | grep -c "Replace the anode")" "1"

echo "== revoking is immediate"
TOKID=$(curl -s -b /tmp/ma.jar $B/api/me/tokens | j "[t['id'] for t in d if t['name']=='Read only'][0]")
ok "revoke"                     "$(code -b /tmp/ma.jar -X DELETE $B/api/me/tokens/$TOKID)" "204"
ok "the token stops working"    "$(tool "$READ" organisations '{}' | text | grep -ci 'access token')" "1"
ok "somebody else's token is not revocable" "$(code -b /tmp/mb.jar -X DELETE $B/api/me/tokens/$TOKID)" "404"
ok "last used is recorded"      "$(curl -s -b /tmp/ma.jar $B/api/me/tokens | j "any(t['last_used_at'] for t in d)")" "True"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
