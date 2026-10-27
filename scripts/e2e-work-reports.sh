#!/usr/bin/env bash
#
# Work reports end-to-end: the admin gate, clipping to the window, the user
# filter, a hidden task staying hidden, and "right now".
#
#   docker compose up -d && ./scripts/e2e-work-reports.sh
#
# `tests/test_work_report_rules.py` proves the arithmetic — spreading an
# entry over hours and days, the viewer's zone. This proves the parts that
# live in SQL and HTTP: who may ask, and that the report composes the same
# access as everything else rather than widening it for admins.
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

# alice = owner, bob = admin, carol + dave = plain members.
A=wa$S@example.com; BB=wb$S@example.com; C=wc$S@example.com; D=wd$S@example.com
signup /tmp/wa.jar $A; signup /tmp/wb.jar $BB; signup /tmp/wc.jar $C; signup /tmp/wd.jar $D

OID=$(post /tmp/wa.jar $B/api/organisations "{\"name\":\"Reports $S\"}" | j "d['id']")
join(){ T=$(post /tmp/wa.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"$3\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/wb.jar $BB admin
join /tmp/wc.jar $C member
join /tmp/wd.jar $D member
uid(){ curl -s -b /tmp/wa.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$1'][0]"; }
CUID=$(uid $C); DUID=$(uid $D)

PID=$(post /tmp/wa.jar $B/api/organisations/$OID/projects '{"name":"Refit"}' | j "d['id']")
T1=$(post /tmp/wa.jar $B/api/organisations/$OID/tasks "{\"title\":\"Sand the hull\",\"project_id\":\"$PID\"}" | j "d['id']")
# Shared with carol and dave so they can log against it.
post /tmp/wa.jar $B/api/organisations/$OID/projects/$PID/access "{\"user_id\":\"$CUID\",\"level\":\"write\"}" >/dev/null
post /tmp/wa.jar $B/api/organisations/$OID/projects/$PID/access "{\"user_id\":\"$DUID\",\"level\":\"write\"}" >/dev/null

TODAY=$(date -u +%Y-%m-%d)
YDAY=$(python3 -c "import datetime;print((datetime.date.fromisoformat('$TODAY')-datetime.timedelta(days=1)).isoformat())")
TWOAGO=$(python3 -c "import datetime;print((datetime.date.fromisoformat('$TODAY')-datetime.timedelta(days=2)).isoformat())")

# Carol: 90 minutes yesterday at 09:00 UTC, and 60 minutes across midnight
# into today (23:30 yesterday → 00:30 today).
post /tmp/wc.jar $B/api/organisations/$OID/tasks/$T1/time "{\"minutes\":90,\"started_at\":\"${YDAY}T09:00:00Z\"}" >/dev/null
post /tmp/wc.jar $B/api/organisations/$OID/tasks/$T1/time "{\"minutes\":60,\"started_at\":\"${YDAY}T23:30:00Z\"}" >/dev/null
# Dave: 30 minutes two days ago, and a timer running now.
post /tmp/wd.jar $B/api/organisations/$OID/tasks/$T1/time "{\"minutes\":30,\"started_at\":\"${TWOAGO}T14:00:00Z\"}" >/dev/null
post /tmp/wd.jar $B/api/organisations/$OID/tasks/$T1/time/start >/dev/null

# Carol's own task, hidden — an admin cannot see it, so its hours are not in
# the report either.
HID=$(post /tmp/wc.jar $B/api/organisations/$OID/tasks '{"title":"Private errand"}' | j "d['id']")
post /tmp/wc.jar $B/api/organisations/$OID/tasks/$HID/time "{\"minutes\":45,\"started_at\":\"${YDAY}T12:00:00Z\"}" >/dev/null
post /tmp/wc.jar $B/api/organisations/$OID/tasks/$HID/hidden '{"hidden":true}' >/dev/null

R=$B/api/organisations/$OID/reports
echo "== who may ask"
ok "the owner may"                  "$(code -b /tmp/wa.jar "$R/work?tz=UTC")" "200"
ok "an admin may"                   "$(code -b /tmp/wb.jar "$R/work?tz=UTC")" "200"
ok "a member is refused, 403"       "$(code -b /tmp/wc.jar "$R/work?tz=UTC")" "403"
ok "and from right now too"         "$(code -b /tmp/wc.jar "$R/now")" "403"
ok "an outsider gets a 404"         "$(code -b /tmp/wc.jar "$B/api/organisations/00000000-0000-7000-8000-000000000000/reports/work")" "404"

echo "== clipping to the window"
ONE="$R/work?tz=UTC&since=$YDAY&until=$YDAY&user_id=$CUID"
# 90 minutes, plus the 30 minutes of the overnight entry before midnight.
ok "yesterday is 120 minutes of carol"   "$(curl -s -b /tmp/wb.jar "$ONE" | j "d['total_seconds']//60")" "120"
ok "one day in the chart"               "$(curl -s -b /tmp/wb.jar "$ONE" | j "len(d['by_day'])")" "1"
ok "the 09:00 hour holds an hour"       "$(curl -s -b /tmp/wb.jar "$ONE" | j "sum(r[9] for r in d['by_hour'])//60")" "60"
ok "the 23:00 hour holds half of one"   "$(curl -s -b /tmp/wb.jar "$ONE" | j "sum(r[23] for r in d['by_hour'])//60")" "30"
ok "the entry spanning midnight is listed" "$(curl -s -b /tmp/wb.jar "$ONE" | j "d['entries_total']")" "2"

echo "== the user filter"
WEEK="$R/work?tz=UTC&since=$TWOAGO&until=$YDAY"
ok "both people in the range"        "$(curl -s -b /tmp/wb.jar "$WEEK" | j "len(d['by_person'])")" "2"
ok "filtered to dave"                "$(curl -s -b /tmp/wb.jar "$WEEK&user_id=$DUID" | j "[p['id'] for p in d['by_person']]==['$DUID']")" "True"
ok "two user_ids, both people"       "$(curl -s -b /tmp/wb.jar "$WEEK&user_id=$DUID&user_id=$CUID" | j "len(d['by_person'])")" "2"

echo "== a hidden task stays hidden"
ok "its title is nowhere in the report" "$(curl -s -b /tmp/wb.jar "$WEEK" | grep -c 'Private errand')" "0"
# 90 + the 30 minutes before midnight; the hidden 45 would make it 165.
ok "nor its 45 minutes"              "$(curl -s -b /tmp/wb.jar "$WEEK&user_id=$CUID" | j "d['total_seconds']//60")" "120"

echo "== nonsense in the URL"
ok "a backwards range is a 422"      "$(code -b /tmp/wb.jar "$R/work?since=$YDAY&until=$TWOAGO")" "422"
ok "an unknown zone reads as UTC"    "$(curl -s -b /tmp/wb.jar "$R/work?tz=Mars/Olympus" | j "d['tz']")" "UTC"
ok "an unreadable date is the default" "$(curl -s -b /tmp/wb.jar "$R/work?since=yesterday" | j "len(d['by_day'])")" "7"

echo "== right now"
NOW=$(curl -s -b /tmp/wb.jar "$R/now")
ok "every active member is listed"   "$(echo "$NOW" | j "len(d)")" "4"
ok "dave is first, and running"      "$(echo "$NOW" | j "d[0]['user']['id']=='$DUID' and d[0]['running']['task_title']")" "Sand the hull"
ok "carol is not running anything"   "$(echo "$NOW" | j "[r['running'] for r in d if r['user']['id']=='$CUID'][0]")" "None"
curl -s -b /tmp/wa.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/tasks/$T1 -d '{"status":"in_progress"}' >/dev/null
ok "alice has her in-progress task"  "$(curl -s -b /tmp/wb.jar "$R/now" | j "[r['in_progress'][0]['title'] for r in d if r['user']['email']=='$A'][0]")" "Sand the hull"
post /tmp/wd.jar $B/api/me/timer/stop >/dev/null
ok "stopping clears it"              "$(curl -s -b /tmp/wb.jar "$R/now" | j "[r['running'] for r in d if r['user']['id']=='$DUID'][0]")" "None"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
