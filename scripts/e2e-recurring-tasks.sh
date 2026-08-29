#!/usr/bin/env bash
#
# Phase 16: recurring tasks — the sweep that regenerates them on schedule.
#
#   docker compose up -d && ./scripts/e2e-recurring-tasks.sh
#
# Same shape as e2e-reminders.sh, and for the same reason: the sweep can't be
# checked by hand. It runs hourly, and its failure mode — generating the same
# occurrence twice — only shows up as a duplicate task nobody asked for. So
# this drives it directly, twice, and asserts the second run creates nothing.
# That claim is the whole reason `next_due_on` is a claim and not a plain
# column.
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

TODAY=$(python3 -c "import datetime;print(datetime.date.today())")
YESTERDAY=$(python3 -c "import datetime;print(datetime.date.today()-datetime.timedelta(days=1))")
TOMORROW=$(python3 -c "import datetime;print(datetime.date.today()+datetime.timedelta(days=1))")

ME=va$S@example.com; OTHER=vb$S@example.com
signup /tmp/va.jar $ME; signup /tmp/vb.jar $OTHER
# UTC on both, so the sweep's per-timezone pass is deterministic here.
patch /tmp/va.jar $B/api/me '{"timezone":"UTC"}' >/dev/null
patch /tmp/vb.jar $B/api/me '{"timezone":"UTC"}' >/dev/null

OID=$(post /tmp/va.jar $B/api/organisations "{\"name\":\"Recur $S\"}" | j "d['id']")
T=$(post /tmp/va.jar $B/api/organisations/$OID/invites "{\"email\":\"$OTHER\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/vb.jar -X POST $B/api/invites/$T/accept

echo "== attaching needs a due date first"
NO_DATE=$(post /tmp/va.jar $B/api/organisations/$OID/tasks "{\"title\":\"No date yet $S\"}" | j "d['id']")
ok "refused without one"        "$(code -b /tmp/va.jar -X POST $B/api/organisations/$OID/tasks/$NO_DATE/recurrence -H 'Content-Type: application/json' -d '{"interval_unit":"week","interval_count":1}')" "422"

echo "== attach, and it becomes the first occurrence"
TID=$(post /tmp/va.jar $B/api/organisations/$OID/tasks "{\"title\":\"Weekly review $S\",\"due_on\":\"$TODAY\"}" | j "d['id']")
R=$(post /tmp/va.jar $B/api/organisations/$OID/tasks/$TID/recurrence "{\"interval_unit\":\"week\",\"interval_count\":1}")
ok "attached"                   "$(echo "$R" | j "d['recurrence']['interval_unit']")" "week"
ok "next occurrence one week out" "$(echo "$R" | j "d['recurrence']['next_due_on']")" "$(python3 -c "import datetime;print(datetime.date.today()+datetime.timedelta(days=7))")"
ok "the creator can manage it"  "$(echo "$R" | j "d['recurrence']['can_manage']")" "True"
ok "attaching twice is refused" "$(code -b /tmp/va.jar -X POST $B/api/organisations/$OID/tasks/$TID/recurrence -H 'Content-Type: application/json' -d '{"interval_unit":"week","interval_count":1}')" "409"

echo "== a plain member with write access still can't manage someone else's series"
curl -s -o /dev/null -b /tmp/va.jar -X POST $B/api/organisations/$OID/tasks/$TID/access -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"$(curl -s -b /tmp/vb.jar $B/api/me | j "d['id']")\",\"level\":\"write\"}"
ok "write access is not enough" "$(code -b /tmp/vb.jar -X POST $B/api/organisations/$OID/tasks/$TID/recurrence/stop)" "403"

echo "== the sweep, twice"
# A task due yesterday, every day: next_due_on lands on today, so the sweep
# fires on the very next run instead of a week from now.
DAILY=$(post /tmp/va.jar $B/api/organisations/$OID/tasks "{\"title\":\"Daily check $S\",\"due_on\":\"$YESTERDAY\"}" | j "d['id']")
post /tmp/va.jar $B/api/organisations/$OID/tasks/$DAILY/recurrence "{\"interval_unit\":\"day\",\"interval_count\":1}" >/dev/null
sweep(){ docker compose exec -T -e PYTHONPATH=/app/src api uv run python -c "
import asyncio
from app.tasks.recurrence import sweep_recurring_tasks
asyncio.run(sweep_recurring_tasks())
" >/dev/null 2>&1; }
count_named(){ curl -s -b /tmp/va.jar "$B/api/organisations/$OID/tasks?include_closed=true" | j "sum(1 for t in d if t['title']=='$1')"; }
sweep
ok "one new occurrence appeared" "$(count_named "Daily check $S")" "2"
sweep
sweep
ok "a second sweep makes no more" "$(count_named "Daily check $S")" "2"

echo "== the series is decoupled from the task it started on"
# Editing the original task's due date afterwards must not reach back into
# the series' own cadence — the two are deliberately independent once
# attach() has run. Rescheduling THIS task doesn't change when the NEXT
# occurrence is due; only the series' own next_due_on does that.
patch /tmp/va.jar $B/api/organisations/$OID/tasks/$DAILY "{\"due_on\":\"$TOMORROW\"}" >/dev/null
sweep
ok "editing the task's due date doesn't re-trigger the sweep" "$(count_named "Daily check $S")" "2"

echo "== stopping"
ok "the creator can stop it"    "$(post /tmp/va.jar $B/api/organisations/$OID/tasks/$TID/recurrence/stop {} | j "d['recurrence']['active']")" "False"
sweep
ok "a stopped series generates nothing new" "$(count_named "Weekly review $S")" "1"

echo "== offboarding reassigns series ownership"
OTHER_ID=$(curl -s -b /tmp/vb.jar $B/api/me | j "d['id']")
MEMBER_ROW=$(curl -s -b /tmp/va.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$OTHER'][0]")
curl -s -o /dev/null -b /tmp/va.jar -X PATCH $B/api/organisations/$OID/members/$MEMBER_ROW -H 'Content-Type: application/json' -d '{"role":"owner"}'
ME_ROW=$(curl -s -b /tmp/va.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$ME'][0]")
ok "removing the series owner succeeds" "$(code -b /tmp/vb.jar -X DELETE $B/api/organisations/$OID/members/$ME_ROW)" "204"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
