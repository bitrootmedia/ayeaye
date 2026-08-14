#!/usr/bin/env bash
#
# Phase 4 end-to-end: tasks, the workflow rules, task-level access and the
# notification inbox — over HTTP against a running stack.
#
#   docker compose up -d && ./scripts/e2e-tasks.sh
#
# `tests/test_task_rules.py` proves the rules as pure functions. This proves
# the SQL that implements them agrees — in particular the loose-task case,
# where the correlated project subquery must yield NULL rather than dropping
# the row from the result.
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

# alice = org owner, bob = admin, carol = member (project owner), dave = member
A=ta$S@example.com; BB=tb$S@example.com; C=tc$S@example.com; D=td$S@example.com
signup /tmp/ta.jar $A; signup /tmp/tb.jar $BB; signup /tmp/tc.jar $C; signup /tmp/td.jar $D

OID=$(post /tmp/ta.jar $B/api/organisations "{\"name\":\"Tasks $S\"}" | j "d['id']")
join(){ T=$(post /tmp/ta.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"$3\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/tb.jar $BB admin
join /tmp/tc.jar $C member
join /tmp/td.jar $D member
uid(){ curl -s -b /tmp/ta.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$1'][0]"; }
CUID=$(uid $C); DUID=$(uid $D); AUID=$(uid $A)

PID=$(post /tmp/tc.jar $B/api/organisations/$OID/projects '{"name":"Build it"}' | j "d['id']")

echo "== creation and defaults"
T=$(post /tmp/tc.jar $B/api/organisations/$OID/tasks "{\"title\":\"Paint the hull\",\"project_id\":\"$PID\"}")
TID=$(echo "$T" | j "d['id']")
ok "new task is todo"           "$(echo "$T" | j "d['status']")" "todo"
ok "new task is open"           "$(echo "$T" | j "str(d['is_open'])")" "True"
ok "creator owns it"            "$(echo "$T" | j "d['owner']['email']")" "$C"
ok "owner may close"            "$(echo "$T" | j "str(d['can_close'])")" "True"
ok "history opens with created" "$(curl -s -b /tmp/tc.jar $B/api/organisations/$OID/tasks/$TID/events | j "d[0]['kind']")" "created"

echo "== status and open/closed are independent"
ok "set blocker"                "$(patch /tmp/tc.jar $B/api/organisations/$OID/tasks/$TID '{"status":"blocker"}' | j "d['status']")" "blocker"
ok "still open"                 "$(curl -s -b /tmp/tc.jar $B/api/organisations/$OID/tasks/$TID | j "str(d['is_open'])")" "True"
CL=$(post /tmp/tc.jar $B/api/organisations/$OID/tasks/$TID/closed '{"closed":true}')
ok "closed from blocker"        "$(echo "$CL" | j "str(d['is_open'])")" "False"
ok "and the status is untouched" "$(echo "$CL" | j "d['status']")" "blocker"
ok "closed drops off the list"  "$(curl -s -b /tmp/tc.jar "$B/api/organisations/$OID/tasks?project_id=$PID" | j "sum(1 for t in d if t['id']=='$TID')")" "0"
ok "include_closed brings it back" "$(curl -s -b /tmp/tc.jar "$B/api/organisations/$OID/tasks?project_id=$PID&include_closed=true" | j "sum(1 for t in d if t['id']=='$TID')")" "1"
ok "reopen"                     "$(post /tmp/tc.jar $B/api/organisations/$OID/tasks/$TID/closed '{"closed":false}' | j "str(d['is_open'])")" "True"
ok "closed+reopened in history" "$(curl -s -b /tmp/tc.jar $B/api/organisations/$OID/tasks/$TID/events | j "[e['kind'] for e in d].count('closed') + [e['kind'] for e in d].count('reopened')")" "2"

echo "== only the owner closes"
post /tmp/tc.jar $B/api/organisations/$OID/projects/$PID/access "{\"user_id\":\"$DUID\",\"level\":\"write\"}" >/dev/null
ok "editor sees the task"       "$(curl -s -b /tmp/td.jar $B/api/organisations/$OID/tasks/$TID | j "d['access']")" "write"
ok "editor can edit"            "$(patch /tmp/td.jar $B/api/organisations/$OID/tasks/$TID '{"status":"in_progress"}' | j "d['status']")" "in_progress"
# 403, not 404: they can see it, they just may not finish it.
ok "editor cannot close (403)"  "$(code -b /tmp/td.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$TID/closed -d '{"closed":true}')" "403"
ok "and can_close says so"      "$(curl -s -b /tmp/td.jar $B/api/organisations/$OID/tasks/$TID | j "str(d['can_close'])")" "False"
ok "org admin can close it"     "$(post /tmp/tb.jar $B/api/organisations/$OID/tasks/$TID/closed '{"closed":true}' | j "str(d['is_open'])")" "False"
post /tmp/tb.jar $B/api/organisations/$OID/tasks/$TID/closed '{"closed":false}' >/dev/null

echo "== loose tasks are not org-wide"
L=$(post /tmp/tc.jar $B/api/organisations/$OID/tasks '{"title":"Private note"}')
LID=$(echo "$L" | j "d['id']")
ok "loose task has no project"  "$(echo "$L" | j "str(d['project_id'])")" "None"
ok "owner sees it"              "$(code -b /tmp/tc.jar $B/api/organisations/$OID/tasks/$LID)" "200"
ok "another member: 404"        "$(code -b /tmp/td.jar $B/api/organisations/$OID/tasks/$LID)" "404"
ok "not in their list"          "$(curl -s -b /tmp/td.jar $B/api/organisations/$OID/tasks | j "sum(1 for t in d if t['id']=='$LID')")" "0"
ok "org admin sees it"          "$(curl -s -b /tmp/tb.jar $B/api/organisations/$OID/tasks/$LID | j "d['access']")" "owner"
ok "loose filter works"         "$(curl -s -b /tmp/tc.jar "$B/api/organisations/$OID/tasks?loose=true" | j "sum(1 for t in d if t['id']=='$LID')")" "1"
ok "and excludes project tasks" "$(curl -s -b /tmp/tc.jar "$B/api/organisations/$OID/tasks?loose=true" | j "sum(1 for t in d if t['id']=='$TID')")" "0"

echo "== being asked to act carries its own access"
ok "dave cannot see it yet"     "$(code -b /tmp/td.jar $B/api/organisations/$OID/tasks/$LID)" "404"
patch /tmp/tc.jar $B/api/organisations/$OID/tasks/$LID "{\"action_required_user_id\":\"$DUID\"}" >/dev/null
ok "now he can, at write"       "$(curl -s -b /tmp/td.jar $B/api/organisations/$OID/tasks/$LID | j "d['access']")" "write"
ok "but still cannot close"     "$(code -b /tmp/td.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$LID/closed -d '{"closed":true}')" "403"
ok "he was notified"            "$(curl -s -b /tmp/td.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='task_action_required')")" "1"
# Rule 3: the same person again must not re-notify.
patch /tmp/tc.jar $B/api/organisations/$OID/tasks/$LID "{\"action_required_user_id\":\"$DUID\"}" >/dev/null
ok "setting it again: no re-ping" "$(curl -s -b /tmp/td.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='task_action_required')")" "1"
patch /tmp/tc.jar $B/api/organisations/$OID/tasks/$LID '{"action_required_user_id":null}' >/dev/null
ok "clearing notifies nobody"   "$(curl -s -b /tmp/td.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='task_action_required')")" "1"
ok "and access goes with it"    "$(code -b /tmp/td.jar $B/api/organisations/$OID/tasks/$LID)" "404"

echo "== per-task grants are additive"
ok "grant read on the loose task" "$(code -b /tmp/tc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$LID/access -d '{"user_id":"'$DUID'","level":"read"}')" "201"
ok "dave reads it"              "$(curl -s -b /tmp/td.jar $B/api/organisations/$OID/tasks/$LID | j "d['access']")" "read"
ok "he was told"                "$(curl -s -b /tmp/td.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='task_shared')")" "1"
# On the PROJECT task he already has write from the project. A weaker task
# grant must not reduce it — that would be a deny rule.
post /tmp/tc.jar $B/api/organisations/$OID/tasks/$TID/access "{\"user_id\":\"$DUID\",\"level\":\"read\"}" >/dev/null
ok "weak task grant cannot demote" "$(curl -s -b /tmp/td.jar $B/api/organisations/$OID/tasks/$TID | j "d['access']")" "write"

echo "== ownership"
ok "editor cannot hand over"    "$(code -b /tmp/td.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/tasks/$TID -d '{"owner_user_id":"'$DUID'"}')" "403"
ok "owner hands over"           "$(patch /tmp/tc.jar $B/api/organisations/$OID/tasks/$TID "{\"owner_user_id\":\"$DUID\"}" | j "d['owner']['email']")" "$D"
ok "new owner was notified"     "$(curl -s -b /tmp/td.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='task_owner_changed')")" "1"
ok "now he can close"           "$(post /tmp/td.jar $B/api/organisations/$OID/tasks/$TID/closed '{"closed":true}' | j "str(d['is_open'])")" "False"
ok "owner_changed is in history" "$(curl -s -b /tmp/td.jar $B/api/organisations/$OID/tasks/$TID/events | j "sum(1 for e in d if e['kind']=='owner_changed')")" "1"

echo "== the inbox"
ok "unread count is live"       "$(curl -s -b /tmp/td.jar $B/api/notifications/unread-count | j "d['unread'] >= 3")" "True"
NID=$(curl -s -b /tmp/td.jar $B/api/notifications | j "d[0]['id']")
ok "mark one read"              "$(code -b /tmp/td.jar -X POST $B/api/notifications/$NID/read)" "204"
ok "mark all read"              "$(code -b /tmp/td.jar -X POST $B/api/notifications/read-all)" "204"
ok "count goes to zero"         "$(curl -s -b /tmp/td.jar $B/api/notifications/unread-count | j "d['unread']")" "0"
ok "inbox is per person"        "$(curl -s -b /tmp/ta.jar $B/api/notifications | j "len(d)")" "0"

echo "== you cannot file work into a project you only read"
P2=$(post /tmp/ta.jar $B/api/organisations/$OID/projects '{"name":"Alice only"}' | j "d['id']")
post /tmp/ta.jar $B/api/organisations/$OID/projects/$P2/access "{\"user_id\":\"$CUID\",\"level\":\"read\"}" >/dev/null
ok "reader cannot add a task"   "$(code -b /tmp/tc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks -d '{"title":"nope","project_id":"'$P2'"}')" "403"
ok "invisible project: 404"     "$(code -b /tmp/td.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks -d '{"title":"nope","project_id":"'$P2'"}')" "404"

echo "== offboarding reassigns rather than blocking"
# Dave owns a task and a project grant. Removing him must not fail on the
# RESTRICT foreign key.
DMID=$(curl -s -b /tmp/ta.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$D'][0]")
ok "removing him succeeds"      "$(code -b /tmp/ta.jar -X DELETE $B/api/organisations/$OID/members/$DMID)" "204"
ok "his task now belongs to an owner" "$(curl -s -b /tmp/ta.jar $B/api/organisations/$OID/tasks/$TID | j "d['owner']['email']")" "$A"
ok "and the handover is recorded" "$(curl -s -b /tmp/ta.jar $B/api/organisations/$OID/tasks/$TID/events | j "sum(1 for e in d if e['kind']=='owner_changed' and e['data'].get('reason'))")" "1"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
