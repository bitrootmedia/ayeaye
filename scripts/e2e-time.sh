#!/usr/bin/env bash
#
# Phase 5 end-to-end: timers, manual entries, corrections and rollups.
#
#   docker compose up -d && ./scripts/e2e-time.sh
#
# `tests/test_time_rules.py` proves the arithmetic and the permission rule as
# pure functions. This proves the parts that only exist in the database: the
# partial unique index that enforces one running timer, and the rollups, which
# must aggregate over exactly the tasks the caller can see.
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
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "${3:-{\}}"; }
patch(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PATCH "$2" -d "$3"; }

# alice = org OWNER, bob = org admin, carol + dave = plain members.
# Both plain members matter: "the task owner cannot edit someone else's
# timesheet" is only a real test between two people who hold no org-level
# override — Alice would pass it for the wrong reason.
A=ma$S@example.com; BB=mb$S@example.com; C=mc$S@example.com; D=md$S@example.com
signup /tmp/ma.jar $A; signup /tmp/mb.jar $BB; signup /tmp/mc.jar $C; signup /tmp/md.jar $D

OID=$(post /tmp/ma.jar $B/api/organisations "{\"name\":\"Hours $S\"}" | j "d['id']")
join(){ T=$(post /tmp/ma.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"$3\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/mb.jar $BB admin
join /tmp/mc.jar $C member
join /tmp/md.jar $D member
uid(){ curl -s -b /tmp/ma.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$1'][0]"; }
CUID=$(uid $C); DUID=$(uid $D)

PID=$(post /tmp/ma.jar $B/api/organisations/$OID/projects '{"name":"Refit"}' | j "d['id']")
T1=$(post /tmp/ma.jar $B/api/organisations/$OID/tasks "{\"title\":\"Sand the hull\",\"project_id\":\"$PID\"}" | j "d['id']")
T2=$(post /tmp/ma.jar $B/api/organisations/$OID/tasks "{\"title\":\"Paint the hull\",\"project_id\":\"$PID\"}" | j "d['id']")
LOOSE=$(post /tmp/ma.jar $B/api/organisations/$OID/tasks '{"title":"Admin faff"}' | j "d['id']")

echo "== the timer"
ok "nothing running to start with" "$(curl -s -b /tmp/ma.jar $B/api/me/timer | j "str(d['entry'])")" "None"
ok "start one"                  "$(post /tmp/ma.jar $B/api/organisations/$OID/tasks/$T1/time/start | j "d['entry']['task_id']")" "$T1"
ok "it shows as running"        "$(curl -s -b /tmp/ma.jar $B/api/me/timer | j "str(d['entry']['ended_at'])")" "None"
ok "and names the task"         "$(curl -s -b /tmp/ma.jar $B/api/me/timer | j "d['entry']['task_title']")" "Sand the hull"
ok "and the organisation"       "$(curl -s -b /tmp/ma.jar $B/api/me/timer | j "d['organisation_id']")" "$OID"

echo "== one timer, always"
# Starting a second stops the first rather than erroring — switching tasks is
# the commonest thing anyone does with a tracker.
SW=$(post /tmp/ma.jar $B/api/organisations/$OID/tasks/$T2/time/start)
ok "switching stops the old one" "$(echo "$SW" | j "d['stopped']['task_id']")" "$T1"
ok "and starts the new one"      "$(echo "$SW" | j "d['entry']['task_id']")" "$T2"
ok "still exactly one running"   "$(curl -s -b /tmp/ma.jar $B/api/me/timer | j "d['entry']['task_id']")" "$T2"
ok "restarting the same task is a no-op" "$(post /tmp/ma.jar $B/api/organisations/$OID/tasks/$T2/time/start | j "str(d['stopped'])")" "None"
ok "stop it"                     "$(post /tmp/ma.jar $B/api/me/timer/stop | j "d['entry']['task_id']")" "$T2"
ok "nothing running now"         "$(curl -s -b /tmp/ma.jar $B/api/me/timer | j "str(d['entry'])")" "None"
ok "stopping twice is fine"      "$(post /tmp/ma.jar $B/api/me/timer/stop | j "str(d['entry'])")" "None"

echo "== the timer is per person, not per organisation"
OTHER=$(post /tmp/ma.jar $B/api/organisations "{\"name\":\"Elsewhere $S\"}" | j "d['id']")
OT=$(post /tmp/ma.jar $B/api/organisations/$OTHER/tasks '{"title":"Other work"}' | j "d['id']")
post /tmp/ma.jar $B/api/organisations/$OID/tasks/$T1/time/start >/dev/null
SW2=$(post /tmp/ma.jar $B/api/organisations/$OTHER/tasks/$OT/time/start)
ok "a timer in another org stops this one" "$(echo "$SW2" | j "d['stopped']['task_id']")" "$T1"
ok "and /me/timer follows you there"       "$(curl -s -b /tmp/ma.jar $B/api/me/timer | j "d['organisation_id']")" "$OTHER"
post /tmp/ma.jar $B/api/me/timer/stop >/dev/null

echo "== manual entries"
E1=$(post /tmp/ma.jar $B/api/organisations/$OID/tasks/$T1/time '{"minutes":90,"note":"first coat"}')
ok "90 minutes lands"           "$(echo "$E1" | j "d['seconds']")" "5400"
ok "the note is kept"           "$(echo "$E1" | j "d['note']")" "first coat"
ok "it is not running"          "$(echo "$E1" | j "str(d['ended_at'] is not None)")" "True"
ok "zero minutes refused"       "$(code -b /tmp/ma.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$T1/time -d '{"minutes":0}')" "422"
ok "negative refused"           "$(code -b /tmp/ma.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$T1/time -d '{"minutes":-30}')" "422"
ok "more than a day refused"    "$(code -b /tmp/ma.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$T1/time -d '{"minutes":2000}')" "422"
ok "the future refused"         "$(code -b /tmp/ma.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$T1/time -d '{"minutes":30,"started_at":"2030-01-01T09:00:00Z"}')" "422"

echo "== corrections leave a trail"
EID=$(echo "$E1" | j "d['id']")
ok "shorten it to 45"           "$(patch /tmp/ma.jar $B/api/organisations/$OID/time/$EID '{"minutes":45}' | j "d['seconds']")" "2700"
ok "and it is marked edited"    "$(patch /tmp/ma.jar $B/api/organisations/$OID/time/$EID '{"note":"second coat"}' | j "str(d['edited_at'] is not None)")" "True"
ok "the task history records it" "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks/$T1/events | j "sum(1 for e in d if e['kind']=='time_edited')")" "2"
ok "logging is in the history too" "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks/$T1/events | j "sum(1 for e in d if e['kind']=='time_logged') >= 1")" "True"

echo "== whose timesheet is it"
# Carol needs to see the task before she can do anything with its time.
post /tmp/ma.jar $B/api/organisations/$OID/projects/$PID/access "{\"user_id\":\"$CUID\",\"level\":\"read\"}" >/dev/null
ok "read access is enough to log your own time" "$(post /tmp/mc.jar $B/api/organisations/$OID/tasks/$T1/time '{"minutes":30}' | j "d['seconds']")" "1800"
ok "she cannot edit Alice's"    "$(code -b /tmp/mc.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/time/$EID -d '{"minutes":10}')" "403"
ok "nor delete it"              "$(code -b /tmp/mc.jar -X DELETE $B/api/organisations/$OID/time/$EID)" "403"
ok "an org admin can"           "$(patch /tmp/mb.jar $B/api/organisations/$OID/time/$EID '{"minutes":60}' | j "d['seconds']")" "3600"
# Owning a task grants nothing over someone else's timesheet. Tested between
# two plain members — Alice is the org owner and would pass for the wrong
# reason, which is exactly the confusion this asserts against.
CT=$(post /tmp/mc.jar $B/api/organisations/$OID/tasks '{"title":"Carols own task"}' | j "d['id']")
post /tmp/mc.jar $B/api/organisations/$OID/tasks/$CT/access "{\"user_id\":\"$DUID\",\"level\":\"read\"}" >/dev/null
DEID=$(post /tmp/md.jar $B/api/organisations/$OID/tasks/$CT/time '{"minutes":20}' | j "d['id']")
ok "the task owner cannot edit another's entry" "$(code -b /tmp/mc.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/time/$DEID -d '{"minutes":5}')" "403"
ok "nor delete it"                              "$(code -b /tmp/mc.jar -X DELETE $B/api/organisations/$OID/time/$DEID)" "403"
ok "but Dave can edit his own"                  "$(patch /tmp/md.jar $B/api/organisations/$OID/time/$DEID '{"minutes":25}' | j "d['seconds']")" "1500"
CEID=$(curl -s -b /tmp/mc.jar $B/api/organisations/$OID/tasks/$T1/time | j "[e['id'] for e in d if e['user']['email']=='$C'][0]")

echo "== entries you cannot see"
ok "no access to the loose task: 404" "$(code -b /tmp/mc.jar $B/api/organisations/$OID/tasks/$LOOSE/time)" "404"
ok "nor can she log against it"       "$(code -b /tmp/mc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks/$LOOSE/time -d '{"minutes":10}')" "404"

echo "== rollups"
post /tmp/ma.jar $B/api/organisations/$OID/tasks/$LOOSE/time '{"minutes":15}' >/dev/null
SUM=$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/time/summary)
# Alice: 60m (corrected by the admin) + 15m loose. Carol: 30m. Dave: 25m.
# Plus the switched timers, a fraction of a second each — so assert a floor,
# not an exact total.
ok "total is at least the manual entries" "$(echo "$SUM" | j "d['total_seconds'] >= 3600+1800+900+1500")" "True"
ok "three people appear"        "$(echo "$SUM" | j "len(d['by_person'])")" "3"
ok "the project is broken out"  "$(echo "$SUM" | j "sum(1 for r in d['by_project'] if r['name']=='Refit')")" "1"
ok "loose time is not dropped"  "$(echo "$SUM" | j "sum(1 for r in d['by_project'] if r['name']=='No project')")" "1"
ok "by task too"                "$(echo "$SUM" | j "sum(1 for r in d['by_task'] if r['name']=='Sand the hull')")" "1"
ok "filtering by project works" "$(curl -s -b /tmp/ma.jar "$B/api/organisations/$OID/time/summary?project_id=$PID" | j "sum(1 for r in d['by_project'] if r['name']=='No project')")" "0"

echo "== rollups respect what you can see"
CSUM=$(curl -s -b /tmp/mc.jar $B/api/organisations/$OID/time/summary)
# Carol can see the project's tasks but not the loose one, so her total must
# exclude Alice's 15 minutes there — the aggregate uses the same visibility
# subquery as the board.
ok "she sees the project's time"  "$(echo "$CSUM" | j "d['total_seconds'] >= 3600+1800")" "True"
ok "and her own task's"           "$(echo "$CSUM" | j "sum(1 for r in d['by_task'] if r['name']=='Carols own task')")" "1"
ok "but not the loose task's"     "$(echo "$CSUM" | j "sum(1 for r in d['by_task'] if r['name']=='Admin faff')")" "0"
# She has a "No project" bucket of her own — she owns a loose task — but it
# must contain only Dave's 25 minutes on it, never Alice's 15 on a loose task
# Carol cannot see.
ok "her loose bucket excludes Alice's" "$(echo "$CSUM" | j "[r['seconds'] for r in d['by_project'] if r['name']=='No project'] == [1500]")" "True"

echo "== the work history"
H=$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/time/entries)
ok "newest first"               "$(echo "$H" | j "d[0]['started_at'] >= d[-1]['started_at']")" "True"
ok "entries name their task"    "$(echo "$H" | j "all(e['task_title'] for e in d)")" "True"
ok "mine=true is only mine"     "$(curl -s -b /tmp/mc.jar "$B/api/organisations/$OID/time/entries?mine=true" | j "{e['user']['email'] for e in d} == {'$C'}")" "True"
ok "carol's history excludes the loose task" "$(curl -s -b /tmp/mc.jar $B/api/organisations/$OID/time/entries | j "sum(1 for e in d if e['task_title']=='Admin faff')")" "0"

echo "== deleting"
ok "delete your own"            "$(code -b /tmp/mc.jar -X DELETE $B/api/organisations/$OID/time/$CEID)" "204"
ok "it is gone"                 "$(curl -s -b /tmp/mc.jar $B/api/organisations/$OID/tasks/$T1/time | j "sum(1 for e in d if e['id']=='$CEID')")" "0"
ok "and the removal is recorded" "$(curl -s -b /tmp/ma.jar $B/api/organisations/$OID/tasks/$T1/events | j "sum(1 for e in d if e['kind']=='time_deleted')")" "1"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
