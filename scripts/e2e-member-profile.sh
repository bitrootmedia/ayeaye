#!/usr/bin/env bash
#
# A colleague's profile: when to reach them, and what they're on.
#
#   docker compose up -d && ./scripts/e2e-member-profile.sh
#
# The person is membership-scoped (status line, timezone, working hours,
# out-of-office); their work is scoped to the *viewer's* task access, and so
# is their running timer. A profile that showed more than the task list
# would be a hole in the access model. See services/profiles.py.
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

ADMIN=mpa$S@example.com; BOB=mpb$S@example.com; DAVE=mpd$S@example.com; CAROL=mpc$S@example.com
signup /tmp/mpa.jar $ADMIN; signup /tmp/mpb.jar $BOB; signup /tmp/mpd.jar $DAVE; signup /tmp/mpc.jar $CAROL

OID=$(post /tmp/mpa.jar $B/api/organisations "{\"name\":\"Profiles $S\"}" | j "d['id']")
join(){ T=$(post /tmp/mpa.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/mpb.jar $BOB
join /tmp/mpd.jar $DAVE
# Carol never joins — the stranger.

BOB_ID=$(curl -s -b /tmp/mpb.jar $B/api/me | j "d['id']")
DAVE_ID=$(curl -s -b /tmp/mpd.jar $B/api/me | j "d['id']")
P="$B/api/organisations/$OID/members/$BOB_ID/profile"

# Bob describes himself.
patch /tmp/mpb.jar $B/api/me '{"status_message":"Heads-down on the refit","timezone":"Europe/Warsaw"}' >/dev/null
curl -s -o /dev/null -b /tmp/mpb.jar -X PUT $B/api/me/working-hours/0/9
curl -s -o /dev/null -b /tmp/mpb.jar -X PUT $B/api/me/working-hours/0/10
TODAY=$(date +%F)
post /tmp/mpb.jar $B/api/me/out-of-office "{\"starts_on\":\"$TODAY\",\"ends_on\":\"$TODAY\",\"note\":\"dentist\"}" >/dev/null

# Bob's work: one task shared with Dave, one private, one hidden.
PID=$(post /tmp/mpb.jar $B/api/organisations/$OID/projects '{"name":"Bob private"}' | j "d['id']")
T1=$(post /tmp/mpb.jar $B/api/organisations/$OID/tasks "{\"title\":\"Shared with Dave\",\"project_id\":\"$PID\"}" | j "d['id']")
T2=$(post /tmp/mpb.jar $B/api/organisations/$OID/tasks "{\"title\":\"Private to Bob\",\"project_id\":\"$PID\"}" | j "d['id']")
T3=$(post /tmp/mpb.jar $B/api/organisations/$OID/tasks "{\"title\":\"Hidden\",\"project_id\":\"$PID\"}" | j "d['id']")
post /tmp/mpb.jar $B/api/organisations/$OID/tasks/$T1/access "{\"user_id\":\"$DAVE_ID\",\"level\":\"read\"}" >/dev/null
post /tmp/mpb.jar $B/api/organisations/$OID/tasks/$T3/hidden '{"hidden":true}' >/dev/null
post /tmp/mpb.jar $B/api/organisations/$OID/tasks/$T2/time/start '{}' >/dev/null

echo "== the person, to any member"
ok "status line"           "$(curl -s -b /tmp/mpd.jar $P | j "d['status_message']")" "Heads-down on the refit"
ok "timezone"              "$(curl -s -b /tmp/mpd.jar $P | j "d['timezone']")" "Europe/Warsaw"
ok "working hours"         "$(curl -s -b /tmp/mpd.jar $P | j "len(d['working_hours'])")" "2"
ok "role"                  "$(curl -s -b /tmp/mpd.jar $P | j "d['role']")" "member"
ok "away today"            "$(curl -s -b /tmp/mpd.jar $P | j "(len(d['away']), d['away'][0]['away_now'], d['away'][0]['note'])")" "(1, True, 'dentist')"

echo "== their work, only as far as the viewer can see"
ok "a member sees only the task shared with them" \
                           "$(curl -s -b /tmp/mpd.jar $P | j "([t['title'] for t in d['open_tasks']], d['open_total'])")" "(['Shared with Dave'], 1)"
ok "an admin sees the private one too, never the hidden one" \
                           "$(curl -s -b /tmp/mpa.jar $P | j "(sorted(t['title'] for t in d['open_tasks']), d['open_total'])")" "(['Private to Bob', 'Shared with Dave'], 2)"
ok "their own profile shows the hidden one to them" \
                           "$(curl -s -b /tmp/mpb.jar $P | j "d['open_total']")" "3"
ok "owned, from their side" "$(curl -s -b /tmp/mpd.jar $P | j "d['open_tasks'][0]['is_owner']")" "True"

echo "== the running timer follows task access"
ok "the admin sees what it's on" \
                           "$(curl -s -b /tmp/mpa.jar $P | j "d['working_on']['task']['title']")" "Private to Bob"
ok "the member, who can't see that task, sees nothing" \
                           "$(curl -s -b /tmp/mpd.jar $P | j "str(d['working_on'])")" "None"
post /tmp/mpb.jar $B/api/organisations/$OID/tasks/$T1/time/start '{}' >/dev/null
ok "moved to a task they can see, now they can" \
                           "$(curl -s -b /tmp/mpd.jar $P | j "d['working_on']['task']['title']")" "Shared with Dave"
post /tmp/mpb.jar $B/api/me/timer/stop '{}' >/dev/null

echo "== recently closed"
post /tmp/mpb.jar $B/api/organisations/$OID/tasks/$T1/closed '{"closed":true}' >/dev/null
ok "closing moves it across" \
                           "$(curl -s -b /tmp/mpd.jar $P | j "(d['open_total'], [t['title'] for t in d['recently_closed']])")" "(0, ['Shared with Dave'])"

echo "== not a member is 404"
ok "a stranger"            "$(code -b /tmp/mpc.jar $P)" "404"
ok "a made-up user id"     "$(code -b /tmp/mpd.jar $B/api/organisations/$OID/members/00000000-0000-7000-8000-000000000000/profile)" "404"
ok "someone who exists but isn't in this org" \
                           "$(code -b /tmp/mpd.jar $B/api/organisations/$OID/members/$(curl -s -b /tmp/mpc.jar $B/api/me | j "d['id']")/profile)" "404"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
