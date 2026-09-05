#!/usr/bin/env bash
#
# Per-organisation notification email, with the account address as fallback.
#
#   docker compose up -d && ./scripts/e2e-notification-emails.sh
#
# The rule itself is a pure function with its own unit tests
# (tests/test_notification_routing.py). What only this can show is that the
# rule is actually consulted on the way out — so this reads Mailpit and
# asserts on the address a real notification was **delivered to**, not on
# what the API said it would do.
#
# Dev stacks only: needs Mailpit on :8025, which compose.override.yml
# provides and a production stack does not.
set -u
B=http://localhost
M=http://localhost:8025
S=$(date +%s)
pass=0; fail=0
ok(){ if [ "$2" = "$3" ]; then echo "  ok   $1"; pass=$((pass+1)); else echo "  FAIL $1: expected [$3] got [$2]"; fail=$((fail+1)); fi; }

signup(){ curl -s -c "$1" -o /dev/null -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  -H 'st-auth-mode: cookie' -X POST $B/api/auth/signup \
  -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$2\"},{\"id\":\"password\",\"value\":\"Testpass123\"}]}"; }
code(){ curl -s -o /dev/null -w '%{http_code}' "$@"; }
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
put(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PUT "$2" -d "$3"; }
# Bodies with more than one key go in a variable first, never inline inside a
# "$(...)" capture — see CLAUDE.md. Twice now that trap has produced a
# *passing* assertion from a request that never happened.
body(){ python3 -c "import json,sys; print(json.dumps(dict(a.split('=',1) for a in sys.argv[1:])))" "$@"; }

# Who a notification about $1 was actually delivered to.
#
# Reads the recent list and matches the subject here rather than asking
# Mailpit's own `?query=` to do it: that endpoint does not match a
# multi-word phrase the way you would expect, and the first version of this
# reported "(nothing arrived)" for two emails that had in fact both arrived
# at exactly the right addresses. A search that quietly matches nothing is
# indistinguishable from the feature being broken.
#
# Retried rather than slept-on, because delivery is a queued job.
delivered_to(){
  for _ in $(seq 1 20); do
    found=$(curl -s "$M/api/v1/messages?limit=50" | SUBJECT="$1" python3 -c "
import json, os, sys
want = os.environ['SUBJECT']
for m in json.load(sys.stdin).get('messages', []):
    if want in m.get('Subject', ''):
        print(m['To'][0]['Address'])
        break
" 2>/dev/null)
    [ -n "$found" ] && { echo "$found"; return; }
    sleep 1
  done
  echo "(nothing arrived)"
}

OWNER=ne-owner$S@example.com; MATE=ne-mate$S@example.com
signup /tmp/neo.jar $OWNER; signup /tmp/nem.jar $MATE

# Two organisations, so "per organisation" means something.
ONE=$(post /tmp/neo.jar $B/api/organisations "{\"name\":\"Alpha $S\"}" | j "d['id']")
TWO=$(post /tmp/neo.jar $B/api/organisations "{\"name\":\"Beta $S\"}" | j "d['id']")
for OID in $ONE $TWO; do
  T=$(post /tmp/neo.jar $B/api/organisations/$OID/invites "$(body email=$MATE role=member)" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b /tmp/nem.jar -c /tmp/nem.jar -X POST $B/api/invites/$T/accept
done
MATE_ID=$(curl -s -b /tmp/neo.jar $B/api/organisations/$ONE/members | j "[m['user_id'] for m in d if m['email']=='$MATE'][0]")

echo "== every organisation you're in is listed, override or not"
LIST=$(curl -s -b /tmp/nem.jar $B/api/me/notification-emails)
ok "both organisations"        "$(echo "$LIST" | j "len(d)")" "2"
ok "no override yet"           "$(echo "$LIST" | j "[o['email'] for o in d]")" "[None, None]"
ok "…so mail goes to the account" "$(echo "$LIST" | j "sorted({o['effective'] for o in d})")" "['$MATE']"

echo "== asking for one does NOT start using it"
# The whole point of the confirmation step: an address nobody has proved
# they can read is not somewhere this will send mail.
ALIAS=ne-alias$S@example.com
put /tmp/nem.jar $B/api/me/notification-emails/$ONE "$(body email=$ALIAS)" >/dev/null
LIST=$(curl -s -b /tmp/nem.jar $B/api/me/notification-emails)
ok "it is pending"             "$(echo "$LIST" | j "[o['pending'] for o in d if o['organisation_id']=='$ONE'][0]")" "$ALIAS"
ok "…and not yet the override" "$(echo "$LIST" | j "[o['email'] for o in d if o['organisation_id']=='$ONE'][0]")" "None"
ok "…so mail still goes to the account" "$(echo "$LIST" | j "[o['effective'] for o in d if o['organisation_id']=='$ONE'][0]")" "$MATE"

echo "== confirming it is what switches it over"
CONFIRM_TOKEN=$(for _ in $(seq 1 25); do
  found=$(curl -s "$M/api/v1/messages?limit=30" | TO="$ALIAS" python3 -c "
import json, os, sys, urllib.request
want = os.environ['TO']
for m in json.load(sys.stdin).get('messages', []):
    if m['To'][0]['Address'] != want or 'Confirm this address' not in m['Subject']:
        continue
    raw = json.loads(urllib.request.urlopen('http://localhost:8025/api/v1/message/' + m['ID']).read())
    for word in raw.get('Text', '').split():
        if '/notification-email/' in word:
            print(word.rsplit('/', 1)[1])
            break
    break
" 2>/dev/null)
  [ -n "$found" ] && { echo "$found"; break; }
  sleep 1
done)
ok "a confirmation email arrived" "$([ -n "$CONFIRM_TOKEN" ] && echo yes || echo no)" "yes"
# Unauthenticated on purpose: the link is read in whichever inbox it was
# sent to, which is very often a different browser.
ok "the link confirms it"      "$(curl -s -X POST $B/api/notification-emails/confirm/$CONFIRM_TOKEN | j "d['email']")" "$ALIAS"
LIST=$(curl -s -b /tmp/nem.jar $B/api/me/notification-emails)
ok "Alpha overridden now"      "$(echo "$LIST" | j "[o['effective'] for o in d if o['organisation_id']=='$ONE'][0]")" "$ALIAS"
ok "nothing left pending"      "$(echo "$LIST" | j "[o['pending'] for o in d if o['organisation_id']=='$ONE'][0]")" "None"
ok "the link is single-use"    "$(code -X POST $B/api/notification-emails/confirm/$CONFIRM_TOKEN)" "404"
ok "a made-up token is 404"    "$(code -X POST $B/api/notification-emails/confirm/not-a-real-token)" "404"
ok "Beta still the account"    "$(echo "$LIST" | j "[o['effective'] for o in d if o['organisation_id']=='$TWO'][0]")" "$MATE"

echo "== and the mail actually goes there"
# Action-required is the quickest real notification to provoke: the owner
# asks the colleague to act, which notifies them.
SUBJ_ONE="Alpha routing $S"
BODY_ONE="$(body title="$SUBJ_ONE" action_required_user_id=$MATE_ID)"
post /tmp/neo.jar $B/api/organisations/$ONE/tasks "$BODY_ONE" >/dev/null
ok "Alpha's notification went to the override" "$(delivered_to "$SUBJ_ONE")" "$ALIAS"

SUBJ_TWO="Beta routing $S"
BODY_TWO="$(body title="$SUBJ_TWO" action_required_user_id=$MATE_ID)"
post /tmp/neo.jar $B/api/organisations/$TWO/tasks "$BODY_TWO" >/dev/null
ok "Beta's went to the account address"        "$(delivered_to "$SUBJ_TWO")" "$MATE"

echo "== clearing it goes back to the account address"
put /tmp/nem.jar $B/api/me/notification-emails/$ONE '{"email":""}' >/dev/null
ok "override cleared"          "$(curl -s -b /tmp/nem.jar $B/api/me/notification-emails | j "[o['email'] for o in d if o['organisation_id']=='$ONE'][0]")" "None"
ok "effective is the account"  "$(curl -s -b /tmp/nem.jar $B/api/me/notification-emails | j "[o['effective'] for o in d if o['organisation_id']=='$ONE'][0]")" "$MATE"

echo "== it is yours alone"
ok "nonsense is refused"       "$(code -b /tmp/nem.jar -H 'Content-Type: application/json' -X PUT $B/api/me/notification-emails/$ONE -d '{"email":"not-an-address"}')" "422"
STRANGER=ne-stranger$S@example.com; signup /tmp/nes.jar $STRANGER
ok "a stranger can't set one for an org they're not in" "$(code -b /tmp/nes.jar -H 'Content-Type: application/json' -X PUT $B/api/me/notification-emails/$ONE -d "{\"email\":\"$ALIAS\"}")" "404"
ok "…and their own list is empty" "$(curl -s -b /tmp/nes.jar $B/api/me/notification-emails | j "len(d)")" "0"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
