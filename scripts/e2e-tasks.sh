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

echo "== handing it back: the owner is notified when action-required clears"
BODY="{\"title\":\"Review the draft\",\"action_required_user_id\":\"$DUID\"}"
HB=$(post /tmp/tc.jar $B/api/organisations/$OID/tasks "$BODY")
HID=$(echo "$HB" | j "d['id']")
ok "dave was asked"             "$(curl -s -b /tmp/td.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='task_action_required')")" "2"
BODY='{"action_required_user_id": null}'
# Dave clearing his OWN action-required was his only route into this task —
# the response still has to be 200 with a real body, not a 404 on a commit
# that already succeeded. Same class of bug the ownership-handover endpoint
# already had to solve for itself.
ok "dave clears it himself: 200, not 404" "$(code -b /tmp/td.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/tasks/$HID -d "$BODY")" "200"
ok "carol (the owner) is told"  "$(curl -s -b /tmp/tc.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='task_action_required_cleared')")" "1"
ok "dave lost access with it"   "$(code -b /tmp/td.jar $B/api/organisations/$OID/tasks/$HID)" "404"
# The owner clearing their own doesn't notify themselves.
BODY="{\"title\":\"Self-assigned\",\"action_required_user_id\":\"$CUID\"}"
SELF=$(post /tmp/tc.jar $B/api/organisations/$OID/tasks "$BODY" | j "d['id']")
BEFORE=$(curl -s -b /tmp/tc.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='task_action_required_cleared')")
patch /tmp/tc.jar $B/api/organisations/$OID/tasks/$SELF '{"action_required_user_id": null}' >/dev/null
AFTER=$(curl -s -b /tmp/tc.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='task_action_required_cleared')")
ok "clearing your own notifies nobody" "$([ "$BEFORE" = "$AFTER" ] && echo same)" "same"

echo "== estimate fields: purely informational, round-trip cleanly"
BODY='{"title":"Estimate this","estimated_start_on":"2026-09-01","estimated_hours":6.5}'
EST=$(post /tmp/tc.jar $B/api/organisations/$OID/tasks "$BODY")
EID=$(echo "$EST" | j "d['id']")
ok "start date persisted"       "$(echo "$EST" | j "d['estimated_start_on']")" "2026-09-01"
ok "hours persisted"            "$(echo "$EST" | j "d['estimated_hours']")" "6.5"
ok "rounds to one decimal"      "$(patch /tmp/tc.jar $B/api/organisations/$OID/tasks/$EID '{"estimated_hours": 3.14}' | j "d['estimated_hours']")" "3.1"
ok "both clear independently"   "$(patch /tmp/tc.jar $B/api/organisations/$OID/tasks/$EID '{"estimated_start_on": null}' | j "d['estimated_hours']")" "3.1"
ok "…and the other still clears" "$(patch /tmp/tc.jar $B/api/organisations/$OID/tasks/$EID '{"estimated_hours": null}' | j "str(d['estimated_hours'])")" "None"

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

COUNT_BEFORE=$(curl -s -b /tmp/td.jar $B/api/notifications | j "len(d)")
ok "delete one"                 "$(code -b /tmp/td.jar -X DELETE $B/api/notifications/$NID)" "204"
ok "it's gone"                  "$(curl -s -b /tmp/td.jar $B/api/notifications | j "len(d)")" "$((COUNT_BEFORE - 1))"
ok "deleting again is still 204, not 404" "$(code -b /tmp/td.jar -X DELETE $B/api/notifications/$NID)" "204"
ok "deleting someone else's is a silent no-op, not leaked" "$(code -b /tmp/ta.jar -X DELETE $B/api/notifications/$NID)" "204"

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

echo "== the board is bounded per column, and says so"
# Twelve in one column. A plain LIMIT can't bound a board: rows come back
# priority-first, so the first N of a busy organisation are all criticals and
# the other columns arrive empty. Each column is bounded separately.
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  post /tmp/ta.jar $B/api/organisations/$OID/tasks "{\"title\":\"Bulk $i\",\"status\":\"todo\"}" >/dev/null
done
BOARD=$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks/board?per_group=5")
ok "a column is capped"         "$(echo "$BOARD" | j "len([c for c in d['columns'] if c['key']=='todo'][0]['tasks'])")" "5"
ok "…but reports its real size" "$(echo "$BOARD" | j "[c for c in d['columns'] if c['key']=='todo'][0]['total'] >= 12")" "True"
ok "grouping by priority works" "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks/board?group=priority" | j "d['group_by']")" "priority"
ok "per_group is clamped"       "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks/board?per_group=99999" | j "d['per_group']")" "200"
# The board is a view of the same access model, not a way round it. Dave was
# removed from the organisation above, so this is a non-member — and note the
# assertion is on the STATUS: `len(d)` on a 404 body is 1, which quietly
# compares equal to a one-task board.
ok "a non-member gets 404"      "$(code -b /tmp/td.jar $B/api/organisations/$OID/tasks/board)" "404"
# And for a member, the board holds exactly what the list holds.
ok "same tasks as the list"     "$(curl -s -b /tmp/tc.jar "$B/api/organisations/$OID/tasks/board?per_group=200" | j "sum(len(c['tasks']) for c in d['columns'])")" "$(curl -s -b /tmp/tc.jar $B/api/organisations/$OID/tasks | j "len(d)")"

echo "== the board can group by action required, a nullable column unlike status or priority"
ART=$(post /tmp/ta.jar $B/api/organisations/$OID/tasks "{\"title\":\"Ask Carol $S\"}" | j "d['id']")
patch /tmp/ta.jar $B/api/organisations/$OID/tasks/$ART "{\"action_required_user_id\":\"$CUID\"}" >/dev/null
# $TID won't do for the "none" check below — the close/reopen tests above
# leave it closed, and a board excludes closed tasks by default same as the
# list does. A fresh task is unambiguously open and unambiguously nobody's.
NOART=$(post /tmp/ta.jar $B/api/organisations/$OID/tasks "{\"title\":\"Nobody's problem $S\"}" | j "d['id']")
ARBOARD=$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks/board?group=action_required&per_group=200")
ok "group_by echoes back"       "$(echo "$ARBOARD" | j "d['group_by']")" "action_required"
ok "Carol's own column key is her id" \
  "$(echo "$ARBOARD" | j "sum(1 for t in [c for c in d['columns'] if c['key']=='$CUID'][0]['tasks'] if t['id']=='$ART')")" "1"
# Every task made earlier in this script has nobody action-required, so the
# "none" column — the JSON-safe stand-in for the NULL partition — is not a
# corner case here, it is most of the board.
ok "a plain task lands in the 'none' column, not dropped" \
  "$(echo "$ARBOARD" | j "sum(1 for t in [c for c in d['columns'] if c['key']=='none'][0]['tasks'] if t['id']=='$NOART')")" "1"

echo "== the list pages, and says what it is a page of"
ok "no limit means everything"  "$(curl -s -b /tmp/ta.jar $B/api/organisations/$OID/tasks | j "len(d) >= 12")" "True"
ok "a limit is honoured"        "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?limit=4" | j "len(d)")" "4"
ok "the total comes back whole" "$(curl -s -o /dev/null -D - -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?limit=4" | grep -i '^x-total-count' | tr -d '\r' | cut -d' ' -f2)" "$(curl -s -b /tmp/ta.jar $B/api/organisations/$OID/tasks | j "len(d)")"
ok "offset moves the window"    "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?limit=4&offset=4" | j "d[0]['id']")" "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?limit=8" | j "d[4]['id']")"
ok "past the end is empty, not an error" "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?limit=5&offset=99999" | j "len(d)")" "0"

echo "== updated_at is last ACTIVITY, not last row update"
# The column the list sorts by. Every one of these leaves the tasks row itself
# untouched, so without an explicit stamp it would answer a question nobody
# asks.
UT=$(post /tmp/ta.jar $B/api/organisations/$OID/tasks '{"title":"Touch me"}' | j "d['id']")
stamp(){ curl -s -b /tmp/ta.jar $B/api/organisations/$OID/tasks/$UT | j "d['updated_at']"; }
WAS=$(stamp)
sleep 1
patch /tmp/ta.jar $B/api/organisations/$OID/tasks/$UT '{"status":"review"}' >/dev/null
NOW=$(stamp); ok "a status change bumps it"  "$([ "$NOW" != "$WAS" ] && echo yes)" "yes"

WAS=$NOW; sleep 1
post /tmp/ta.jar $B/api/organisations/$OID/tasks/$UT/comments '{"body":"a word"}' >/dev/null
NOW=$(stamp); ok "a COMMENT bumps it"        "$([ "$NOW" != "$WAS" ] && echo yes)" "yes"

WAS=$NOW; sleep 1
post /tmp/ta.jar $B/api/organisations/$OID/tasks/$UT/tags '{"name":"Touched"}' >/dev/null
NOW=$(stamp); ok "a TAG bumps it"            "$([ "$NOW" != "$WAS" ] && echo yes)" "yes"

WAS=$NOW; sleep 1
post /tmp/ta.jar $B/api/organisations/$OID/tasks/$UT/time '{"minutes":15}' >/dev/null
NOW=$(stamp); ok "LOGGED TIME bumps it"      "$([ "$NOW" != "$WAS" ] && echo yes)" "yes"

# The exception, and the whole point of it: a note nobody else can read must
# not announce itself through a timestamp everybody can see.
WAS=$NOW; sleep 1
curl -s -b /tmp/ta.jar -H 'Content-Type: application/json' -X PUT $B/api/organisations/$OID/tasks/$UT/note -d '{"body":"just for me"}' >/dev/null
NOW=$(stamp); ok "a PRIVATE NOTE does not"   "$([ "$NOW" = "$WAS" ] && echo same)" "same"

echo "== the list filters and sorts"
ok "filter by status"           "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?status=review" | j "set(t['status'] for t in d) == {'review'}")" "True"
ok "filter by priority"         "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?priority=normal" | j "set(t['priority'] for t in d) == {'normal'}")" "True"
AUID=$(curl -s -b /tmp/ta.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$A'][0]")
ok "filter by owner"            "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?owner_user_id=$AUID" | j "set(t['owner']['id'] for t in d) == {'$AUID'}")" "True"
ok "filters combine"            "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?status=review&owner_user_id=$AUID" | j "all(t['status']=='review' and t['owner']['id']=='$AUID' for t in d)")" "True"
# Sorted server-side, because the page is a page: ordering in the browser
# would only order the rows it happens to be holding.
ok "sort by updated_at desc"    "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?sort=updated_at&dir=desc" | j "d[0]['id']")" "$UT"
ok "…and asc puts it last"      "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?sort=updated_at" | j "d[-1]['id']")" "$UT"
ok "sort by title is A-Z"       "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?sort=title" | j "[t['title'] for t in d] == sorted(t['title'] for t in d)")" "True"
# By rank, not by spelling: alphabetically "blocker" would come first.
ok "status sorts by workflow"   "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?sort=status" | j "d[0]['status']")" "todo"
ok "an unknown sort is ignored" "$(code -b /tmp/ta.jar "$B/api/organisations/$OID/tasks?sort=nonsense")" "200"

echo "== a description is sanitised HTML, and search reads the prose"
# The editor produces tidy markup. That is irrelevant — this is what a client
# can actually send, and the next person to open the task renders it.
RT=$(post /tmp/ta.jar $B/api/organisations/$OID/tasks '{"title":"Rich"}' | j "d['id']")
desc(){ curl -s -b /tmp/ta.jar $B/api/organisations/$OID/tasks/$RT | j "d['description'] or ''"; }
patch /tmp/ta.jar $B/api/organisations/$OID/tasks/$RT '{"description":"<p>Hull needs <strong>epoxy</strong></p><script>alert(1)</script>"}' >/dev/null
ok "the script tag is gone"     "$(desc | grep -c script)" "0"
ok "the formatting stays"       "$(desc | grep -c '<strong>epoxy</strong>')" "1"
patch /tmp/ta.jar $B/api/organisations/$OID/tasks/$RT '{"description":"<p onclick=\"steal()\">Hi</p>"}' >/dev/null
ok "an inline handler is gone"  "$(desc | grep -c onclick)" "0"
patch /tmp/ta.jar $B/api/organisations/$OID/tasks/$RT '{"description":"<p><a href=\"javascript:alert(1)\">x</a></p>"}' >/dev/null
ok "a javascript: link is gone" "$(desc | grep -c javascript)" "0"
# An image with no attachment id can never be served, so it is dropped rather
# than stored as a permanent broken-image icon.
patch /tmp/ta.jar $B/api/organisations/$OID/tasks/$RT '{"description":"<p>a</p><img src=\"https://tracker.example.com/pixel.gif\">"}' >/dev/null
ok "an external image is gone"  "$(desc | grep -c 'tracker.example.com')" "0"
patch /tmp/ta.jar $B/api/organisations/$OID/tasks/$RT '{"description":"<pre><code class=\"language-python\">x=1</code></pre>"}' >/dev/null
ok "a code language survives"   "$(desc | grep -c 'language-python')" "1"
patch /tmp/ta.jar $B/api/organisations/$OID/tasks/$RT '{"description":"<pre><code class=\"absolute inset-0\">x</code></pre>"}' >/dev/null
ok "any other class does not"   "$(desc | grep -c 'absolute')" "0"
patch /tmp/ta.jar $B/api/organisations/$OID/tasks/$RT '{"description":"<p></p>"}' >/dev/null
ok "an emptied editor is empty" "$(curl -s -b /tmp/ta.jar $B/api/organisations/$OID/tasks/$RT | j "d['description'] is None")" "True"

patch /tmp/ta.jar $B/api/organisations/$OID/tasks/$RT '{"description":"<p>The <em>mizzenmast</em> bracket</p>"}' >/dev/null
ok "search matches the prose"   "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/search?q=mizzenmast" | j "sum(1 for h in d['hits'] if h['id']=='$RT')")" "1"
# The whole reason for the generated column: searching a tag name must not
# return every task that happens to be formatted.
ok "…and not the markup"        "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/search?q=strong" | j "sum(1 for h in d['hits'] if h['id']=='$RT')")" "0"
ok "the snippet is prose"       "$(curl -s -b /tmp/ta.jar "$B/api/organisations/$OID/search?q=mizzenmast" | j "'<' in ([h['subtitle'] for h in d['hits'] if h['id']=='$RT'][0] or '')")" "False"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
