#!/usr/bin/env bash
#
# Sharing one task without sharing its whole project.
#
#   docker compose up -d && ./scripts/e2e-task-sharing.sh
#
# The backend (POST/PATCH/DELETE .../tasks/{id}/access) has existed since
# Phase 4 — what this proves is the frontend reuse: components/access-panel.tsx
# generalized from a project-only component (basePath instead of a hardcoded
# projectId) into the identical share/level/revoke flow for tasks. The one
# property worth a dedicated check: sharing a task grants exactly that task,
# never the project it's filed in.
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

OWNER=ts-owner$S@example.com; OTHER=ts-other$S@example.com
signup /tmp/tso.jar $OWNER; signup /tmp/tst.jar $OTHER

OID=$(post /tmp/tso.jar $B/api/organisations "{\"name\":\"TaskSharing $S\"}" | j "d['id']")
BODY="{\"email\":\"$OTHER\",\"role\":\"member\"}"
T=$(post /tmp/tso.jar $B/api/organisations/$OID/invites "$BODY" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/tst.jar -c /tmp/tst.jar -X POST $B/api/invites/$T/accept
OTHER_ID=$(curl -s -b /tmp/tso.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$OTHER'][0]")

PID=$(post /tmp/tso.jar $B/api/organisations/$OID/projects '{"name":"Private Project"}' | j "d['id']")
BODY="{\"title\":\"Isolated task\",\"project_id\":\"$PID\"}"
TID=$(post /tmp/tso.jar $B/api/organisations/$OID/tasks "$BODY" | j "d['id']")

echo "== before sharing"
ok "other cannot see the task"   "$(code -b /tmp/tst.jar $B/api/organisations/$OID/tasks/$TID)" "404"
ok "nor the project"             "$(code -b /tmp/tst.jar $B/api/organisations/$OID/projects/$PID)" "404"

echo "== sharing the task, not the project"
BODY="{\"user_id\":\"$OTHER_ID\",\"level\":\"write\"}"
GRANT=$(post /tmp/tso.jar $B/api/organisations/$OID/tasks/$TID/access "$BODY")
GID=$(echo "$GRANT" | j "d['id']")
ok "grant created"               "$(echo "$GRANT" | j "d['level']")" "write"
ok "other now sees the task"     "$(curl -s -b /tmp/tst.jar $B/api/organisations/$OID/tasks/$TID | j "d['access']")" "write"
ok "other still cannot see the project" "$(code -b /tmp/tst.jar $B/api/organisations/$OID/projects/$PID)" "404"
ok "they were notified"          "$(curl -s -b /tmp/tst.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='task_shared')")" "1"

echo "== changing the level"
BODY='{"level":"read"}'
ok "downgrade to read"           "$(patch /tmp/tso.jar $B/api/organisations/$OID/tasks/$TID/access/$GID "$BODY" | j "d['level']")" "read"
ok "other can no longer close"   "$(code -b /tmp/tst.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/closed -d '{"closed":true}')" "403"

echo "== revoking"
ok "revoke"                      "$(code -b /tmp/tso.jar -X DELETE $B/api/organisations/$OID/tasks/$TID/access/$GID)" "204"
ok "access is gone"              "$(code -b /tmp/tst.jar $B/api/organisations/$OID/tasks/$TID)" "404"

echo "== you cannot share a task you only read"
BODY="{\"user_id\":\"$OTHER_ID\",\"level\":\"read\"}"
post /tmp/tso.jar $B/api/organisations/$OID/tasks/$TID/access "$BODY" >/dev/null
BODY2='{"user_id":"'$OTHER_ID'","level":"write"}'
ok "a read grantee cannot re-share it" "$(code -b /tmp/tst.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/access -d "$BODY2")" "403"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
