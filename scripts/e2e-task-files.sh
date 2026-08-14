#!/usr/bin/env bash
#
# Phase 8: task priority, and the unified Files panel.
#
#   docker compose up -d && ./scripts/e2e-task-files.sh
#
# The Files panel is the interesting half: it has to show files added to the
# task AND files posted in its comments, without showing anything staged but
# never sent, and without leaking either to someone who can't see the task.
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

A=pa$S@example.com; BB=pb$S@example.com
signup /tmp/pa.jar $A; signup /tmp/pb.jar $BB

OID=$(post /tmp/pa.jar $B/api/organisations "{\"name\":\"Prio $S\"}" | j "d['id']")
T=$(post /tmp/pa.jar $B/api/organisations/$OID/invites "{\"email\":\"$BB\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/pb.jar -X POST $B/api/invites/$T/accept
BUID=$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$BB'][0]")

python3 -c "
import base64,sys
sys.stdout.buffer.write(base64.b64decode(
 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='))
" > /tmp/dot.png

echo "== priority"
TID=$(post /tmp/pa.jar $B/api/organisations/$OID/tasks '{"title":"Fix the leak"}' | j "d['id']")
ok "defaults to normal"         "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID | j "d['priority']")" "normal"
ok "set to critical"            "$(patch /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID '{"priority":"critical"}' | j "d['priority']")" "critical"
ok "recorded in the history"    "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/events | j "[e['data'] for e in d if e['kind']=='priority_changed'][0]['now']")" "critical"
ok "set at creation"            "$(post /tmp/pa.jar $B/api/organisations/$OID/tasks '{"title":"Later","priority":"very_low"}' | j "d['priority']")" "very_low"
ok "a bogus value is refused"   "$(code -b /tmp/pa.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/tasks/$TID -d '{"priority":"panic"}')" "422"
ok "setting the same value writes no event" "$(patch /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID '{"priority":"critical"}' >/dev/null; curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/events | j "sum(1 for e in d if e['kind']=='priority_changed')")" "1"

echo "== the board leads with the most urgent"
for p in low urgent normal critical very_low high; do
  post /tmp/pa.jar $B/api/organisations/$OID/tasks "{\"title\":\"P-$p\",\"priority\":\"$p\"}" >/dev/null
done
ORDER=$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks | j "[t['priority'] for t in d if t['title'].startswith('P-')]")
ok "ordered by urgency"         "$ORDER" "['critical', 'urgent', 'high', 'normal', 'low', 'very_low']"

echo "== files on the task"
TICKET=$(post /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files '{"filename":"plan.png","content_type":"image/png"}')
AID=$(echo "$TICKET" | j "d['attachment']['id']")
ok "the key is under tasks/"    "$(echo "$TICKET" | j "'/media/tasks/' in d['upload_url']")" "True"
curl -s -o /dev/null -X PUT -H 'Content-Type: image/png' --data-binary @/tmp/dot.png "$(echo "$TICKET" | j "d['upload_url']")"
ok "confirm works for a task file" "$(code -b /tmp/pa.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/attachments/$AID/confirm -d '{}')" "200"
ok "it appears in the panel"    "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "[f['filename'] for f in d]")" "['plan.png']"
ok "and is not marked as a comment file" "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "str(d[0]['from_comment'])")" "False"
ok "it names who added it"      "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "d[0]['uploaded_by']['email']")" "$A"

echo "== a comment's file shows up in the same panel"
CT=$(post /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/attachments '{"filename":"survey.png","content_type":"image/png"}')
CID=$(echo "$CT" | j "d['attachment']['id']")
curl -s -o /dev/null -X PUT -H 'Content-Type: image/png' --data-binary @/tmp/dot.png "$(echo "$CT" | j "d['upload_url']")"
post /tmp/pa.jar $B/api/organisations/$OID/attachments/$CID/confirm '{}' >/dev/null
ok "staged but unsent: not on the task" "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "sum(1 for f in d if f['filename']=='survey.png')")" "0"
post /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/comments "{\"body\":\"See attached\",\"attachment_ids\":[\"$CID\"]}" >/dev/null
ok "once sent, it IS on the task" "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "sum(1 for f in d if f['filename']=='survey.png')")" "1"
ok "and is marked as a comment file" "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "[f['from_comment'] for f in d if f['filename']=='survey.png'][0]")" "True"
ok "both files are listed"      "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "len(d)")" "2"

echo "== thumbnails"
# Made by the worker after confirm, so give it a moment. A missing thumbnail
# is a valid answer — the UI falls back to the original.
sleep 4
ok "an image gets a thumbnail"  "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "sum(1 for f in d if f['thumbnail_url'])")" "2"
ok "it points at a .thumb.jpg"  "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "'.thumb.jpg' in [f['thumbnail_url'] for f in d if f['thumbnail_url']][0]")" "True"
THUMB=$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "[f['thumbnail_url'] for f in d if f['thumbnail_url']][0]")
ok "and it can actually be fetched" "$(curl -s -o /dev/null -w '%{http_code}' "$THUMB")" "200"
# A text file must not get one, and must not be treated as broken.
TT=$(post /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files '{"filename":"notes.txt","content_type":"text/plain"}')
NID=$(echo "$TT" | j "d['attachment']['id']")
curl -s -o /dev/null -X PUT -H 'Content-Type: text/plain' --data-binary 'hello' "$(echo "$TT" | j "d['upload_url']")"
post /tmp/pa.jar $B/api/organisations/$OID/attachments/$NID/confirm '{}' >/dev/null
sleep 2
ok "a text file has no thumbnail" "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "str([f['thumbnail_url'] for f in d if f['filename']=='notes.txt'][0])")" "None"

echo "== permissions"
ok "no access to the task: 404"  "$(code -b /tmp/pb.jar $B/api/organisations/$OID/tasks/$TID/files)" "404"
ok "nor can they add one: 404"   "$(code -b /tmp/pb.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/files -d '{"filename":"x.png","content_type":"image/png"}')" "404"
post /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/access "{\"user_id\":\"$BUID\",\"level\":\"read\"}" >/dev/null
ok "a viewer sees the files"     "$(curl -s -b /tmp/pb.jar $B/api/organisations/$OID/tasks/$TID/files | j "len(d) >= 2")" "True"
# read is enough to comment, but attaching to the TASK changes what the task is.
ok "a viewer cannot add one"     "$(code -b /tmp/pb.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/files -d '{"filename":"x.png","content_type":"image/png"}')" "403"
ok "nor delete someone else's"   "$(code -b /tmp/pb.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/files/$AID)" "403"

echo "== deleting"
ok "the owner removes a file"    "$(code -b /tmp/pa.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/files/$AID)" "204"
ok "it is gone from the panel"   "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "sum(1 for f in d if f['filename']=='plan.png')")" "0"
# A comment's file is removed by removing the comment, not from here.
CFID=$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$TID/files | j "[f['id'] for f in d if f['from_comment']][0]")
ok "a comment's file isn't deletable here" "$(code -b /tmp/pa.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/files/$CFID)" "404"

echo "== moving a task between projects"
P1=$(post /tmp/pa.jar $B/api/organisations/$OID/projects '{"name":"First"}' | j "d['id']")
P2=$(post /tmp/pa.jar $B/api/organisations/$OID/projects '{"name":"Second"}' | j "d['id']")
MT=$(post /tmp/pa.jar $B/api/organisations/$OID/tasks "{\"title\":\"Travels\",\"project_id\":\"$P1\"}" | j "d['id']")
ok "moves to another project"    "$(patch /tmp/pa.jar $B/api/organisations/$OID/tasks/$MT "{\"project_id\":\"$P2\"}" | j "d['project_name']")" "Second"
ok "the move is in the history"  "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/tasks/$MT/events | j "sum(1 for e in d if e['kind']=='moved')")" "1"
ok "can be made loose"           "$(patch /tmp/pa.jar $B/api/organisations/$OID/tasks/$MT '{"project_id":null}' | j "str(d['project_id'])")" "None"
ok "and filed again"             "$(patch /tmp/pa.jar $B/api/organisations/$OID/tasks/$MT "{\"project_id\":\"$P1\"}" | j "d['project_name']")" "First"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
