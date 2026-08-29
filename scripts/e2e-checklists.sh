#!/usr/bin/env bash
#
# Checklists: a quick todo list under a task, more than one allowed.
#
#   docker compose up -d && ./scripts/e2e-checklists.sh
#
# Shared task content, not a personal record — `write` gates every mutation,
# the same bar tagging and attaching a file already clear. This is the HTTP
# half; tests/test_password_policy.py-style pure functions don't apply here
# since there's no rule to isolate beyond ordinary CRUD and the access gate,
# which is what this script actually proves against real SQL and a real 403.
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
patch(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PATCH "$2" -d "$3"; }

OWNER=cl-owner$S@example.com; VIEWER=cl-viewer$S@example.com
signup /tmp/cl-owner.jar $OWNER; signup /tmp/cl-viewer.jar $VIEWER

OID=$(post /tmp/cl-owner.jar $B/api/organisations "{\"name\":\"Checklists $S\"}" | j "d['id']")
T=$(post /tmp/cl-owner.jar $B/api/organisations/$OID/invites "{\"email\":\"$VIEWER\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/cl-viewer.jar -X POST $B/api/invites/$T/accept
VUID=$(curl -s -b /tmp/cl-owner.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$VIEWER'][0]")
TID=$(post /tmp/cl-owner.jar $B/api/organisations/$OID/tasks "{\"title\":\"Ship the release\"}" | j "d['id']")

echo "== creating a checklist"
CL=$(post /tmp/cl-owner.jar $B/api/organisations/$OID/tasks/$TID/checklists "{\"title\":\"Pre-flight\"}")
CLID=$(echo "$CL" | j "d['id']")
ok "returns the title"      "$(echo "$CL" | j "d['title']")" "Pre-flight"
ok "starts with no items"   "$(echo "$CL" | j "len(d['items'])")" "0"
ok "empty title -> 422"     "$(code -b /tmp/cl-owner.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/checklists -d '{"title":""}')" "422"

echo "== items"
IT=$(post /tmp/cl-owner.jar $B/api/organisations/$OID/tasks/$TID/checklists/$CLID/items "{\"text\":\"Tag the release\"}")
ITID=$(echo "$IT" | j "d['id']")
ok "item starts undone"     "$(echo "$IT" | j "str(d['done'])")" "False"
ok "check it off"           "$(patch /tmp/cl-owner.jar $B/api/organisations/$OID/tasks/$TID/checklists/$CLID/items/$ITID '{"done":true}' | j "str(d['done'])")" "True"
ok "un-check it"            "$(patch /tmp/cl-owner.jar $B/api/organisations/$OID/tasks/$TID/checklists/$CLID/items/$ITID '{"done":false}' | j "str(d['done'])")" "False"
ok "re-word it"             "$(patch /tmp/cl-owner.jar $B/api/organisations/$OID/tasks/$TID/checklists/$CLID/items/$ITID '{"text":"Tag and sign the release"}' | j "d['text']")" "Tag and sign the release"

echo "== more than one list"
CL2ID=$(post /tmp/cl-owner.jar $B/api/organisations/$OID/tasks/$TID/checklists "{\"title\":\"Post-release\"}" | j "d['id']")
ok "two checklists on one task" "$(curl -s -b /tmp/cl-owner.jar $B/api/organisations/$OID/tasks/$TID/checklists | j "len(d)")" "2"

echo "== read is enough to see, write is needed to change"
post /tmp/cl-owner.jar $B/api/organisations/$OID/tasks/$TID/access "{\"user_id\":\"$VUID\",\"level\":\"read\"}" >/dev/null
ok "viewer sees the checklists"  "$(curl -s -b /tmp/cl-viewer.jar $B/api/organisations/$OID/tasks/$TID/checklists | j "len(d)")" "2"
ok "…but cannot add a list"      "$(code -b /tmp/cl-viewer.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/checklists -d '{"title":"Nope"}')" "403"
ok "…nor add an item"            "$(code -b /tmp/cl-viewer.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/checklists/$CLID/items -d '{"text":"Nope"}')" "403"
ok "…nor check one off"          "$(code -b /tmp/cl-viewer.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/tasks/$TID/checklists/$CLID/items/$ITID -d '{"done":true}')" "403"
ok "…nor delete the list"        "$(code -b /tmp/cl-viewer.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/checklists/$CLID)" "403"

echo "== renaming"
ok "owner renames it"       "$(patch /tmp/cl-owner.jar $B/api/organisations/$OID/tasks/$TID/checklists/$CLID '{"title":"Pre-flight (renamed)"}' | j "d['title']")" "Pre-flight (renamed)"

echo "== deleting"
ok "remove one item"        "$(code -b /tmp/cl-owner.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/checklists/$CLID/items/$ITID)" "204"
ok "delete a checklist"     "$(code -b /tmp/cl-owner.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/checklists/$CLID)" "204"
ok "only the other remains" "$(curl -s -b /tmp/cl-owner.jar $B/api/organisations/$OID/tasks/$TID/checklists | j "[c['title'] for c in d]")" "['Post-release']"
ok "deleting the task takes its checklists with it" "$(code -b /tmp/cl-owner.jar -X DELETE $B/api/organisations/$OID/tasks/$TID)" "204"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
