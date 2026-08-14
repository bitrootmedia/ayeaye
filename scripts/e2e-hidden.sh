#!/usr/bin/env bash
#
# Phase 9a: tasks that only their owner can see.
#
#   docker compose up -d && ./scripts/e2e-hidden.sh
#
# `tests/test_task_rules.py` proves the Python half of the rule over the full
# grid with no database. This proves the **SQL** half — that the short-circuit
# in `task_level_expression` reaches every statement that composes it: the
# board, the single fetch, search, and the time rollups. Those are four
# different queries and a rule that only lands in three of them is a leak.
#
# Four accounts, because the interesting denials are all about somebody who
# would otherwise have access:
#
#   ALICE  organisation owner, and an org ADMIN — the deliberate hole
#   BOB    a plain member with a write grant on the project
#   CAROL  a plain member named action-required
#   DAVE   a plain member with a direct grant on the task itself
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

ALICE=ha$S@example.com; BOB=hb$S@example.com; CAROL=hc$S@example.com; DAVE=hd$S@example.com
signup /tmp/ha.jar $ALICE; signup /tmp/hb.jar $BOB
signup /tmp/hc.jar $CAROL; signup /tmp/hd.jar $DAVE

OID=$(post /tmp/ha.jar $B/api/organisations "{\"name\":\"Hidden $S\"}" | j "d['id']")
join(){ T=$(post /tmp/ha.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/hb.jar $BOB; join /tmp/hc.jar $CAROL; join /tmp/hd.jar $DAVE
uid(){ curl -s -b /tmp/ha.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$1'][0]"; }
BOB_ID=$(uid $BOB); CAROL_ID=$(uid $CAROL); DAVE_ID=$(uid $DAVE)

# Bob owns the project and the task, so hiding is his to do. Alice, the
# organisation owner, is the one who must *stop* seeing it.
PID=$(post /tmp/hb.jar $B/api/organisations/$OID/projects '{"name":"Refit"}' | j "d['id']")
TID=$(post /tmp/hb.jar $B/api/organisations/$OID/tasks "{\"title\":\"Quiet work $S\",\"project_id\":\"$PID\"}" | j "d['id']")
post /tmp/hb.jar $B/api/organisations/$OID/projects/$PID/access "{\"user_id\":\"$CAROL_ID\",\"level\":\"write\"}" >/dev/null
post /tmp/hb.jar $B/api/organisations/$OID/tasks/$TID/access "{\"user_id\":\"$DAVE_ID\",\"level\":\"read\"}" >/dev/null

get(){ code -b "$1" $B/api/organisations/$OID/tasks/$TID; }
board(){ curl -s -b "$1" $B/api/organisations/$OID/tasks | j "sum(1 for t in d if t['id']=='$TID')"; }
find_it(){ curl -s -b "$1" "$B/api/organisations/$OID/search?q=Quiet+work+$S" | j "sum(1 for h in d['hits'] if h['id']=='$TID')"; }

echo "== before hiding, everyone with a route in can see it"
ok "the owner"                  "$(get /tmp/hb.jar)" "200"
ok "the org admin"              "$(get /tmp/ha.jar)" "200"
ok "a project grantee"          "$(get /tmp/hc.jar)" "200"
ok "a task grantee"             "$(get /tmp/hd.jar)" "200"
ok "and it's on their board"    "$(board /tmp/hc.jar)" "1"
ok "and in their search"        "$(find_it /tmp/hd.jar)" "1"

echo "== hide it"
ok "the owner may"              "$(post /tmp/hb.jar $B/api/organisations/$OID/tasks/$TID/hidden '{"hidden":true}' | j "d['is_hidden']")" "True"
ok "recorded in the history"    "$(curl -s -b /tmp/hb.jar $B/api/organisations/$OID/tasks/$TID/events | j "sum(1 for e in d if e['kind']=='hidden')")" "1"

echo "== now only the owner, in every statement that resolves access"
ok "the owner still sees it"    "$(get /tmp/hb.jar)" "200"
ok "the ORG ADMIN cannot"       "$(get /tmp/ha.jar)" "404"
ok "the project grantee cannot" "$(get /tmp/hc.jar)" "404"
ok "the task grantee cannot"    "$(get /tmp/hd.jar)" "404"
ok "gone from the admin's board"    "$(board /tmp/ha.jar)" "0"
ok "gone from the grantee's board"  "$(board /tmp/hc.jar)" "0"
ok "gone from the admin's search"   "$(find_it /tmp/ha.jar)" "0"
ok "gone from the grantee's search" "$(find_it /tmp/hd.jar)" "0"
ok "still on the OWNER's board"     "$(board /tmp/hb.jar)" "1"
ok "still in the OWNER's search"    "$(find_it /tmp/hb.jar)" "1"

echo "== the grants are suspended, not deleted"
ok "the task grant is still there"  "$(curl -s -b /tmp/hb.jar $B/api/organisations/$OID/tasks/$TID/access | j "sum(1 for g in d['grants'] if g['user'] and g['user']['id']=='$DAVE_ID')")" "1"
post /tmp/hb.jar $B/api/organisations/$OID/tasks/$TID/hidden '{"hidden":false}' >/dev/null
ok "un-hiding restores them all"    "$(get /tmp/hd.jar)" "200"
ok "…including for the org admin"   "$(get /tmp/ha.jar)" "200"

echo "== who may hide"
ok "an org admin may NOT hide someone else's task" \
  "$(code -b /tmp/ha.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/hidden -d '{"hidden":true}')" "403"
ok "nor may a write grantee"    "$(code -b /tmp/hc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/hidden -d '{"hidden":true}')" "403"

echo "== action-required and hiding are mutually exclusive"
patch /tmp/hb.jar $B/api/organisations/$OID/tasks/$TID "{\"action_required_user_id\":\"$CAROL_ID\"}" >/dev/null
ok "can't hide while someone must act" \
  "$(code -b /tmp/hb.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/hidden -d '{"hidden":true}')" "409"
patch /tmp/hb.jar $B/api/organisations/$OID/tasks/$TID '{"action_required_user_id":null}' >/dev/null
post /tmp/hb.jar $B/api/organisations/$OID/tasks/$TID/hidden '{"hidden":true}' >/dev/null
ok "…and can't ask once hidden" \
  "$(code -b /tmp/hb.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/tasks/$TID -d "{\"action_required_user_id\":\"$CAROL_ID\"}")" "409"

echo "== your own logged time survives someone hiding the task"
# Carol logs an hour while she can still see it, then Bob hides it. Her hours
# are a record of what SHE did — they must not evaporate from her own timesheet
# because the owner changed the task's visibility.
post /tmp/hb.jar $B/api/organisations/$OID/tasks/$TID/hidden '{"hidden":false}' >/dev/null
post /tmp/hc.jar $B/api/organisations/$OID/tasks/$TID/time '{"minutes":60,"note":"survey"}' >/dev/null
BEFORE=$(curl -s -b /tmp/hc.jar $B/api/organisations/$OID/time/summary | j "d['total_seconds']")
post /tmp/hb.jar $B/api/organisations/$OID/tasks/$TID/hidden '{"hidden":true}' >/dev/null
ok "her total is unchanged"     "$(curl -s -b /tmp/hc.jar $B/api/organisations/$OID/time/summary | j "d['total_seconds']")" "$BEFORE"
ok "but she still can't open it" "$(get /tmp/hc.jar)" "404"
ok "and it's not in the admin's rollup" \
  "$(curl -s -b /tmp/ha.jar $B/api/organisations/$OID/time/summary | j "sum(1 for r in d['by_task'] if r['id']=='$TID')")" "0"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
