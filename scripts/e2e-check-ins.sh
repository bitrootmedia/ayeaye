#!/usr/bin/env bash
#
# "Still working on this?" — services/check_ins.py, end to end.
#
#   docker compose up -d && ./scripts/e2e-check-ins.sh
#
# The sweep is due at a random minute an hour or two out, so this moves the
# clock instead of waiting for it: `next_check_in_at` and `check_in_deadline`
# are pulled into the past with psql, and the sweep is run in the API
# container rather than waited for from the scheduler. Everything else goes
# through the real surfaces — MCP (the menu bar app), REST (the web header)
# and the Telegram webhook, with a chat linked at the database because the
# Bot API can't be reached from a dev stack.
#
# Creates a real account and leaves it behind. Dev stacks only.
set -u
B=http://localhost
S=$(date +%s)
pass=0; fail=0
ok(){ if [ "$2" = "$3" ]; then echo "  ok   $1"; pass=$((pass+1)); else echo "  FAIL $1: expected [$3] got [$2]"; fail=$((fail+1)); fi; }
signup(){ curl -s -c "$1" -o /dev/null -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  -H 'st-auth-mode: cookie' -X POST $B/api/auth/signup \
  -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$2\"},{\"id\":\"password\",\"value\":\"Testpass123\"}]}"; }
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
patch(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PATCH "$2" -d "$3"; }
sql(){ docker compose exec -T postgres psql -U app -d app -tAc "$1"; }
sweep(){ docker compose exec -T -e PYTHONPATH=/app/src api uv run python -c "
import asyncio
from app.tasks.check_ins import sweep_timer_check_ins
asyncio.run(sweep_timer_check_ins())" >/dev/null 2>&1; }
tool(){ # $1 tool  $2 arguments-json
  python3 -c "import json,sys; print(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':sys.argv[1],'arguments':json.loads(sys.argv[2])}}))" "$1" "$2" > /tmp/ci-req.json
  curl -s -X POST $B/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2025-06-18' \
    --data-binary @/tmp/ci-req.json \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result']['content'][0]['text'])"; }
due_now(){ sql "update time_entries set next_check_in_at = now() - interval '1 minute' where ended_at is null and user_id = '$UID_'" >/dev/null; }
expire_now(){ sql "update time_entries set check_in_deadline = now() - interval '1 minute' where ended_at is null and user_id = '$UID_'" >/dev/null; }
webhook(){ # $1 callback data
  python3 -c "import json,sys; print(json.dumps({'update_id':1,'callback_query':{'id':'cb1','data':sys.argv[1],'message':{'message_id':7,'chat':{'id':int(sys.argv[2])},'text':'Still working on it?'}}}))" "$1" "$CHAT" > /tmp/ci-tg.json
  curl -s -o /dev/null -H 'Content-Type: application/json' -X POST $B/api/telegram/webhook --data-binary @/tmp/ci-tg.json; }

ME=ci$S@example.com
signup /tmp/ci.jar $ME
UID_=$(curl -s -b /tmp/ci.jar $B/api/me | j "d['id']")
OID=$(post /tmp/ci.jar $B/api/organisations "{\"name\":\"Watch $S\"}" | j "d['id']")
TID=$(post /tmp/ci.jar $B/api/organisations/$OID/tasks '{"title":"Caulk the deck"}' | j "d['id']")
TOKEN=$(post /tmp/ci.jar $B/api/me/tokens '{"name":"Menu bar","scope":"write"}' | j "d['token']")

echo "== defaults"
ok "on by default, Telegram first" "$(curl -s -b /tmp/ci.jar $B/api/me | j "d['timer_check_ins']")" "telegram"
ok "six a day"                     "$(curl -s -b /tmp/ci.jar $B/api/me | j "d['timer_check_ins_per_day']")" "6"

echo "== starting schedules the first question an hour or two out"
post /tmp/ci.jar $B/api/organisations/$OID/tasks/$TID/time/start '{}' >/dev/null
ok "between 60 and 120 minutes" \
  "$(sql "select next_check_in_at between started_at + interval '60 min' and started_at + interval '120 min' from time_entries where ended_at is null and user_id = '$UID_'")" "t"
ok "nothing asked yet" "$(tool running_timer '{}' | grep -c check_in_deadline)" "0"

echo "== asking"
due_now; sweep
ok "MCP shows the open question"   "$(tool running_timer '{}' | grep -c check_in_deadline=)" "1"
ok "so does the web header"        "$(curl -s -b /tmp/ci.jar $B/api/me/timer | j "d['check_in_deadline'] is not None")" "True"
ok "the deadline is 15–30 min out" \
  "$(sql "select check_in_deadline between check_in_asked_at + interval '15 min' and check_in_asked_at + interval '30 min' from time_entries where ended_at is null and user_id = '$UID_'")" "t"
ok "and it counted against today" "$(sql "select timer_check_ins_count from users where id = '$UID_'")" "1"
sweep
ok "a second sweep doesn't ask again" "$(sql "select timer_check_ins_count from users where id = '$UID_'")" "1"

echo "== yes, from the menu bar"
ok "answered"                     "$(tool answer_check_in '{"still_working": true}')" "Carrying on."
ok "the question is gone"         "$(tool running_timer '{}' | grep -c check_in_deadline)" "0"
ok "the next one is scheduled"    "$(sql "select next_check_in_at > now() + interval '59 min' from time_entries where ended_at is null and user_id = '$UID_'")" "t"
ok "the timer is still running"   "$(curl -s -b /tmp/ci.jar $B/api/me/timer | j "d['entry'] is not None")" "True"

echo "== yes, from the web header"
due_now; sweep
ok "answered" "$(post /tmp/ci.jar $B/api/me/timer/check-in '{"still_working": true}' | j "d['check_in_deadline'] is None and d['entry'] is not None")" "True"

echo "== Telegram's buttons"
CHAT=$((900000000 + S % 100000))
sql "insert into notification_channels (user_id, kind, label, config, enabled_kinds, verified_at) values ('$UID_', 'telegram', 'Telegram', '{\"chat_id\": \"$CHAT\"}', array['timer_paused'], now())" >/dev/null
EID=$(sql "select id from time_entries where ended_at is null and user_id = '$UID_'")
due_now; sweep
webhook "checkin:yes:$EID"
ok "a yes tap carries on"         "$(curl -s -b /tmp/ci.jar $B/api/me/timer | j "d['check_in_deadline'] is None and d['entry'] is not None")" "True"
due_now; sweep
webhook "checkin:yes:00000000-0000-0000-0000-000000000000"
ok "a tap about another timer does nothing" "$(curl -s -b /tmp/ci.jar $B/api/me/timer | j "d['check_in_deadline'] is not None")" "True"
webhook "checkin:stop:$EID"
ok "a stop tap stops it"          "$(curl -s -b /tmp/ci.jar $B/api/me/timer | j "d['entry'] is None")" "True"

echo "== nobody answers"
post /tmp/ci.jar $B/api/organisations/$OID/tasks/$TID/time/start '{}' >/dev/null
due_now; sweep; expire_now; sweep
ok "the timer is paused"          "$(curl -s -b /tmp/ci.jar $B/api/me/timer | j "d['entry'] is None")" "True"
ok "ended when it asked, not at the deadline" \
  "$(sql "select ended_at = check_in_asked_at from time_entries where user_id = '$UID_' order by started_at desc limit 1")" "t"
ok "timer_paused is in the inbox" \
  "$(curl -s -b /tmp/ci.jar $B/api/notifications | j "sum(1 for n in (d['items'] if isinstance(d, dict) else d) if n['kind']=='timer_paused')")" "1"
ok "and the history says why" \
  "$(sql "select count(*) from task_events where task_id = '$TID' and data->>'reason' like 'paused%'")" "1"

echo "== turning it off withdraws an open question"
post /tmp/ci.jar $B/api/organisations/$OID/tasks/$TID/time/start '{}' >/dev/null
due_now; sweep
patch /tmp/ci.jar $B/api/me '{"timer_check_ins": "off"}' >/dev/null
ok "withdrawn"                    "$(curl -s -b /tmp/ci.jar $B/api/me/timer | j "d['check_in_deadline'] is None")" "True"
due_now; sweep
ok "and nothing more is asked"    "$(curl -s -b /tmp/ci.jar $B/api/me/timer | j "d['check_in_deadline'] is None")" "True"
ok "an unknown mode is refused"   "$(curl -s -o /dev/null -w '%{http_code}' -b /tmp/ci.jar -H 'Content-Type: application/json' -X PATCH $B/api/me -d '{"timer_check_ins": "sometimes"}')" "422"

echo "== the daily cap"
patch /tmp/ci.jar $B/api/me '{"timer_check_ins": "apps", "timer_check_ins_per_day": 1}' >/dev/null
sql "update users set timer_check_ins_count = 0, timer_check_ins_day = null where id = '$UID_'" >/dev/null
due_now; sweep
tool answer_check_in '{"still_working": true}' >/dev/null
due_now; sweep
ok "one a day means one"          "$(curl -s -b /tmp/ci.jar $B/api/me/timer | j "d['check_in_deadline'] is None")" "True"
ok "pushed back, not dropped"     "$(sql "select next_check_in_at > now() from time_entries where ended_at is null and user_id = '$UID_'")" "t"
post /tmp/ci.jar $B/api/me/timer/stop '{}' >/dev/null

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
