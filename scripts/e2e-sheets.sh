#!/usr/bin/env bash
#
# Sheets: a grid checklist under a task — rows, columns, a checkbox per cell.
#
#   docker compose up -d && ./scripts/e2e-sheets.sh
#
# A cell's existence IS the check (see models/sheet.py), so this proves the
# idempotent check/uncheck shape and that a new row starts unchecked against
# every existing column for free, alongside the same write-gate every other
# piece of shared task content (checklists, tags, files) already has.
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
put(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PUT "$2" -d "${3:-{\}}"; }

OWNER=sh-owner$S@example.com; VIEWER=sh-viewer$S@example.com
signup /tmp/sh-owner.jar $OWNER; signup /tmp/sh-viewer.jar $VIEWER

OID=$(post /tmp/sh-owner.jar $B/api/organisations "{\"name\":\"Sheets $S\"}" | j "d['id']")
T=$(post /tmp/sh-owner.jar $B/api/organisations/$OID/invites "{\"email\":\"$VIEWER\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/sh-viewer.jar -X POST $B/api/invites/$T/accept
VUID=$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$VIEWER'][0]")
TID=$(post /tmp/sh-owner.jar $B/api/organisations/$OID/tasks "{\"title\":\"Server maintenance round\"}" | j "d['id']")

echo "== creating a sheet"
SH=$(post /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets "{\"title\":\"Weekly maintenance\"}")
SHID=$(echo "$SH" | j "d['id']")
ok "returns the title"      "$(echo "$SH" | j "d['title']")" "Weekly maintenance"
ok "starts empty"           "$(echo "$SH" | j "len(d['rows'])==0 and len(d['columns'])==0 and len(d['cells'])==0")" "True"
ok "empty title -> 422"     "$(code -b /tmp/sh-owner.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/sheets -d '{"title":""}')" "422"

echo "== rows and columns"
R1=$(post /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/rows "{\"label\":\"server1\"}" | j "d['id']")
R2=$(post /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/rows "{\"label\":\"server2\"}" | j "d['id']")
C1=$(post /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/columns "{\"label\":\"Clean logs\"}" | j "d['id']")
C2=$(post /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/columns "{\"label\":\"Update apt\"}" | j "d['id']")
ok "two rows, two columns"  "$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d[0]['rows'])==2 and len(d[0]['columns'])==2")" "True"

echo "== checking a cell"
CELL=$(put /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/cells/$R1/$C1)
ok "records who checked it" "$(echo "$CELL" | j "d['checked_by']['email']")" "$OWNER"
ok "and when"               "$(echo "$CELL" | j "bool(d['checked_at'])")" "True"
ok "checking again is idempotent, same timestamp" "$(echo "$CELL" | j "d['checked_at']")" "$(put /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/cells/$R1/$C1 | j "d['checked_at']")"
ok "one checked cell so far" "$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d[0]['cells'])")" "1"

echo "== a new row starts unchecked everywhere"
R3=$(post /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/rows "{\"label\":\"server3\"}" | j "d['id']")
ok "three rows now"         "$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d[0]['rows'])")" "3"
ok "still one checked cell" "$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d[0]['cells'])")" "1"

echo "== unchecking"
ok "uncheck the cell"       "$(code -b /tmp/sh-owner.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/cells/$R1/$C1)" "204"
ok "back to zero"           "$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d[0]['cells'])")" "0"

echo "== read is enough to see, write is needed to change"
post /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/access "{\"user_id\":\"$VUID\",\"level\":\"read\"}" >/dev/null
ok "viewer sees the sheet"  "$(curl -s -b /tmp/sh-viewer.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d)")" "1"
ok "…but cannot add a sheet" "$(code -b /tmp/sh-viewer.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/sheets -d '{"title":"Nope"}')" "403"
ok "…nor add a row"          "$(code -b /tmp/sh-viewer.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/rows -d '{"label":"Nope"}')" "403"
ok "…nor add a column"       "$(code -b /tmp/sh-viewer.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/columns -d '{"label":"Nope"}')" "403"
ok "…nor check a cell"       "$(code -b /tmp/sh-viewer.jar -X PUT $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/cells/$R1/$C1)" "403"
ok "…nor reset"              "$(code -b /tmp/sh-viewer.jar -X POST $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/reset)" "403"
ok "…nor delete the sheet"   "$(code -b /tmp/sh-viewer.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/sheets/$SHID)" "403"

echo "== resetting"
put /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/cells/$R1/$C1 >/dev/null
put /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/cells/$R2/$C2 >/dev/null
ok "two cells checked"      "$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d[0]['cells'])")" "2"
ok "reset the sheet"        "$(code -b /tmp/sh-owner.jar -X POST $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/reset)" "204"
ok "back to zero"           "$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d[0]['cells'])")" "0"

echo "== renaming and removing"
ok "owner renames it"       "$(curl -s -b /tmp/sh-owner.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/tasks/$TID/sheets/$SHID -d '{"title":"Weekly maintenance (renamed)"}' | j "d['title']")" "Weekly maintenance (renamed)"
ok "remove a column"        "$(code -b /tmp/sh-owner.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/columns/$C2)" "204"
ok "one column left"        "$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d[0]['columns'])")" "1"
ok "remove a row"           "$(code -b /tmp/sh-owner.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/sheets/$SHID/rows/$R3)" "204"
ok "two rows left"          "$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d[0]['rows'])")" "2"
ok "delete the sheet"       "$(code -b /tmp/sh-owner.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/sheets/$SHID)" "204"
ok "no sheets left"         "$(curl -s -b /tmp/sh-owner.jar $B/api/organisations/$OID/tasks/$TID/sheets | j "len(d)")" "0"
ok "deleting the task takes any sheets with it" "$(code -b /tmp/sh-owner.jar -X DELETE $B/api/organisations/$OID/tasks/$TID)" "204"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
