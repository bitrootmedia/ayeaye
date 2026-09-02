#!/usr/bin/env bash
#
# Working hours: a weekly pattern, yours to set and any colleague's to see.
#
#   docker compose up -d && ./scripts/e2e-working-hours.sh
#
# Two things are being proved: setting/clearing a cell is idempotent and
# bounded (0-6, 0-23), and visibility is scoped to a shared organisation —
# not private, but not public either. See services/working_hours.py.
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

ALICE=wha$S@example.com; BOB=whb$S@example.com; CAROL=whc$S@example.com
signup /tmp/wha.jar $ALICE; signup /tmp/whb.jar $BOB; signup /tmp/whc.jar $CAROL

OID=$(post /tmp/wha.jar $B/api/organisations "{\"name\":\"Working Hours $S\"}" | j "d['id']")
join(){ T=$(post /tmp/wha.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/whb.jar $BOB
# Carol never joins — she's the stranger this script uses for the negative case.

ALICE_ID=$(curl -s -b /tmp/wha.jar $B/api/me | j "d['id']")

echo "== setting and clearing a cell"
ok "marking an hour"          "$(code -b /tmp/wha.jar -X PUT $B/api/me/working-hours/0/9)" "204"
ok "marking it again is a no-op, not an error" \
                               "$(code -b /tmp/wha.jar -X PUT $B/api/me/working-hours/0/9)" "204"
ok "it shows up once"         "$(curl -s -b /tmp/wha.jar $B/api/me/working-hours | j "len(d['cells'])")" "1"
ok "clearing an hour"         "$(code -b /tmp/wha.jar -X DELETE $B/api/me/working-hours/0/9)" "204"
ok "clearing an unset hour is still a no-op" \
                               "$(code -b /tmp/wha.jar -X DELETE $B/api/me/working-hours/0/9)" "204"
ok "grid is empty again"      "$(curl -s -b /tmp/wha.jar $B/api/me/working-hours | j "len(d['cells'])")" "0"

echo "== the grid is bounded"
ok "weekday 7 is refused"     "$(code -b /tmp/wha.jar -X PUT $B/api/me/working-hours/7/0)" "422"
ok "hour 24 is refused"       "$(code -b /tmp/wha.jar -X PUT $B/api/me/working-hours/0/24)" "422"
ok "negative weekday is refused" "$(code -b /tmp/wha.jar -X PUT $B/api/me/working-hours/-1/0)" "422"

echo "== visible to a shared organisation, not to a stranger"
curl -s -b /tmp/wha.jar -X PUT $B/api/me/working-hours/2/14 -o /dev/null
ok "a colleague sees the cell" \
  "$(curl -s -b /tmp/whb.jar $B/api/organisations/$OID/members/$ALICE_ID/working-hours | j "(d['cells'][0]['weekday'], d['cells'][0]['hour'])")" \
  "(2, 14)"
ok "a stranger with no shared org gets 404" \
  "$(code -b /tmp/whc.jar $B/api/organisations/$OID/members/$ALICE_ID/working-hours)" "404"
ok "a made-up user id in a real org is also 404" \
  "$(code -b /tmp/whb.jar $B/api/organisations/$OID/members/00000000-0000-7000-8000-000000000000/working-hours)" "404"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
