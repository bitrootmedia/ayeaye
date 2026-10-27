#!/usr/bin/env bash
#
# The weekly report: Monday's summary of last week, for organisation admins.
#
#   docker compose up -d && ./scripts/e2e-weekly-report.sh
#
# Proves what the unit tests can't: who gets claimed (admins with it on, at
# their hour, on a Monday, once), that the report is the admin's own view —
# a member's hidden task and a private draft are missing from it the way they
# are missing from the board — and that it arrives as an email.
#
# The sweep is driven with an injected "now" rather than waiting for Monday.
# Creates real accounts and leaves them behind. Dev stacks only: needs Mailpit.
set -u
B=http://localhost
M=http://localhost:8025
S=$(date +%s)
pass=0; fail=0
ok(){ if [ "$2" = "$3" ]; then echo "  ok   $1"; pass=$((pass+1)); else echo "  FAIL $1: expected [$3] got [$2]"; fail=$((fail+1)); fi; }
signup(){ curl -s -c "$1" -o /dev/null -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  -H 'st-auth-mode: cookie' -X POST $B/api/auth/signup \
  -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$2\"},{\"id\":\"password\",\"value\":\"Testpass123\"}]}"; }
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "${3:-{\}}"; }
patch(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PATCH "$2" -d "$3"; }
sql(){ docker compose exec -T postgres psql -U app -d app -tAc "$1" | tr -d '\r'; }

# A zone nobody else on a dev stack is in, so the claim touches only us.
TZ_NAME=Pacific/Chatham

# alice = owner, bob = admin who turned it off, carol = member.
A=ra$S@example.com; BB=rb$S@example.com; C=rc$S@example.com
signup /tmp/ra.jar $A; signup /tmp/rb.jar $BB; signup /tmp/rc.jar $C
OID=$(post /tmp/ra.jar $B/api/organisations "{\"name\":\"Weekly $S\"}" | j "d['id']")
join(){ T=$(post /tmp/ra.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"$3\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/rb.jar $BB admin
join /tmp/rc.jar $C member
for jar in /tmp/ra.jar /tmp/rb.jar /tmp/rc.jar; do
  patch $jar $B/api/me "{\"timezone\":\"$TZ_NAME\",\"daily_summary_hour\":6}" >/dev/null
done

echo "== the setting"
ok "on by default"                 "$(curl -s -b /tmp/ra.jar $B/api/me | j "d['weekly_report_enabled']")" "True"
ok "bob turns it off"              "$(patch /tmp/rb.jar $B/api/me '{"weekly_report_enabled":false}' | j "d['weekly_report_enabled']")" "False"
ok "the email channel routes it"   "$(curl -s -b /tmp/ra.jar $B/api/me/notification-channels | j "[c for c in d if c['kind']=='email'][0]['enabled_kinds'].count('weekly_report')")" "1"

echo "== last week's work"
T_OPEN=$(post /tmp/ra.jar $B/api/organisations/$OID/tasks '{"title":"Sand the hull"}' | j "d['id']")
T_DONE=$(post /tmp/rc.jar $B/api/organisations/$OID/tasks '{"title":"Order varnish"}' | j "d['id']")
post /tmp/rc.jar $B/api/organisations/$OID/tasks/$T_DONE/closed '{"closed":true}' >/dev/null
T_HID=$(post /tmp/rc.jar $B/api/organisations/$OID/tasks '{"title":"Private errand"}' | j "d['id']")
post /tmp/rc.jar $B/api/organisations/$OID/tasks/$T_HID/hidden '{"hidden":true}' >/dev/null
T_NOW=$(post /tmp/ra.jar $B/api/organisations/$OID/tasks '{"title":"This week, not last"}' | j "d['id']")

# Wednesday of last week, midday UTC — inside "last week" in any zone.
WED=$(python3 -c "import datetime as d; t=d.date.today(); print(t-d.timedelta(days=t.weekday()+5))")
post /tmp/rc.jar $B/api/organisations/$OID/tasks/$T_DONE/time "{\"minutes\":90,\"started_at\":\"${WED}T09:00:00Z\"}" >/dev/null
post /tmp/ra.jar $B/api/organisations/$OID/tasks/$T_OPEN/time "{\"minutes\":30,\"started_at\":\"${WED}T13:00:00Z\"}" >/dev/null
post /tmp/rc.jar $B/api/organisations/$OID/tasks/$T_HID/time "{\"minutes\":45,\"started_at\":\"${WED}T15:00:00Z\"}" >/dev/null

BOOK=$(post /tmp/ra.jar $B/api/organisations/$OID/kb/books '{"name":"Boatyard"}' | j "d['id']")
ART=$(post /tmp/ra.jar $B/api/organisations/$OID/kb/books/$BOOK/articles '{"title":"Varnishing in winter"}' | j "d['id']")
patch /tmp/ra.jar $B/api/organisations/$OID/kb/articles/$ART/private '{"is_private": false}' >/dev/null
DRAFT=$(post /tmp/ra.jar $B/api/organisations/$OID/kb/books/$BOOK/articles '{"title":"Unfinished draft"}' | j "d['id']")
post /tmp/ra.jar $B/api/organisations/$OID/kb/books/$BOOK/facts '{"body":"Varnish needs 10°C or warmer to cure; below that it stays tacky for days."}' >/dev/null

sql "UPDATE tasks SET created_at = '${WED} 12:00Z' WHERE id IN ('$T_OPEN','$T_DONE','$T_HID')" >/dev/null
sql "UPDATE tasks SET closed_at = '${WED} 16:00Z' WHERE id = '$T_DONE'" >/dev/null
sql "UPDATE articles SET created_at = '${WED} 12:00Z' WHERE id IN ('$ART','$DRAFT')" >/dev/null
sql "UPDATE facts SET created_at = '${WED} 12:00Z' WHERE book_id = '$BOOK'" >/dev/null

# The sweep, with "now" set to this Monday at 06:xx in the zone — or a
# Tuesday, to prove it waits.
sweep(){ docker compose exec -T -e PYTHONPATH=/app/src api uv run --no-sync python - "$1" "$TZ_NAME" "$S" <<'PY'
import asyncio, sys
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.db import SessionLocal
from app.models import User
from app.services import weekly_report as w
from app.tasks.weekly_report import send

day, tz_name, stamp = sys.argv[1], sys.argv[2], sys.argv[3]
tz = ZoneInfo(tz_name)
today = datetime.now(tz).date()
monday = today - timedelta(days=today.weekday())
when = monday + timedelta(days=1 if day == "tuesday" else 0)
now = datetime.combine(when, time(6, 20), tzinfo=tz)

async def main():
    async with SessionLocal() as db:
        ids = await w.claim(db, tz_name=tz_name, now=now)
        mine = (await db.execute(select(User.email).where(User.id.in_(ids)))).scalars().all()
        names = sorted(e.split("@")[0][:2] for e in mine if stamp in e)
        sent = 0
        for uid in ids:
            sent += await send(db, uid)
        print(",".join(names) or "nobody")

asyncio.run(main())
PY
}

echo "== who gets one"
ok "not on a Tuesday"              "$(sweep tuesday)" "nobody"
ok "Monday: the owner, not the admin who opted out, not the member" "$(sweep monday)" "ra"
ok "and only once"                 "$(sweep monday)" "nobody"

echo "== what it says"
N=$(curl -s -b /tmp/ra.jar "$B/api/notifications" | python3 -c "
import json,sys
d=json.load(sys.stdin); d=d.get('items', d) if isinstance(d, dict) else d
print(json.dumps([n for n in d if n['kind']=='weekly_report']))")
ok "one report in the inbox"       "$(echo "$N" | j "len(d)")" "1"
BODY=$(echo "$N" | j "d[0]['body']")
ok "titled for the org"            "$(echo "$N" | j "d[0]['title'].endswith('in Weekly $S')")" "True"
ok "links to the work report"      "$(echo "$N" | j "'/reports?since=' in d[0]['link_path']")" "True"
ok "the headline"                  "$(echo "$BODY" | head -1)" "2h logged · 2 tasks opened · 1 closed · 1 articles · 1 facts"
ok "hours by person"               "$(echo "$BODY" | grep -c "^- rc$S@example.com: 1h 30m\$")" "1"
ok "opened, with its owner"        "$(echo "$BODY" | grep -c "^- Sand the hull (ra$S@example.com)\$")" "1"
ok "closed"                        "$(echo "$BODY" | grep -A1 'Tasks closed' | grep -c 'Order varnish')" "1"
ok "the article and its book"      "$(echo "$BODY" | grep -c '^- Varnishing in winter (Boatyard)$')" "1"
ok "the fact"                      "$(echo "$BODY" | grep -c '^- Varnish needs 10°C')" "1"
ok "not the hidden task"           "$(echo "$BODY" | grep -c 'Private errand')" "0"
ok "nor its 45 minutes"            "$(echo "$BODY" | grep -c '2h 45m\|2h 15m')" "0"
ok "not the draft"                 "$(echo "$BODY" | grep -c 'Unfinished draft')" "0"
ok "not this week's task"          "$(echo "$BODY" | grep -c 'This week, not last')" "0"

GOT=""
for _ in $(seq 1 20); do
  GOT=$(curl -s "$M/api/v1/messages?limit=50" | TO="$A" python3 -c "
import json, os, sys
for m in json.load(sys.stdin).get('messages', []):
    if m['To'][0]['Address'] == os.environ['TO'] and 'Week of' in m['Subject']:
        print('yes'); break" 2>/dev/null)
  [ -n "$GOT" ] && break
  sleep 1
done
ok "and it arrived as an email"    "${GOT:-no}" "yes"

echo "== a quiet organisation sends nothing"
QUIET=$(post /tmp/rc.jar $B/api/organisations "{\"name\":\"Quiet $S\"}" | j "d['id']")
sql "UPDATE users SET last_weekly_report_sent_on = NULL WHERE email = '$C'" >/dev/null
ok "carol owns an empty one, and is claimed" "$(sweep monday)" "rc"
ok "but gets no report"            "$(curl -s -b /tmp/rc.jar "$B/api/notifications" | python3 -c "
import json,sys
d=json.load(sys.stdin); d=d.get('items', d) if isinstance(d, dict) else d
print(sum(n['kind']=='weekly_report' for n in d))")" "0"

echo
echo "pass=$pass fail=$fail"
[ $fail -eq 0 ]
