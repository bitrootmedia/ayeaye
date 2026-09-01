#!/usr/bin/env bash
#
# The day planner: a pool of open tasks, five buckets, one entry per task per
# person, and the admin escape hatch — same shape as time entries, not notes.
#
#   docker compose up -d && ./scripts/e2e-planner.sh
#
# Four accounts:
#
#   ALICE  organisation owner
#   BOB    an organisation admin — the one who may act on someone else's plan
#   CAROL  a plain member — the planner under test
#   DAVE   a plain member — proves a non-admin gets nowhere near Carol's, and
#          supplies the task Carol can never legitimately place
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
put(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PUT "$2" -d "$3"; }
patch(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PATCH "$2" -d "$3"; }

ALICE=pa$S@example.com; BOB=pb$S@example.com; CAROL=pc$S@example.com; DAVE=pd$S@example.com
signup /tmp/pa.jar $ALICE; signup /tmp/pb.jar $BOB; signup /tmp/pc.jar $CAROL; signup /tmp/pd.jar $DAVE

OID=$(post /tmp/pa.jar $B/api/organisations "{\"name\":\"Planner $S\"}" | j "d['id']")
join(){ T=$(post /tmp/pa.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/pb.jar $BOB; join /tmp/pc.jar $CAROL; join /tmp/pd.jar $DAVE

BOB_MID=$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$BOB'][0]")
patch /tmp/pa.jar $B/api/organisations/$OID/members/$BOB_MID '{"role":"admin"}' >/dev/null
CAROL_ID=$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$CAROL'][0]")

planner(){ curl -s -b "$1" "$B/api/organisations/$OID/planner${2:-}"; }
plan_count(){ planner "$1" "$2" | j "sum(len(v) for v in d['buckets'].values())"; }
in_pool(){ planner "$1" "$2" | j "sum(1 for t in d['pool'] if t['id']=='$3')"; }
in_bucket(){ planner "$1" "$2" | j "sum(1 for t in d['buckets'].get('$3', []) if t['task']['id']=='$4')"; }

echo "== the pool"
TID=$(post /tmp/pc.jar $B/api/organisations/$OID/tasks "{\"title\":\"Order the antifoul $S\"}" | j "d['id']")
ok "a new open task lands in Carol's pool" "$(in_pool /tmp/pc.jar "" "$TID")" "1"

echo "== placing, moving, never duplicating"
ok "place into today"           "$(put /tmp/pc.jar $B/api/organisations/$OID/planner/$TID '{"bucket":"today","position":1000}' | j "d['bucket']")" "today"
ok "…and it leaves the pool"    "$(in_pool /tmp/pc.jar "" "$TID")" "0"
ok "…and sits in today"         "$(in_bucket /tmp/pc.jar "" "today" "$TID")" "1"
ok "move to tomorrow"           "$(put /tmp/pc.jar $B/api/organisations/$OID/planner/$TID '{"bucket":"tomorrow","position":500}' | j "d['bucket']")" "tomorrow"
ok "…gone from today"           "$(in_bucket /tmp/pc.jar "" "today" "$TID")" "0"
ok "…exactly one entry, total"  "$(plan_count /tmp/pc.jar "")" "1"

echo "== position is optional — appends to the end of the bucket"
TID2=$(post /tmp/pc.jar $B/api/organisations/$OID/tasks "{\"title\":\"Second in bucket $S\"}" | j "d['id']")
FIRST_POS=$(put /tmp/pc.jar $B/api/organisations/$OID/planner/$TID '{"bucket":"someday"}' | j "d['position']")
SECOND_POS=$(put /tmp/pc.jar $B/api/organisations/$OID/planner/$TID2 '{"bucket":"someday"}' | j "d['position']")
ok "the second placement lands after the first" "$([ "$SECOND_POS" -gt "$FIRST_POS" ] && echo yes)" "yes"
curl -s -o /dev/null -b /tmp/pc.jar -X DELETE $B/api/organisations/$OID/planner/$TID2

echo "== a task's own screen shows the caller's bucket, and only the caller's"
ok "Carol's own view of the task shows the bucket" \
   "$(curl -s -b /tmp/pc.jar $B/api/organisations/$OID/tasks/$TID | j "d['planner_bucket']")" "someday"
ok "the list view doesn't pay for it (always null there)" \
   "$(curl -s -b /tmp/pc.jar "$B/api/organisations/$OID/tasks?limit=5" | j "all(t['planner_bucket'] is None for t in d)")" "True"
curl -s -o /dev/null -b /tmp/pc.jar -X DELETE $B/api/organisations/$OID/planner/$TID
ok "unplanning clears it back to null" \
   "$(curl -s -b /tmp/pc.jar $B/api/organisations/$OID/tasks/$TID | j "d['planner_bucket']")" "None"

echo "== removing returns it to the pool"
ok "unplan"                     "$(code -b /tmp/pc.jar -X DELETE $B/api/organisations/$OID/planner/$TID)" "204"
ok "back in the pool"           "$(in_pool /tmp/pc.jar "" "$TID")" "1"
ok "no buckets left"            "$(plan_count /tmp/pc.jar "")" "0"
ok "unplanning again is a no-op, not a 404" "$(code -b /tmp/pc.jar -X DELETE $B/api/organisations/$OID/planner/$TID)" "204"

put /tmp/pc.jar $B/api/organisations/$OID/planner/$TID '{"bucket":"today","position":1000}' >/dev/null

echo "== a plain member is nowhere near someone else's planner"
ok "Dave cannot view Carol's"   "$(code -b /tmp/pd.jar "$B/api/organisations/$OID/planner?user_id=$CAROL_ID")" "403"
ok "Dave cannot place into it"  "$(code -b /tmp/pd.jar -H 'Content-Type: application/json' -X PUT "$B/api/organisations/$OID/planner/$TID?user_id=$CAROL_ID" -d '{"bucket":"someday","position":1}')" "403"
ok "Dave cannot unplan from it" "$(code -b /tmp/pd.jar -X DELETE "$B/api/organisations/$OID/planner/$TID?user_id=$CAROL_ID")" "403"

echo "== an organisation admin may act on Carol's planner"
ok "Bob can view it"            "$(code -b /tmp/pb.jar "$B/api/organisations/$OID/planner?user_id=$CAROL_ID")" "200"
ok "Bob moves her task"         "$(put /tmp/pb.jar "$B/api/organisations/$OID/planner/$TID?user_id=$CAROL_ID" '{"bucket":"next_week","position":1000}' | j "d['bucket']")" "next_week"
ok "…and it landed on HER row"  "$(in_bucket /tmp/pc.jar "" "next_week" "$TID")" "1"

echo "== that override does not merge the two people's plans"
DAVE_LOOSE=$(post /tmp/pd.jar $B/api/organisations/$OID/tasks "{\"title\":\"Dave private work $S\"}" | j "d['id']")
put /tmp/pb.jar $B/api/organisations/$OID/planner/$DAVE_LOOSE '{"bucket":"today","position":1000}' >/dev/null
ok "Bob's own plan has it"      "$(in_bucket /tmp/pb.jar "" "today" "$DAVE_LOOSE")" "1"
ok "Carol's plan does not"      "$(in_bucket /tmp/pc.jar "" "today" "$DAVE_LOOSE")" "0"

echo "== an admin's override cannot see past the target's own access"
ok "loose task is invisible to Carol" "$(code -b /tmp/pc.jar $B/api/organisations/$OID/tasks/$DAVE_LOOSE)" "404"
ok "so Bob can't place it into HER planner either" \
  "$(code -b /tmp/pb.jar -H 'Content-Type: application/json' -X PUT "$B/api/organisations/$OID/planner/$DAVE_LOOSE?user_id=$CAROL_ID" -d '{"bucket":"today","position":1}')" "404"

echo "== a task Carol owns: hiding it removes nobody's view of HER OWN bucket"
post /tmp/pc.jar $B/api/organisations/$OID/tasks/$TID/hidden '{"hidden":true}' >/dev/null
# Carol owns this one, and hiding is the one place access is SUBTRACTED for
# everyone except the owner. Bob's admin override renders exactly what Carol
# herself would see — and Carol, as owner, still sees her own hidden task.
# This is not a leak: it's Carol's own access, surfaced through Bob's view.
ok "still in Carol's own view"       "$(in_bucket /tmp/pc.jar "" "next_week" "$TID")" "1"
ok "…and in Bob's view of it, too"   "$(in_bucket /tmp/pb.jar "?user_id=$CAROL_ID" "next_week" "$TID")" "1"
post /tmp/pc.jar $B/api/organisations/$OID/tasks/$TID/hidden '{"hidden":false}' >/dev/null

echo "== a task Carol does NOT own: hiding it removes HER access, and Bob's view of her planner follows"
# This is the real regression case: Dave owns it, shares it with Carol, Carol
# plans it, then Dave hides it. Carol is not the owner, so the short-circuit
# actually fires — she loses access, and so must Bob's view of HER planner,
# even though Bob is an admin and could see the task directly himself.
SHARED=$(post /tmp/pd.jar $B/api/organisations/$OID/tasks "{\"title\":\"Dave's task, shared $S\"}" | j "d['id']")
post /tmp/pd.jar $B/api/organisations/$OID/tasks/$SHARED/access "{\"user_id\":\"$CAROL_ID\",\"level\":\"write\"}" >/dev/null
put /tmp/pc.jar $B/api/organisations/$OID/planner/$SHARED '{"bucket":"someday","position":1000}' >/dev/null
ok "it's in Carol's someday"          "$(in_bucket /tmp/pc.jar "" "someday" "$SHARED")" "1"
post /tmp/pd.jar $B/api/organisations/$OID/tasks/$SHARED/hidden '{"hidden":true}' >/dev/null
ok "gone from Carol's own view"       "$(in_bucket /tmp/pc.jar "" "someday" "$SHARED")" "0"
ok "…and from Bob's view of HER planner, though Bob could see it himself" \
  "$(in_bucket /tmp/pb.jar "?user_id=$CAROL_ID" "someday" "$SHARED")" "0"
post /tmp/pd.jar $B/api/organisations/$OID/tasks/$SHARED/hidden '{"hidden":false}' >/dev/null
ok "un-hiding restores it for both"   "$(in_bucket /tmp/pc.jar "" "someday" "$SHARED")" "1"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
