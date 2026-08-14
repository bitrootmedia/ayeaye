#!/usr/bin/env bash
#
# Phase 9e/f: the account screen and the dashboard.
#
#   docker compose up -d && ./scripts/e2e-dashboard.sh
#
# Three things worth proving through HTTP: a password change refuses without
# the current password (the whole reason the endpoint isn't just a PATCH),
# out-of-office is visible to colleagues and editable only by its owner, and
# announcements are admins-only to write and everyone's to read.
#
# Creates real accounts and leaves them behind. Dev stacks only.
set -u
B=http://localhost
S=$(date +%s)
pass=0; fail=0
ok(){ if [ "$2" = "$3" ]; then echo "  ok   $1"; pass=$((pass+1)); else echo "  FAIL $1: expected [$3] got [$2]"; fail=$((fail+1)); fi; }

signup(){ curl -s -c "$1" -o /dev/null -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  -H 'st-auth-mode: cookie' -X POST $B/api/auth/signup \
  -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$2\"},{\"id\":\"password\",\"value\":\"$3\"}]}"; }
signin(){ curl -s -c "$1" -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  -H 'st-auth-mode: cookie' -X POST $B/api/auth/signin \
  -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$2\"},{\"id\":\"password\",\"value\":\"$3\"}]}" | j "d['status']"; }
code(){ curl -s -o /dev/null -w '%{http_code}' "$@"; }
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
patch(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PATCH "$2" -d "$3"; }

TODAY=$(date +%F)
SOON=$(python3 -c "import datetime;print(datetime.date.today()+datetime.timedelta(days=3))")
LATER=$(python3 -c "import datetime;print(datetime.date.today()+datetime.timedelta(days=40))")

BOSS=da$S@example.com; CREW=dc$S@example.com
signup /tmp/da.jar $BOSS Testpass123; signup /tmp/dc.jar $CREW Testpass123
OID=$(post /tmp/da.jar $B/api/organisations "{\"name\":\"Dash $S\"}" | j "d['id']")
T=$(post /tmp/da.jar $B/api/organisations/$OID/invites "{\"email\":\"$CREW\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/dc.jar -X POST $B/api/invites/$T/accept

echo "== your own status line"
ok "starts empty"               "$(curl -s -b /tmp/dc.jar $B/api/me | j "d['status_message'] is None")" "True"
ok "set it"                     "$(patch /tmp/dc.jar $B/api/me '{"status_message":"Heads-down on the refit"}' | j "d['status_message']")" "Heads-down on the refit"
ok "clear it"                   "$(patch /tmp/dc.jar $B/api/me '{"status_message":"  "}' | j "d['status_message'] is None")" "True"

echo "== changing your password"
ok "the wrong current one is refused" \
  "$(code -b /tmp/dc.jar -H 'Content-Type: application/json' -X POST $B/api/me/password -d '{"current_password":"Wrongpass123","new_password":"Newpass456"}')" "403"
ok "a weak new one is refused" \
  "$(code -b /tmp/dc.jar -H 'Content-Type: application/json' -X POST $B/api/me/password -d '{"current_password":"Testpass123","new_password":"abc"}')" "422"
ok "the real one works"         "$(code -b /tmp/dc.jar -H 'Content-Type: application/json' -X POST $B/api/me/password -d '{"current_password":"Testpass123","new_password":"Newpass4567"}')" "204"
ok "the old password no longer signs in" "$(signin /tmp/dz.jar $CREW Testpass123)" "WRONG_CREDENTIALS_ERROR"
ok "the new one does"           "$(signin /tmp/dc.jar $CREW Newpass4567)" "OK"

echo "== out of office"
A=$(post /tmp/dc.jar $B/api/me/out-of-office "{\"starts_on\":\"$TODAY\",\"ends_on\":\"$SOON\",\"note\":\"sailing\"}")
AID=$(echo "$A" | j "d['id']")
ok "recorded"                   "$(echo "$A" | j "d['note']")" "sailing"
ok "away right now"             "$(echo "$A" | j "d['away_now']")" "True"
ok "backwards dates are refused" \
  "$(code -b /tmp/dc.jar -H 'Content-Type: application/json' -X POST $B/api/me/out-of-office -d "{\"starts_on\":\"$SOON\",\"ends_on\":\"$TODAY\"}")" "422"
# The point of recording it rather than remembering it.
ok "a colleague sees it"        "$(curl -s -b /tmp/da.jar $B/api/organisations/$OID/dashboard | j "[a['person']['email'] for a in d['away']]")" "['$CREW']"
ok "…with the note"             "$(curl -s -b /tmp/da.jar $B/api/organisations/$OID/dashboard | j "d['away'][0]['note']")" "sailing"
ok "but cannot delete it"       "$(code -b /tmp/da.jar -X DELETE $B/api/me/out-of-office/$AID)" "404"
# Far enough out to be beyond the dashboard's fortnight horizon.
post /tmp/dc.jar $B/api/me/out-of-office "{\"starts_on\":\"$LATER\",\"ends_on\":\"$LATER\"}" >/dev/null
ok "next month is not on the dashboard yet" "$(curl -s -b /tmp/da.jar $B/api/organisations/$OID/dashboard | j "len(d['away'])")" "1"
ok "…though it is in my own list"           "$(curl -s -b /tmp/dc.jar $B/api/me/out-of-office | j "len(d)")" "2"
ok "and I can remove mine"      "$(code -b /tmp/dc.jar -X DELETE $B/api/me/out-of-office/$AID)" "204"

echo "== announcements"
ok "a member may not post"      "$(code -b /tmp/dc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/announcements -d '{"body":"hello"}')" "403"
ok "the owner may"              "$(post /tmp/da.jar $B/api/organisations/$OID/announcements '{"body":"Yard closed Friday","sticky":true}' | j "d['sticky']")" "True"
ok "everyone reads it"          "$(curl -s -b /tmp/dc.jar $B/api/organisations/$OID/dashboard | j "d['announcements'][0]['body']")" "Yard closed Friday"
ok "and it says who said it"    "$(curl -s -b /tmp/dc.jar $B/api/organisations/$OID/dashboard | j "d['announcements'][0]['author']['email']")" "$BOSS"
ok "a member is told they can't post" "$(curl -s -b /tmp/dc.jar $B/api/organisations/$OID/dashboard | j "d['can_announce']")" "False"
ok "…and the owner that they can"     "$(curl -s -b /tmp/da.jar $B/api/organisations/$OID/dashboard | j "d['can_announce']")" "True"
# A noticeboard nobody prunes is a noticeboard nobody reads.
YESTERDAY=$(python3 -c "import datetime;print(datetime.date.today()-datetime.timedelta(days=1))")
post /tmp/da.jar $B/api/organisations/$OID/announcements "{\"body\":\"Old news\",\"expires_on\":\"$YESTERDAY\"}" >/dev/null
ok "an expired one is not shown" "$(curl -s -b /tmp/dc.jar $B/api/organisations/$OID/dashboard | j "sum(1 for a in d['announcements'] if a['body']=='Old news')")" "0"
NID=$(curl -s -b /tmp/da.jar $B/api/organisations/$OID/dashboard | j "d['announcements'][0]['id']")
ok "a member may not take one down" "$(code -b /tmp/dc.jar -X DELETE $B/api/organisations/$OID/announcements/$NID)" "403"
ok "the owner may"                  "$(code -b /tmp/da.jar -X DELETE $B/api/organisations/$OID/announcements/$NID)" "204"

echo "== and none of it leaks between organisations"
OTHER=$(post /tmp/dc.jar $B/api/organisations "{\"name\":\"Other $S\"}" | j "d['id']")
ok "a different org has its own board" "$(curl -s -b /tmp/dc.jar $B/api/organisations/$OTHER/dashboard | j "len(d['announcements'])")" "0"
STRANGER=ds$S@example.com
signup /tmp/ds.jar $STRANGER Testpass123
ok "a signed-in outsider gets a 404" "$(code -b /tmp/ds.jar $B/api/organisations/$OID/dashboard)" "404"
ok "…and no cookie at all is a 401"  "$(code $B/api/organisations/$OID/dashboard)" "401"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
