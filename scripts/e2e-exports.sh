#!/usr/bin/env bash
#
# Data export: a ZIP per organisation or per project, one directory per task.
#
#   docker compose up -d && ./scripts/e2e-exports.sh
#
# One property matters most here, and it's the one that would leak data if
# it regressed: **an export belongs to whoever requested it, full stop —
# not even an org admin can see or download someone else's.** The zip's
# contents are the requester's own visibility snapshot, not the
# organisation's, so this is tested the same way private notes are.
# Everything else (build → ready → download, the autodelete sweep) is
# proved against the real worker and real storage.
#
# Every -d body is built into a variable before use, never a literal
# "{\"a\":\"$x\",\"b\":\"$y\"}" inline inside a "$(...)" capture — see
# e2e-mfa.sh's own comment for why: bash's brace expansion silently tears
# a multi-key literal like that in two once it's nested two quote-levels
# deep, turning one request into two malformed ones with no error at all.
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
post(){ curl -s -b "$1" -c "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
get(){ curl -s -b "$1" -c "$1" "$2"; }

# Poll until an export leaves "pending", the way a real caller would.
wait_ready(){
  jar="$1"; url="$2"
  for _ in $(seq 1 20); do
    st=$(get "$jar" "$url" | j "d['status']")
    [ "$st" != "pending" ] && { echo "$st"; return; }
    sleep 0.5
  done
  echo "timeout"
}

OWNER=eo$S@example.com; ADMIN=ea$S@example.com
signup /tmp/eo.jar $OWNER; signup /tmp/ea.jar $ADMIN

OID=$(post /tmp/eo.jar $B/api/organisations "{\"name\":\"Exports $S\"}" | j "d['id']")
BODY="{\"email\":\"$ADMIN\",\"role\":\"admin\"}"
T=$(post /tmp/eo.jar $B/api/organisations/$OID/invites "$BODY" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/ea.jar -c /tmp/ea.jar -X POST $B/api/invites/$T/accept

BODY="{\"name\":\"Website\"}"
PID=$(post /tmp/eo.jar $B/api/organisations/$OID/projects "$BODY" | j "d['id']")
BODY="{\"title\":\"Fix the header bug\",\"project_id\":\"$PID\"}"
post /tmp/eo.jar $B/api/organisations/$OID/tasks "$BODY" >/dev/null
BODY='{"title":"Loose task"}'
post /tmp/eo.jar $B/api/organisations/$OID/tasks "$BODY" >/dev/null

echo "== creating and listing"
ok "starts empty"              "$(get /tmp/eo.jar $B/api/organisations/$OID/exports | j "len(d)")" "0"
BODY='{"project_id": null}'
EXP=$(post /tmp/eo.jar $B/api/organisations/$OID/exports "$BODY")
ok "starts pending"            "$(echo "$EXP" | j "d['status']")" "pending"
EID=$(echo "$EXP" | j "d['id']")
ok "any member may trigger one" "$(code -b /tmp/ea.jar -c /tmp/ea.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/exports -d "$BODY")" "201"

echo "== building"
STATUS=$(wait_ready /tmp/eo.jar $B/api/organisations/$OID/exports/$EID)
ok "reaches ready"             "$STATUS" "ready"
# Just the owner's own — the admin's own export from the check above
# belongs to a different list entirely, per the privacy rule below.
ok "the list shows it"         "$(get /tmp/eo.jar $B/api/organisations/$OID/exports | j "len(d)")" "1"

echo "== privacy: yours only, not even an admin's"
ok "admin's own list is empty for this export" "$(get /tmp/ea.jar $B/api/organisations/$OID/exports | j "sum(1 for e in d if e['id']=='$EID')")" "0"
ok "admin cannot fetch it by id (404, not 403)" "$(code -b /tmp/ea.jar -c /tmp/ea.jar $B/api/organisations/$OID/exports/$EID)" "404"
ok "…nor download it"          "$(code -b /tmp/ea.jar -c /tmp/ea.jar $B/api/organisations/$OID/exports/$EID/download)" "404"

echo "== downloading"
DL=$(get /tmp/eo.jar $B/api/organisations/$OID/exports/$EID/download)
URL=$(echo "$DL" | j "d['download_url']")
ok "the url actually serves the zip" "$(code "$URL")" "200"
curl -s -o /tmp/e2e-export.zip "$URL"
FOLDERS=$(python3 -c "
import zipfile
z = zipfile.ZipFile('/tmp/e2e-export.zip')
names = z.namelist()
print(sum(1 for n in names if n.endswith('task.md')))
")
ok "one task.md per task, both scopes"  "$FOLDERS" "2"
ok "a No project bucket exists"  "$(python3 -c "
import zipfile
z = zipfile.ZipFile('/tmp/e2e-export.zip')
print(any(n.startswith('no-project/') for n in z.namelist()))
")" "True"
rm -f /tmp/e2e-export.zip

echo "== autodelete: downloading twice doesn't re-stamp the clock"
FIRST=$(docker compose exec -T postgres psql -U app -d app -tAc "select downloaded_at from exports where id = '$EID'")
sleep 1
get /tmp/eo.jar $B/api/organisations/$OID/exports/$EID/download >/dev/null
SECOND=$(docker compose exec -T postgres psql -U app -d app -tAc "select downloaded_at from exports where id = '$EID'")
ok "downloaded_at unchanged by a second download" "$FIRST" "$SECOND"

echo "== autodelete: the sweep actually deletes and expires"
docker compose exec -T postgres psql -U app -d app -c "update exports set downloaded_at = now() - interval '10 minutes' where id = '$EID'" >/dev/null
docker compose exec -T -e PYTHONPATH=/app/src api uv run python -c "
import asyncio
from app.tasks.exports import sweep_expired_exports
asyncio.run(sweep_expired_exports.kiq())
" >/dev/null
sleep 2
ok "flips to expired"          "$(get /tmp/eo.jar $B/api/organisations/$OID/exports/$EID | j "d['status']")" "expired"
ok "re-downloading is 410, not 404" "$(code -b /tmp/eo.jar -c /tmp/eo.jar $B/api/organisations/$OID/exports/$EID/download)" "410"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
