#!/usr/bin/env bash
#
# Phase 9d: reminders, and the sweep that fires them.
#
#   docker compose up -d && ./scripts/e2e-reminders.sh
#
# The sweep is the part that can't be checked by hand: it runs hourly, and its
# failure mode — sending the same nudge twice — only shows up in everybody's
# inbox at once. So this drives it directly, twice, and asserts the second run
# does nothing. That claim is the whole reason `notified_ahead_at` and
# `notified_due_at` exist.
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

TODAY=$(date +%F)
TOMORROW=$(python3 -c "import datetime;print(datetime.date.today()+datetime.timedelta(days=1))")
NEXTWEEK=$(python3 -c "import datetime;print(datetime.date.today()+datetime.timedelta(days=7))")

ME=ra$S@example.com; OTHER=rb$S@example.com
signup /tmp/ra.jar $ME; signup /tmp/rb.jar $OTHER
# UTC on both, so the sweep's per-timezone pass is deterministic here.
patch /tmp/ra.jar $B/api/me '{"timezone":"UTC"}' >/dev/null
patch /tmp/rb.jar $B/api/me '{"timezone":"UTC"}' >/dev/null

OID=$(post /tmp/ra.jar $B/api/organisations "{\"name\":\"Remind $S\"}" | j "d['id']")
T=$(post /tmp/ra.jar $B/api/organisations/$OID/invites "{\"email\":\"$OTHER\",\"role\":\"admin\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/rb.jar -X POST $B/api/invites/$T/accept

TID=$(post /tmp/ra.jar $B/api/organisations/$OID/tasks "{\"title\":\"Chase the yard $S\"}" | j "d['id']")

echo "== setting one"
R=$(post /tmp/ra.jar $B/api/organisations/$OID/tasks/$TID/reminders "{\"remind_on\":\"$NEXTWEEK\",\"note\":\"ring them\"}")
RID=$(echo "$R" | j "d['id']")
ok "created"                    "$(echo "$R" | j "d['remind_on']")" "$NEXTWEEK"
ok "not overdue yet"            "$(echo "$R" | j "d['overdue']")" "False"
ok "on the task"                "$(curl -s -b /tmp/ra.jar $B/api/organisations/$OID/tasks/$TID/reminders | j "len(d)")" "1"
ok "and in my own list"         "$(curl -s -b /tmp/ra.jar $B/api/reminders | j "sum(1 for r in d if r['id']=='$RID')")" "1"
ok "the badge is quiet"         "$(curl -s -b /tmp/ra.jar $B/api/reminders/due-count | j "d['count']")" "0"

echo "== it is mine and nobody else's"
# The other account is an ORG ADMIN and can see the task perfectly well.
ok "the admin sees the task"    "$(code -b /tmp/rb.jar $B/api/organisations/$OID/tasks/$TID)" "200"
ok "…but no reminder on it"     "$(curl -s -b /tmp/rb.jar $B/api/organisations/$OID/tasks/$TID/reminders | j "len(d)")" "0"
ok "…and none in their list"    "$(curl -s -b /tmp/rb.jar $B/api/reminders | j "len(d)")" "0"
ok "…and cannot touch mine"     "$(code -b /tmp/rb.jar -X DELETE $B/api/reminders/$RID)" "404"

echo "== today counts as due"
DUE=$(post /tmp/ra.jar $B/api/organisations/$OID/tasks/$TID/reminders "{\"remind_on\":\"$TODAY\",\"note\":\"today\"}")
DUE_ID=$(echo "$DUE" | j "d['id']")
ok "overdue immediately"        "$(echo "$DUE" | j "d['overdue']")" "True"
ok "the badge turns red"        "$(curl -s -b /tmp/ra.jar $B/api/reminders/due-count | j "d['count']")" "1"

echo "== the sweep, twice"
SOON=$(post /tmp/ra.jar $B/api/organisations/$OID/tasks/$TID/reminders "{\"remind_on\":\"$TOMORROW\",\"note\":\"tomorrow\"}" | j "d['id']")
# `-e PYTHONPATH`: compose exec does not inherit the service's environment
# block, and the app lives under /app/src.
sweep(){ docker compose exec -T -e PYTHONPATH=/app/src api uv run python -c "
import asyncio
from app.tasks.reminders import sweep_reminders
asyncio.run(sweep_reminders())
" >/dev/null 2>&1; }
count_kind(){ curl -s -b /tmp/ra.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='$1')"; }
sweep
ok "the one due today fired"    "$(count_kind reminder_due)" "1"
ok "tomorrow's got its warning" "$(count_kind reminder_soon)" "1"
# The claim. This is the assertion the columns exist for.
sweep
sweep
ok "a second sweep sends nothing"     "$(count_kind reminder_due)" "1"
ok "…nor a third"                     "$(count_kind reminder_soon)" "1"

echo "== dismissing, and snoozing"
ok "mark it done"               "$(patch /tmp/ra.jar $B/api/reminders/$DUE_ID '{"done":true}' | j "d['id']")" "$DUE_ID"
ok "it leaves the list"         "$(curl -s -b /tmp/ra.jar $B/api/reminders | j "sum(1 for r in d if r['id']=='$DUE_ID')")" "0"
ok "and the badge clears"       "$(curl -s -b /tmp/ra.jar $B/api/reminders/due-count | j "d['count']")" "0"
# Moving a reminder to a new day has to arm it again, or snoozing is a way to
# silence something permanently by accident.
patch /tmp/ra.jar $B/api/reminders/$SOON "{\"remind_on\":\"$TODAY\"}" >/dev/null
sweep
ok "a moved reminder fires again"     "$(count_kind reminder_due)" "2"

echo "== housekeeping"
ok "the note can be edited"     "$(patch /tmp/ra.jar $B/api/reminders/$RID '{"note":"ring the yard"}' | j "d['note']")" "ring the yard"
ok "deleting works"             "$(code -b /tmp/ra.jar -X DELETE $B/api/reminders/$RID)" "204"
ok "…and it's gone"             "$(curl -s -b /tmp/ra.jar $B/api/reminders | j "sum(1 for r in d if r['id']=='$RID')")" "0"
# A reminder hangs off work. Lose the work, lose sight of the reminder.
NEW=$(post /tmp/ra.jar $B/api/organisations/$OID/tasks/$TID/reminders "{\"remind_on\":\"$NEXTWEEK\"}" | j "d['id']")
curl -s -o /dev/null -b /tmp/ra.jar -X DELETE $B/api/organisations/$OID/tasks/$TID
ok "deleting the task takes it" "$(curl -s -b /tmp/ra.jar $B/api/reminders | j "sum(1 for r in d if r['id']=='$NEW')")" "0"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
