#!/usr/bin/env bash
#
# Phase 9c: private notes.
#
#   docker compose up -d && ./scripts/e2e-notes.sh
#
# One thing is being proved here, from every angle somebody might come at it:
# **nobody else can read your note.** Not the task's owner, not an
# organisation admin, not through search. There is no endpoint that takes a
# user id, so the test is that the same URL returns different things to
# different people — and never somebody else's words.
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
put(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PUT "$2" -d "$3"; }

ADMIN=na$S@example.com; OWNER=no$S@example.com; MATE=nm$S@example.com
signup /tmp/na.jar $ADMIN; signup /tmp/no.jar $OWNER; signup /tmp/nm.jar $MATE

OID=$(post /tmp/na.jar $B/api/organisations "{\"name\":\"Notes $S\"}" | j "d['id']")
join(){ T=$(post /tmp/na.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/no.jar $OWNER; join /tmp/nm.jar $MATE
MATE_ID=$(curl -s -b /tmp/na.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$MATE'][0]")

# The owner's task, shared with the mate so they can both open it.
TID=$(post /tmp/no.jar $B/api/organisations/$OID/tasks "{\"title\":\"Shared work $S\"}" | j "d['id']")
post /tmp/no.jar $B/api/organisations/$OID/tasks/$TID/access "{\"user_id\":\"$MATE_ID\",\"level\":\"write\"}" >/dev/null

note(){ curl -s -b "$1" $B/api/organisations/$OID/tasks/$TID/note | j "d['body']"; }

echo "== writing one"
ok "starts empty"               "$(note /tmp/nm.jar)" ""
ok "the mate writes theirs"     "$(put /tmp/nm.jar $B/api/organisations/$OID/tasks/$TID/note "{\"body\":\"mizzenmast\"}" | j "d['body']")" "mizzenmast"
ok "and reads it back"          "$(note /tmp/nm.jar)" "mizzenmast"
ok "it is stamped"              "$(curl -s -b /tmp/nm.jar $B/api/organisations/$OID/tasks/$TID/note | j "d['updated_at'] is not None")" "True"

echo "== and nobody else sees it"
ok "the TASK OWNER sees nothing"    "$(note /tmp/no.jar)" ""
ok "the ORG ADMIN sees nothing"     "$(note /tmp/na.jar)" ""
put /tmp/no.jar $B/api/organisations/$OID/tasks/$TID/note "{\"body\":\"binnacle\"}" >/dev/null
ok "each keeps their own"           "$(note /tmp/nm.jar)" "mizzenmast"
ok "…and the owner theirs"          "$(note /tmp/no.jar)" "binnacle"

echo "== searchable, but only by their author"
find_note(){ curl -s -b "$1" "$B/api/organisations/$OID/search?q=$2" | j "sum(1 for h in d['hits'] if h['kind']=='note')"; }
ok "the mate finds their own"       "$(find_note /tmp/nm.jar "mizzenmast")" "1"
# The owner has a note of their own on the same task, so "no hits" would pass
# for the wrong reason. Assert on the body: whatever they get back is theirs.
ok "…and only their own"            "$(curl -s -b /tmp/nm.jar "$B/api/organisations/$OID/search?q=binnacle" | j "sum(1 for h in d['hits'] if h['kind']=='note')")" "0"
ok "the OWNER cannot find it"       "$(find_note /tmp/no.jar "mizzenmast")" "0"
ok "the ADMIN cannot find it"       "$(find_note /tmp/na.jar "mizzenmast")" "0"
ok "the hit links to the task"      "$(curl -s -b /tmp/nm.jar "$B/api/organisations/$OID/search?q=mizzenmast" | j "[h['id'] for h in d['hits'] if h['kind']=='note'][0]")" "$TID"

echo "== clearing it"
ok "an empty body removes it"   "$(put /tmp/nm.jar $B/api/organisations/$OID/tasks/$TID/note '{"body":"   "}' | j "d['body']")" ""
ok "…and it stops matching"     "$(find_note /tmp/nm.jar "mizzenmast")" "0"
ok "writing again is fine"      "$(put /tmp/nm.jar $B/api/organisations/$OID/tasks/$TID/note '{"body":"back"}' | j "d['body']")" "back"
ok "saving twice does not collide" "$(put /tmp/nm.jar $B/api/organisations/$OID/tasks/$TID/note '{"body":"again"}' | j "d['body']")" "again"

echo "== you still need to be able to see the task"
LOOSE=$(post /tmp/no.jar $B/api/organisations/$OID/tasks "{\"title\":\"Private work $S\"}" | j "d['id']")
ok "no task, no note"           "$(code -b /tmp/nm.jar $B/api/organisations/$OID/tasks/$LOOSE/note)" "404"
ok "nor may they write one"     "$(code -b /tmp/nm.jar -H 'Content-Type: application/json' -X PUT $B/api/organisations/$OID/tasks/$LOOSE/note -d '{"body":"nope"}')" "404"
# Losing sight of the task takes the note with it — not deleted, unreachable.
post /tmp/no.jar $B/api/organisations/$OID/tasks/$TID/hidden '{"hidden":true}' >/dev/null
ok "hiding the task hides the note" "$(code -b /tmp/nm.jar $B/api/organisations/$OID/tasks/$TID/note)" "404"
ok "…and drops it from search"      "$(find_note /tmp/nm.jar "again")" "0"
post /tmp/no.jar $B/api/organisations/$OID/tasks/$TID/hidden '{"hidden":false}' >/dev/null
ok "un-hiding brings it back"       "$(note /tmp/nm.jar)" "again"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
