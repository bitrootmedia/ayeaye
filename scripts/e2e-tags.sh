#!/usr/bin/env bash
#
# Phase 9b: tags, and the one that takes work off the board.
#
#   docker compose up -d && ./scripts/e2e-tags.sh
#
# The interesting half is `off_board`: a knowledge-base item has to leave the
# board without becoming unfindable. Those are two different queries — the
# list and the search — and getting one right without the other produces
# either clutter or a black hole.
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

ADMIN=ga$S@example.com; MEMBER=gm$S@example.com
signup /tmp/ga.jar $ADMIN; signup /tmp/gm.jar $MEMBER

OID=$(post /tmp/ga.jar $B/api/organisations "{\"name\":\"Tags $S\"}" | j "d['id']")
T=$(post /tmp/ga.jar $B/api/organisations/$OID/invites "{\"email\":\"$MEMBER\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/gm.jar -X POST $B/api/invites/$T/accept

echo "== the vocabulary"
TAG=$(post /tmp/gm.jar $B/api/organisations/$OID/tags '{"name":"Rigging"}')
TAG_ID=$(echo "$TAG" | j "d['id']")
ok "a plain member can create one" "$(echo "$TAG" | j "d['name']")" "Rigging"
ok "…on the board by default"      "$(echo "$TAG" | j "d['off_board']")" "False"
# The rule that stops the vocabulary rotting: same word, different case, one tag.
ok "get-or-create is case-insensitive" \
  "$(post /tmp/ga.jar $B/api/organisations/$OID/tags '{"name":"rigging"}' | j "d['id']")" "$TAG_ID"
ok "…and keeps the original casing" \
  "$(post /tmp/ga.jar $B/api/organisations/$OID/tags '{"name":"  RIGGING  "}' | j "d['name']")" "Rigging"
ok "a member may NOT take one off the board" \
  "$(code -b /tmp/gm.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tags -d '{"name":"Reference","off_board":true}')" "403"

KB=$(post /tmp/ga.jar $B/api/organisations/$OID/tags '{"name":"Knowledge base","off_board":true}')
KB_ID=$(echo "$KB" | j "d['id']")
ok "an admin may"                  "$(echo "$KB" | j "d['off_board']")" "True"
ok "a member may NOT rename one"   "$(code -b /tmp/gm.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/tags/$KB_ID -d '{"name":"KB"}')" "403"
ok "nor delete one"                "$(code -b /tmp/gm.jar -X DELETE $B/api/organisations/$OID/tags/$KB_ID)" "403"

echo "== tagging a task"
TID=$(post /tmp/ga.jar $B/api/organisations/$OID/tasks "{\"title\":\"Splice the mainbrace $S\"}" | j "d['id']")
ok "apply by name"              "$(post /tmp/ga.jar $B/api/organisations/$OID/tasks/$TID/tags '{"name":"Rigging"}' | j "[t['name'] for t in d]")" "['Rigging']"
ok "applying twice is a no-op"  "$(post /tmp/ga.jar $B/api/organisations/$OID/tasks/$TID/tags '{"name":"Rigging"}' | j "len(d)")" "1"
ok "it rides along on the task" "$(curl -s -b /tmp/ga.jar $B/api/organisations/$OID/tasks/$TID | j "[t['name'] for t in d['tags']]")" "['Rigging']"
ok "and on the board"           "$(curl -s -b /tmp/ga.jar $B/api/organisations/$OID/tasks | j "[t['tags'] for t in d if t['id']=='$TID'][0][0]['name']")" "Rigging"
ok "the count follows"          "$(curl -s -b /tmp/ga.jar $B/api/organisations/$OID/tags | j "[t['task_count'] for t in d if t['id']=='$TAG_ID'][0]")" "1"

echo "== off the board, but not out of reach"
DOC=$(post /tmp/ga.jar $B/api/organisations/$OID/tasks "{\"title\":\"How the winch works $S\"}" | j "d['id']")
board(){ curl -s -b /tmp/ga.jar "$B/api/organisations/$OID/tasks${1:-}" | j "sum(1 for t in d if t['id']=='$DOC')"; }
ok "on the board before tagging" "$(board)" "1"
post /tmp/ga.jar $B/api/organisations/$OID/tasks/$DOC/tags '{"name":"Knowledge base"}' >/dev/null
ok "gone from the board"         "$(board)" "0"
ok "…and from the project view"  "$(board '?loose=true')" "0"
ok "but there when you ask for the tag" "$(board "?tag_id=$KB_ID")" "1"
ok "…or ask for everything"      "$(board '?include_off_board=true')" "1"
ok "still fetchable directly"    "$(code -b /tmp/ga.jar $B/api/organisations/$OID/tasks/$DOC)" "200"
ok "still in search by title"    "$(curl -s -b /tmp/ga.jar "$B/api/organisations/$OID/search?q=winch+works+$S" | j "sum(1 for h in d['hits'] if h['id']=='$DOC')")" "1"
# The point of tagging: the word you filed it under finds it.
ok "and findable BY THE TAG"     "$(curl -s -b /tmp/ga.jar "$B/api/organisations/$OID/search?q=Knowledge" | j "sum(1 for h in d['hits'] if h['id']=='$DOC')")" "1"
ok "an ordinary tag also matches" "$(curl -s -b /tmp/ga.jar "$B/api/organisations/$OID/search?q=Rigging" | j "sum(1 for h in d['hits'] if h['id']=='$TID')")" "1"

echo "== the label comes off, the work stays"
ok "untag"                      "$(code -b /tmp/ga.jar -X DELETE $B/api/organisations/$OID/tasks/$DOC/tags/$KB_ID)" "204"
ok "back on the board"          "$(board)" "1"
post /tmp/ga.jar $B/api/organisations/$OID/tasks/$DOC/tags '{"name":"Knowledge base"}' >/dev/null
ok "deleting the tag frees it"  "$(code -b /tmp/ga.jar -X DELETE $B/api/organisations/$OID/tags/$KB_ID)" "204"
ok "…and the task is untouched" "$(code -b /tmp/ga.jar $B/api/organisations/$OID/tasks/$DOC)" "200"
ok "…and back on the board"     "$(board)" "1"

echo "== tags don't leak access"
ok "a member can't see an untagged private task" \
  "$(code -b /tmp/gm.jar $B/api/organisations/$OID/tasks/$TID)" "404"
ok "…nor find it by its tag"    "$(curl -s -b /tmp/gm.jar "$B/api/organisations/$OID/search?q=Rigging" | j "sum(1 for h in d['hits'] if h['id']=='$TID')")" "0"
ok "though the tag itself is shared vocabulary" \
  "$(curl -s -b /tmp/gm.jar $B/api/organisations/$OID/tags | j "sum(1 for t in d if t['id']=='$TAG_ID')")" "1"

echo "== renaming"
ok "an admin renames it"        "$(patch /tmp/ga.jar $B/api/organisations/$OID/tags/$TAG_ID '{"name":"Rigging work"}' | j "d['name']")" "Rigging work"
ok "the task follows"           "$(curl -s -b /tmp/ga.jar $B/api/organisations/$OID/tasks/$TID | j "[t['name'] for t in d['tags']]")" "['Rigging work']"
post /tmp/ga.jar $B/api/organisations/$OID/tags '{"name":"Sails"}' >/dev/null
ok "a colliding rename is refused" \
  "$(code -b /tmp/ga.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/tags/$TAG_ID -d '{"name":"sails"}')" "409"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
