#!/usr/bin/env bash
#
# Sparks: quick capture, cross-organisation, yours alone.
#
#   docker compose up -d && ./scripts/e2e-sparks.sh
#
# One thing is being proved, the same shape as e2e-notes.sh: **nobody else
# can read, edit or delete your spark.** There is no organisation in the
# URL at all here — unlike the notepad, this list is cross-organisation, so
# the test doesn't even need one.
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

ALICE=spa$S@example.com; BOB=spb$S@example.com
signup /tmp/spa.jar $ALICE; signup /tmp/spb.jar $BOB

echo "== creating and listing"
SID=$(post /tmp/spa.jar $B/api/sparks "{\"body\":\"a stray idea $S\"}" | j "d['id']")
ok "it comes back"            "$(curl -s -b /tmp/spa.jar $B/api/sparks | j "sum(1 for s in d if s['id']=='$SID')")" "1"
ok "an empty body is refused" "$(code -b /tmp/spa.jar -X POST $B/api/sparks -H 'Content-Type: application/json' -d '{"body":"   "}')" "422"

echo "== editing"
patch /tmp/spa.jar $B/api/sparks/$SID "{\"body\":\"edited $S\"}" >/dev/null
ok "the edit stuck"           "$(curl -s -b /tmp/spa.jar $B/api/sparks | j "[s['body'] for s in d if s['id']=='$SID'][0]")" "edited $S"

echo "== nobody else can read, edit or delete it — not even a 403, a 404"
BID=$(post /tmp/spb.jar $B/api/sparks "{\"body\":\"bob's own $S\"}" | j "d['id']")
ok "bob's list never shows alice's spark" \
  "$(curl -s -b /tmp/spb.jar $B/api/sparks | j "sum(1 for s in d if s['id']=='$SID')")" "0"
ok "bob editing alice's spark is 404, not 403" \
  "$(code -b /tmp/spb.jar -X PATCH $B/api/sparks/$SID -H 'Content-Type: application/json' -d '{"body":"hijack"}')" "404"
ok "bob deleting alice's spark is 404"       "$(code -b /tmp/spb.jar -X DELETE $B/api/sparks/$SID)" "404"
ok "it's untouched"           "$(curl -s -b /tmp/spa.jar $B/api/sparks | j "[s['body'] for s in d if s['id']=='$SID'][0]")" "edited $S"

echo "== deleting"
ok "deleting your own"        "$(code -b /tmp/spa.jar -X DELETE $B/api/sparks/$SID)" "204"
ok "it's gone"                "$(curl -s -b /tmp/spa.jar $B/api/sparks | j "sum(1 for s in d if s['id']=='$SID')")" "0"
ok "deleting bob's stray one" "$(code -b /tmp/spb.jar -X DELETE $B/api/sparks/$BID)" "204"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
