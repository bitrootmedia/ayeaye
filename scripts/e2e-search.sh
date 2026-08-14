#!/usr/bin/env bash
#
# Search: fuzziness, ranking, and — the part that matters — permissions.
#
#   docker compose up -d && ./scripts/e2e-search.sh
#
# A search box is the easiest place in a product to leak data: it reads across
# every table at once, and a result that shouldn't be there looks exactly like
# one that should. So most of this file is about what does NOT come back.
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
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
# urlencode the query so spaces and punctuation survive the round trip.
find(){ curl -s -b "$1" -G --data-urlencode "q=$3" "$B/api/organisations/$2/search"; }
titles(){ j "sorted(h['title'] for h in d['hits'])"; }
count(){ j "sum(1 for h in d['hits'] if h['title']=='$1')"; }

A=sa$S@example.com; BB=sb$S@example.com; C=sc$S@example.com
signup /tmp/sa.jar $A; signup /tmp/sb.jar $BB; signup /tmp/sc.jar $C

OID=$(post /tmp/sa.jar $B/api/organisations "{\"name\":\"Search $S\"}" | j "d['id']")
join(){ T=$(post /tmp/sa.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"$3\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/sb.jar $BB admin
join /tmp/sc.jar $C member
uid(){ curl -s -b /tmp/sa.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$1'][0]"; }
CUID=$(uid $C)

# Alice's private project, with tasks nobody else has been given.
PID=$(post /tmp/sa.jar $B/api/organisations/$OID/projects \
  '{"name":"Antifouling programme","description":"Hull coatings and abrasives"}' | j "d['id']")
post /tmp/sa.jar $B/api/organisations/$OID/tasks \
  "{\"title\":\"Strip the old antifoul\",\"project_id\":\"$PID\",\"description\":\"Needs a 40-grit disc and the orbital sander\"}" >/dev/null
post /tmp/sa.jar $B/api/organisations/$OID/tasks \
  "{\"title\":\"Order two-part epoxy\",\"project_id\":\"$PID\"}" >/dev/null
# A loose task — no project at all.
post /tmp/sa.jar $B/api/organisations/$OID/tasks \
  '{"title":"Chase the chandlery invoice"}' >/dev/null

echo "== it finds things"
ok "exact word"                 "$(find /tmp/sa.jar $OID 'antifoul' | count 'Strip the old antifoul')" "1"
ok "prefix, mid-typing"         "$(find /tmp/sa.jar $OID 'antif' | count 'Strip the old antifoul')" "1"
ok "from the third character"   "$(find /tmp/sa.jar $OID 'ant' | count 'Strip the old antifoul')" "1"
ok "matches inside a word"      "$(find /tmp/sa.jar $OID 'foul' | count 'Strip the old antifoul')" "1"
ok "finds the project too"      "$(find /tmp/sa.jar $OID 'antifoul' | count 'Antifouling programme')" "1"
ok "searches descriptions"      "$(find /tmp/sa.jar $OID 'orbital' | count 'Strip the old antifoul')" "1"
ok "finds loose tasks"          "$(find /tmp/sa.jar $OID 'chandlery' | count 'Chase the chandlery invoice')" "1"
ok "case-insensitive"           "$(find /tmp/sa.jar $OID 'ANTIFOUL' | count 'Strip the old antifoul')" "1"

echo "== fuzzy: typos still land"
ok "transposed letters"         "$(find /tmp/sa.jar $OID 'antifuol' | count 'Strip the old antifoul')" "1"
ok "missing letter"             "$(find /tmp/sa.jar $OID 'chandlry' | count 'Chase the chandlery invoice')" "1"
ok "wrong letter"               "$(find /tmp/sa.jar $OID 'epoxi' | count 'Order two-part epoxy')" "1"

echo "== it doesn't find nonsense"
ok "unrelated query: nothing"   "$(find /tmp/sa.jar $OID 'zzzzqqqq' | j "len(d['hits'])")" "0"
ok "empty query: nothing"       "$(curl -s -b /tmp/sa.jar "$B/api/organisations/$OID/search?q=" | j "len(d['hits'])")" "0"
ok "whitespace only: nothing"   "$(find /tmp/sa.jar $OID '   ' | j "len(d['hits'])")" "0"

echo "== permissions: the part that must not be wrong"
# Carol is an ordinary member with no grant on anything.
ok "member sees no tasks"       "$(find /tmp/sc.jar $OID 'antifoul' | j "len(d['hits'])")" "0"
ok "member sees no loose task"  "$(find /tmp/sc.jar $OID 'chandlery' | j "len(d['hits'])")" "0"
ok "member sees no project"     "$(find /tmp/sc.jar $OID 'programme' | j "len(d['hits'])")" "0"
ok "member cannot search descriptions either" "$(find /tmp/sc.jar $OID 'orbital' | j "len(d['hits'])")" "0"
# Bob is an org admin, so he sees everything.
ok "admin sees them"            "$(find /tmp/sb.jar $OID 'antifoul' | j "len(d['hits'])")" "2"

echo "== granting makes them appear, immediately"
post /tmp/sa.jar $B/api/organisations/$OID/projects/$PID/access "{\"user_id\":\"$CUID\",\"level\":\"read\"}" >/dev/null
ok "project grant, tasks appear" "$(find /tmp/sc.jar $OID 'antifoul' | count 'Strip the old antifoul')" "1"
ok "and the project itself"      "$(find /tmp/sc.jar $OID 'antifoul' | count 'Antifouling programme')" "1"
ok "still not the loose task"    "$(find /tmp/sc.jar $OID 'chandlery' | j "len(d['hits'])")" "0"

echo "== revoking removes them, immediately"
# No index to fall out of date: this is the whole argument for staying in
# Postgres rather than shipping documents to a search engine.
GID=$(curl -s -b /tmp/sa.jar $B/api/organisations/$OID/projects/$PID/access | j "d['grants'][0]['id']")
curl -s -o /dev/null -b /tmp/sa.jar -X DELETE $B/api/organisations/$OID/projects/$PID/access/$GID
ok "gone from search at once"    "$(find /tmp/sc.jar $OID 'antifoul' | j "len(d['hits'])")" "0"

echo "== being asked to act makes it findable"
TID=$(curl -s -b /tmp/sa.jar "$B/api/organisations/$OID/tasks?loose=true" | j "[t['id'] for t in d if t['title']=='Chase the chandlery invoice'][0]")
curl -s -o /dev/null -b /tmp/sa.jar -H 'Content-Type: application/json' -X PATCH \
  $B/api/organisations/$OID/tasks/$TID -d "{\"action_required_user_id\":\"$CUID\"}"
ok "action-required can find it" "$(find /tmp/sc.jar $OID 'chandlery' | count 'Chase the chandlery invoice')" "1"
curl -s -o /dev/null -b /tmp/sa.jar -H 'Content-Type: application/json' -X PATCH \
  $B/api/organisations/$OID/tasks/$TID -d '{"action_required_user_id":null}'
ok "clearing it hides it again"  "$(find /tmp/sc.jar $OID 'chandlery' | j "len(d['hits'])")" "0"

echo "== ranking"
ok "title beats description"    "$(find /tmp/sa.jar $OID 'antifoul' | j "d['hits'][0]['title']")" "Strip the old antifoul"
ok "a snippet explains the hit" "$(find /tmp/sa.jar $OID 'orbital' | j "'orbital' in (d['hits'][0]['subtitle'] or '')")" "True"
ok "results carry their kind"   "$(find /tmp/sa.jar $OID 'antifoul' | j "sorted({h['kind'] for h in d['hits']})")" "['project', 'task']"
ok "a task names its project"   "$(find /tmp/sa.jar $OID 'epoxy' | j "d['hits'][0]['context']")" "Antifouling programme"

echo "== closed and archived are found, and flagged"
curl -s -o /dev/null -b /tmp/sa.jar -H 'Content-Type: application/json' -X POST \
  $B/api/organisations/$OID/tasks/$TID/closed -d '{"closed":true}'
ok "closed task still findable" "$(find /tmp/sa.jar $OID 'chandlery' | count 'Chase the chandlery invoice')" "1"
ok "and marked inactive"        "$(find /tmp/sa.jar $OID 'chandlery' | j "d['hits'][0]['inactive']")" "True"

echo "== cross-organisation isolation"
OTHER=$(post /tmp/sc.jar $B/api/organisations "{\"name\":\"Elsewhere $S\"}" | j "d['id']")
post /tmp/sc.jar $B/api/organisations/$OTHER/tasks '{"title":"Strip the old antifoul"}' >/dev/null
ok "own org only"               "$(find /tmp/sc.jar $OTHER 'antifoul' | j "len(d['hits'])")" "1"
ok "non-member: 404"            "$(curl -s -o /dev/null -w '%{http_code}' -b /tmp/sa.jar -G --data-urlencode 'q=antifoul' $B/api/organisations/$OTHER/search)" "404"

echo "== it is fast"
# Not a benchmark — a tripwire. As-you-type means one request per keystroke,
# so anything approaching a second here is a different design problem.
T0=$(python3 -c "import time; print(time.time())")
for _ in 1 2 3 4 5; do find /tmp/sa.jar $OID 'antif' >/dev/null; done
T1=$(python3 -c "import time; print(time.time())")
MS=$(python3 -c "print(int((float('$T1')-float('$T0'))*1000/5))")
echo "  ..   ${MS}ms per search (round trip, 5 runs)"
ok "under 250ms per search"     "$(python3 -c "print($MS < 250)")" "True"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
