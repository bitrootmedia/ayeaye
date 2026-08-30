#!/usr/bin/env bash
#
# Dependencies between tasks — informational, never enforced.
#
#   docker compose up -d && ./scripts/e2e-dependencies.sh
#
# "task_id depends on depends_on_task_id" reads left to right. Two rules
# worth a dedicated suite: you can only point a dependency at a task you can
# already see, and the graph stays a DAG (one recursive query refuses the
# edge that would close a cycle). Closing a task with open dependencies
# still works — that's the point, not a bug.
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

OWNER=dep-owner$S@example.com; OTHER=dep-other$S@example.com
signup /tmp/depo.jar $OWNER; signup /tmp/dept.jar $OTHER

OID=$(post /tmp/depo.jar $B/api/organisations "{\"name\":\"Deps $S\"}" | j "d['id']")
BODY="{\"email\":\"$OTHER\",\"role\":\"member\"}"
T=$(post /tmp/depo.jar $B/api/organisations/$OID/invites "$BODY" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/dept.jar -c /tmp/dept.jar -X POST $B/api/invites/$T/accept

A=$(post /tmp/depo.jar $B/api/organisations/$OID/tasks '{"title":"Task A"}' | j "d['id']")
BB=$(post /tmp/depo.jar $B/api/organisations/$OID/tasks '{"title":"Task B"}' | j "d['id']")
C=$(post /tmp/depo.jar $B/api/organisations/$OID/tasks '{"title":"Task C"}' | j "d['id']")

echo "== linking"
LINK=$(post /tmp/depo.jar $B/api/organisations/$OID/tasks/$A/dependencies "{\"depends_on_task_id\":\"$BB\"}")
DEPID=$(echo "$LINK" | j "d['id']")
ok "A depends on B, created" "$(echo "$LINK" | j "d['task']['title']")" "Task B"
ok "A cannot depend on itself" "$(code -b /tmp/depo.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$A/dependencies -d "{\"depends_on_task_id\":\"$A\"}")" "422"
ok "duplicate edge refused"     "$(code -b /tmp/depo.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$A/dependencies -d "{\"depends_on_task_id\":\"$BB\"}")" "409"

echo "== reading both directions"
ok "A's depends_on shows B"  "$(curl -s -b /tmp/depo.jar $B/api/organisations/$OID/tasks/$A/dependencies | j "d['depends_on'][0]['task']['title']")" "Task B"
ok "B's blocks shows A"      "$(curl -s -b /tmp/depo.jar $B/api/organisations/$OID/tasks/$BB/dependencies | j "d['blocks'][0]['task']['title']")" "Task A"

echo "== the graph stays a DAG"
ok "B depends on A is refused (direct cycle)" "$(code -b /tmp/depo.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$BB/dependencies -d "{\"depends_on_task_id\":\"$A\"}")" "409"
post /tmp/depo.jar $B/api/organisations/$OID/tasks/$BB/dependencies "{\"depends_on_task_id\":\"$C\"}" >/dev/null
ok "C depends on A closes a 3-node cycle, refused" "$(code -b /tmp/depo.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$C/dependencies -d "{\"depends_on_task_id\":\"$A\"}")" "409"

echo "== you can only link to something you can see"
ok "other cannot link A to a task they can't see (404)" "$(code -b /tmp/dept.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$A/dependencies -d "{\"depends_on_task_id\":\"$C\"}")" "404"

echo "== write-gated, not read"
BODY="{\"user_id\":\"$(curl -s -b /tmp/depo.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$OTHER'][0]")\",\"level\":\"read\"}"
post /tmp/depo.jar $B/api/organisations/$OID/tasks/$A/access "$BODY" >/dev/null
ok "read-only grantee cannot add a dependency" "$(code -b /tmp/dept.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$A/dependencies -d "{\"depends_on_task_id\":\"$C\"}")" "403"

echo "== an invisible dependency is a placeholder, never leaked"
ok "other (read on A only) sees B as a placeholder" "$(curl -s -b /tmp/dept.jar $B/api/organisations/$OID/tasks/$A/dependencies | j "d['depends_on'][0]['task']")" "None"

echo "== informational, not enforced: closing still works"
ok "A closes fine with an open dependency" "$(code -b /tmp/depo.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$A/closed -d '{"closed":true}')" "200"

echo "== removing"
ok "remove"       "$(code -b /tmp/depo.jar -X DELETE $B/api/organisations/$OID/tasks/$A/dependencies/$DEPID)" "204"
ok "gone"         "$(curl -s -b /tmp/depo.jar $B/api/organisations/$OID/tasks/$A/dependencies | j "len(d['depends_on'])")" "0"

echo "== every add and remove is in the history"
ok "events: added then removed" "$(curl -s -b /tmp/depo.jar $B/api/organisations/$OID/tasks/$A/events | j "[e['kind'] for e in d if e['kind'].startswith('dependency')]")" "['dependency_added', 'dependency_removed']"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
