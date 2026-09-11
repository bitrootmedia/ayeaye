#!/usr/bin/env bash
#
# The changelog: a per-organisation dated log of what happened.
#
#   docker compose up -d && ./scripts/e2e-changelog.sh
#
# Two bars, and the second is the reason this script needs four accounts:
#
#   read/add   any active member
#   edit/del   whoever recorded it, or an org admin
#
# "A member must not be able to rewrite a colleague's entry" is only testable
# between two *plain* members — exactly the shape a single-account test would
# report as working. There is deliberately no third bar: unlike the bookmark
# shelf next door, nothing here pins and nothing reorders, because a log's
# order is its dates.
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
get(){ curl -s -b "$1" "$2"; }
# Bodies are built into a variable first, never written as a literal `{...}`
# with a comma inside a nested `$(...)` capture — bash brace-expands that and
# silently tears one request into two. See CLAUDE.md's e2e-mfa.sh note.
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
patch(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PATCH "$2" -d "$3"; }
pcode(){ curl -s -o /dev/null -w '%{http_code}' -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
ptcode(){ curl -s -o /dev/null -w '%{http_code}' -b "$1" -H 'Content-Type: application/json' -X PATCH "$2" -d "$3"; }
dcode(){ curl -s -o /dev/null -w '%{http_code}' -b "$1" -X DELETE "$2"; }
gcode(){ curl -s -o /dev/null -w '%{http_code}' -b "$1" "$2"; }
# `X-Total-Count` is what makes "Showing 2 of 5" honest rather than a guess.
total(){ curl -s -D - -o /dev/null -b "$1" "$2" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-total-count"{print $2}'; }

OWNER=cl-owner$S@example.com; ADMIN=cl-admin$S@example.com
MEM=cl-member$S@example.com;  MEM2=cl-member2$S@example.com
signup /tmp/cl-owner.jar $OWNER; signup /tmp/cl-admin.jar $ADMIN
signup /tmp/cl-mem.jar $MEM;     signup /tmp/cl-mem2.jar $MEM2

ORG_BODY="{\"name\":\"Ledger $S\"}"
OID=$(post /tmp/cl-owner.jar $B/api/organisations "$ORG_BODY" | j "d['id']")
invite(){ post /tmp/cl-owner.jar $B/api/organisations/$OID/invites "{\"email\":\"$1\",\"role\":\"$2\"}" | j "d['invite_url'].rsplit('/',1)[1]"; }
curl -s -o /dev/null -b /tmp/cl-admin.jar -X POST $B/api/invites/$(invite "$ADMIN" admin)/accept
curl -s -o /dev/null -b /tmp/cl-mem.jar  -X POST $B/api/invites/$(invite "$MEM" member)/accept
curl -s -o /dev/null -b /tmp/cl-mem2.jar -X POST $B/api/invites/$(invite "$MEM2" member)/accept

# A second organisation, to prove the log doesn't reach across the boundary.
ORG2_BODY="{\"name\":\"Ledger2 $S\"}"
OID2=$(post /tmp/cl-owner.jar $B/api/organisations "$ORG2_BODY" | j "d['id']")
# A stranger, to prove the whole screen is 404 rather than empty.
OUT=cl-out$S@example.com; signup /tmp/cl-out.jar $OUT

TODAY=$(python3 -c "import datetime;print(datetime.date.today().isoformat())")
OLD=$(python3 -c "import datetime;print((datetime.date.today()-datetime.timedelta(days=30)).isoformat())")
MID=$(python3 -c "import datetime;print((datetime.date.today()-datetime.timedelta(days=10)).isoformat())")

echo "== recording one"
BODY="{\"description\":\"BingAds version lift\",\"happened_on\":\"$MID\"}"
E1=$(post /tmp/cl-mem.jar $B/api/organisations/$OID/changelog "$BODY")
E1ID=$(echo "$E1" | j "d['id']")
ok "keeps the description"        "$(echo "$E1" | j "d['description']")" "BingAds version lift"
ok "keeps the date it happened"   "$(echo "$E1" | j "d['happened_on']")" "$MID"
ok "records who wrote it down"    "$(echo "$E1" | j "d['added_by']['email']")" "$MEM"
ok "the author may edit it"       "$(echo "$E1" | j "d['can_edit']")" "True"
ok "a plain member can record one" "$(pcode /tmp/cl-mem2.jar $B/api/organisations/$OID/changelog '{"description":"Feed switched to the new endpoint"}')" "201"

echo "== the date is the one being recorded, and defaults to the caller's today"
# Two dates on the row deliberately: `happened_on` is what happened,
# `created_at` is when somebody typed it in. Tuesday's version lift routinely
# gets written down on Thursday.
DEFAULTED=$(post /tmp/cl-owner.jar $B/api/organisations/$OID/changelog '{"description":"Recorded with no date"}')
ok "an omitted date is today"     "$(echo "$DEFAULTED" | j "d['happened_on']")" "$TODAY"
ok "created_at is its own field"  "$(echo "$DEFAULTED" | j "d['created_at'][:10] == '$TODAY'")" "True"

echo "== an entry needs something in it"
ok "an empty description (422)"   "$(pcode /tmp/cl-owner.jar $B/api/organisations/$OID/changelog '{"description":""}')" "422"
ok "whitespace only (422)"        "$(pcode /tmp/cl-owner.jar $B/api/organisations/$OID/changelog '{"description":"   "}')" "422"
# Refused rather than truncated: an entry cut in half says something other
# than what was written.
LONG=$(python3 -c "import json;print(json.dumps({'description':'x'*2001}))")
ok "an oversized one (422)"       "$(pcode /tmp/cl-owner.jar $B/api/organisations/$OID/changelog "$LONG")" "422"
ok "a junk date (422)"            "$(pcode /tmp/cl-owner.jar $B/api/organisations/$OID/changelog '{"description":"When?","happened_on":"not-a-date"}')" "422"

echo "== the log reads newest first, by the date it happened"
OLDBODY="{\"description\":\"The very first thing\",\"happened_on\":\"$OLD\"}"
post /tmp/cl-owner.jar $B/api/organisations/$OID/changelog "$OLDBODY" > /dev/null
LIST=$(get /tmp/cl-mem.jar $B/api/organisations/$OID/changelog)
ok "four entries so far"          "$(echo "$LIST" | j "len(d)")" "4"
ok "newest happened_on first"     "$(echo "$LIST" | j "d[0]['happened_on'] >= d[1]['happened_on'] >= d[2]['happened_on'] >= d[3]['happened_on']")" "True"
ok "the oldest is last"           "$(echo "$LIST" | j "d[-1]['description']")" "The very first thing"
# Same-date entries tie-break on id descending, so the most recently recorded
# of a day comes first rather than the order swapping between requests.
SAME1="{\"description\":\"Same day, recorded first\",\"happened_on\":\"$TODAY\"}"
SAME2="{\"description\":\"Same day, recorded second\",\"happened_on\":\"$TODAY\"}"
post /tmp/cl-owner.jar $B/api/organisations/$OID/changelog "$SAME1" > /dev/null
post /tmp/cl-owner.jar $B/api/organisations/$OID/changelog "$SAME2" > /dev/null
ok "same date ties break newest-recorded first" \
  "$(get /tmp/cl-mem.jar $B/api/organisations/$OID/changelog | j "d[0]['description']")" "Same day, recorded second"

echo "== everybody in the organisation reads the same log"
ok "the owner sees all six"  "$(get /tmp/cl-owner.jar $B/api/organisations/$OID/changelog | j "len(d)")" "6"
ok "an admin sees all six"   "$(get /tmp/cl-admin.jar $B/api/organisations/$OID/changelog | j "len(d)")" "6"
ok "a member sees all six"   "$(get /tmp/cl-mem.jar   $B/api/organisations/$OID/changelog | j "len(d)")" "6"
ok "org2's log is empty"     "$(get /tmp/cl-owner.jar $B/api/organisations/$OID2/changelog | j "len(d)")" "0"
# Not an empty list — a 404, the same "no access reads as 404" rule as
# everywhere else. A stranger must not learn the organisation exists.
ok "a stranger gets 404"     "$(gcode /tmp/cl-out.jar $B/api/organisations/$OID/changelog)" "404"

echo "== paged, and it says what it is a page of"
ok "no limit returns everything"  "$(get /tmp/cl-mem.jar $B/api/organisations/$OID/changelog | j "len(d)")" "6"
ok "a limit returns a page"       "$(get /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog?limit=2" | j "len(d)")" "2"
ok "X-Total-Count is the whole"   "$(total /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog?limit=2")" "6"
ok "and it's there unpaged too"   "$(total /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog")" "6"
ok "offset walks the same order"  "$(get /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog?limit=2&offset=2" | j "d[0]['description']")" \
  "$(get /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog" | j "d[2]['description']")"
ok "past the end is empty"        "$(get /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog?limit=2&offset=99" | j "len(d)")" "0"

echo "== correcting an entry: whoever recorded it, or an org admin"
ok "the author may reword it"     "$(patch /tmp/cl-mem.jar $B/api/organisations/$OID/changelog/$E1ID '{"description":"BingAds version lift (v14)"}' | j "d['description']")" "BingAds version lift (v14)"
ok "the author may redate it"     "$(patch /tmp/cl-mem.jar $B/api/organisations/$OID/changelog/$E1ID "{\"happened_on\":\"$OLD\"}" | j "d['happened_on']")" "$OLD"
# 403 and not 404: every member can see the entry, so pretending it isn't
# there would be the wrong lie.
ok "another member may NOT (403)" "$(ptcode /tmp/cl-mem2.jar $B/api/organisations/$OID/changelog/$E1ID '{"description":"Hijacked"}')" "403"
ok "an admin may (escape hatch)"  "$(patch /tmp/cl-admin.jar $B/api/organisations/$OID/changelog/$E1ID '{"description":"BingAds version lift (v14, corrected)"}' | j "d['description']")" "BingAds version lift (v14, corrected)"
ok "the owner may too"            "$(ptcode /tmp/cl-owner.jar $B/api/organisations/$OID/changelog/$E1ID '{"description":"BingAds version lift"}')" "200"
ok "an edit still refuses empty"  "$(ptcode /tmp/cl-owner.jar $B/api/organisations/$OID/changelog/$E1ID '{"description":"  "}')" "422"
ok "a non-author sees can_edit false" "$(get /tmp/cl-mem2.jar $B/api/organisations/$OID/changelog | j "[e['can_edit'] for e in d if e['id']=='$E1ID'][0]")" "False"
ok "an admin sees can_edit true"      "$(get /tmp/cl-admin.jar $B/api/organisations/$OID/changelog | j "[e['can_edit'] for e in d if e['id']=='$E1ID'][0]")" "True"

echo "== an entry cannot be reached through another organisation's URL"
# Without the organisation scope in get_or_404, somebody who belongs to both
# could edit org1's history through org2's path.
ok "cross-organisation PATCH (404)"  "$(ptcode /tmp/cl-owner.jar $B/api/organisations/$OID2/changelog/$E1ID '{"description":"Wrong ledger"}')" "404"
ok "cross-organisation DELETE (404)" "$(dcode /tmp/cl-owner.jar $B/api/organisations/$OID2/changelog/$E1ID)" "404"
ok "an unknown id (404)"             "$(dcode /tmp/cl-owner.jar $B/api/organisations/$OID/changelog/00000000-0000-7000-8000-000000000000)" "404"

echo "== findable from search, and the filter agrees with it"
# The ⌘K palette and the log's own filter run the *same* matcher
# (`search_service.matches`), which is what makes a hit's link land on a page
# that actually contains it.
HIT=$(get /tmp/cl-mem.jar "$B/api/organisations/$OID/search?q=BingAds")
ok "the entry is a search hit"     "$(echo "$HIT" | j "[h['kind'] for h in d['hits'] if h['kind']=='changelog'][0]")" "changelog"
ok "the title is its first line"   "$(echo "$HIT" | j "[h['title'] for h in d['hits'] if h['kind']=='changelog'][0]")" "BingAds version lift"
ok "the date is the context"       "$(echo "$HIT" | j "[h['context'] for h in d['hits'] if h['kind']=='changelog'][0]")" "$OLD"
ok "the id addresses the entry"    "$(echo "$HIT" | j "[h['id'] for h in d['hits'] if h['kind']=='changelog'][0]")" "$E1ID"
# Typo tolerance is the trigram half doing its job, not an ILIKE.
ok "a typo still matches"          "$(get /tmp/cl-mem.jar "$B/api/organisations/$OID/search?q=BingAdz" | j "sum(1 for h in d['hits'] if h['kind']=='changelog')>0")" "True"
# The organisation boundary, again — search is per organisation like
# everything else.
ok "org2's search finds nothing"   "$(get /tmp/cl-owner.jar "$B/api/organisations/$OID2/search?q=BingAds" | j "sum(1 for h in d['hits'] if h['kind']=='changelog')")" "0"
ok "a stranger's search 404s"      "$(gcode /tmp/cl-out.jar "$B/api/organisations/$OID/search?q=BingAds")" "404"

ok "the list filters on the same q" "$(get /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog?q=BingAds" | j "len(d)")" "1"
ok "and it's the same entry"        "$(get /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog?q=BingAds" | j "d[0]['id']")" "$E1ID"
# The count has to go through the filter too, or "Showing 1 of 6" counts the
# whole log while showing a filtered page of it.
ok "X-Total-Count is filtered too"  "$(total /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog?q=BingAds&limit=1")" "1"
# Deliberately a word sharing no trigram with anything in this log. The
# first attempt used "zzzzznothing", which matched — "thing" is a word in one
# of the entries and `%>` is word-similarity, not substring. That generosity
# is wanted (a search box showing nothing feels broken) and is exactly why
# the filter reuses the search matcher rather than a stricter ILIKE.
ok "an unmatched filter is empty"   "$(get /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog?q=qwxkvbz" | j "len(d)")" "0"
ok "an empty q is not a filter"     "$(get /tmp/cl-mem.jar "$B/api/organisations/$OID/changelog?q=" | j "len(d)")" "6"

echo "== removing one: the same bar as editing"
DELBODY='{"description":"Recorded by mistake"}'
DID=$(post /tmp/cl-mem.jar $B/api/organisations/$OID/changelog "$DELBODY" | j "d['id']")
ok "another member may NOT (403)" "$(dcode /tmp/cl-mem2.jar $B/api/organisations/$OID/changelog/$DID)" "403"
ok "the author may (204)"         "$(dcode /tmp/cl-mem.jar  $B/api/organisations/$OID/changelog/$DID)" "204"
ok "and it's gone"                "$(get /tmp/cl-mem.jar $B/api/organisations/$OID/changelog | j "sum(1 for e in d if e['id']=='$DID')")" "0"
ok "back to six"                  "$(total /tmp/cl-mem.jar $B/api/organisations/$OID/changelog)" "6"

echo
echo "  $pass passed, $fail failed"
[ $fail -eq 0 ]
