#!/usr/bin/env bash
#
# Bookmarks: the organisation's shared shelf of links.
#
#   docker compose up -d && ./scripts/e2e-bookmarks.sh
#
# Three bars, and they are different from each other — which is the whole
# reason this script needs four accounts:
#
#   read/add   any active member
#   edit/del   whoever added it, or an org admin
#   pin        the organisation's OWNER, and not even an admin
#
# The middle one is only testable between two plain members (a member must
# not be able to rewrite a colleague's link), and the last one is only
# testable with an admin who is not the owner. Both are exactly the shapes a
# single-account test would report as working.
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
# Bodies are built into a variable first, never written as a literal `{...}`
# with a comma inside a nested `$(...)` capture — bash brace-expands that and
# silently tears one request into two. See CLAUDE.md's e2e-mfa.sh note.
pcode(){ curl -s -o /dev/null -w '%{http_code}' -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
ptcode(){ curl -s -o /dev/null -w '%{http_code}' -b "$1" -H 'Content-Type: application/json' -X PATCH "$2" -d "$3"; }

OWNER=bm-owner$S@example.com; ADMIN=bm-admin$S@example.com
MEM=bm-member$S@example.com;  MEM2=bm-member2$S@example.com
signup /tmp/bm-owner.jar $OWNER; signup /tmp/bm-admin.jar $ADMIN
signup /tmp/bm-mem.jar $MEM;     signup /tmp/bm-mem2.jar $MEM2

OID=$(post /tmp/bm-owner.jar $B/api/organisations "{\"name\":\"Shelf $S\"}" | j "d['id']")
invite(){ post /tmp/bm-owner.jar $B/api/organisations/$OID/invites "{\"email\":\"$1\",\"role\":\"$2\"}" | j "d['invite_url'].rsplit('/',1)[1]"; }
curl -s -o /dev/null -b /tmp/bm-admin.jar -X POST $B/api/invites/$(invite "$ADMIN" admin)/accept
curl -s -o /dev/null -b /tmp/bm-mem.jar  -X POST $B/api/invites/$(invite "$MEM" member)/accept
curl -s -o /dev/null -b /tmp/bm-mem2.jar -X POST $B/api/invites/$(invite "$MEM2" member)/accept

# A second organisation, to prove the list doesn't reach across the boundary.
OID2=$(post /tmp/bm-owner.jar $B/api/organisations "{\"name\":\"Shelf2 $S\"}" | j "d['id']")

echo "== adding one"
BM=$(post /tmp/bm-mem.jar $B/api/organisations/$OID/bookmarks "{\"url\":\"https://example.com/runbook\",\"description\":\"The deploy runbook\"}")
BID=$(echo "$BM" | j "d['id']")
ok "returns the url and description" "$(echo "$BM" | j "d['url']+'|'+d['description']")" "https://example.com/runbook|The deploy runbook"
ok "starts unpinned"                 "$(echo "$BM" | j "d['pinned']")" "False"
ok "records who added it"            "$(echo "$BM" | j "d['added_by']['email']")" "$MEM"
ok "the author may edit it"          "$(echo "$BM" | j "d['can_edit']")" "True"
ok "a plain member can add one"      "$(pcode /tmp/bm-mem2.jar $B/api/organisations/$OID/bookmarks '{"url":"https://example.com/wiki"}')" "201"
ok "description defaults to empty"   "$(post /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks '{"url":"https://example.com/drive"}' | j "d['description']")" ""

echo "== a url is normalised, and only http(s) is stored"
ok "a bare hostname gains https://"  "$(post /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks '{"url":"example.org/handbook"}' | j "d['url']")" "https://example.org/handbook"
ok "a host:port is not a scheme"     "$(post /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks '{"url":"localhost:3000/admin"}' | j "d['url']")" "https://localhost:3000/admin"
# The one that matters: the list renders every row as a real <a href>, so a
# stored javascript: URL is stored XSS waiting for the next colleague.
ok "javascript: is refused (422)"    "$(pcode /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks '{"url":"javascript:alert(1)"}')" "422"
ok "data: is refused (422)"          "$(pcode /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks '{"url":"data:text/html,<script>1</script>"}')" "422"
ok "an empty url is refused (422)"   "$(pcode /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks '{"url":""}')" "422"

echo "== everybody in the organisation sees the same shelf"
ok "the owner sees all five"  "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "len(d)")" "5"
ok "an admin sees all five"   "$(curl -s -b /tmp/bm-admin.jar $B/api/organisations/$OID/bookmarks | j "len(d)")" "5"
ok "a member sees all five"   "$(curl -s -b /tmp/bm-mem.jar  $B/api/organisations/$OID/bookmarks | j "len(d)")" "5"
ok "org2's shelf is empty"   "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID2/bookmarks | j "len(d)")" "0"

echo "== editing: whoever added it, or an org admin"
ok "the author may rename it"        "$(patch /tmp/bm-mem.jar $B/api/organisations/$OID/bookmarks/$BID '{"description":"Deploy runbook (2024)"}' | j "d['description']")" "Deploy runbook (2024)"
ok "another member may NOT (403)"    "$(ptcode /tmp/bm-mem2.jar $B/api/organisations/$OID/bookmarks/$BID '{"description":"Hijacked"}')" "403"
ok "…403 not 404: they can see it"   "$(curl -s -b /tmp/bm-mem2.jar $B/api/organisations/$OID/bookmarks | j "sum(1 for b in d if b['id']=='$BID')")" "1"
ok "…and can_edit says so upfront"   "$(curl -s -b /tmp/bm-mem2.jar $B/api/organisations/$OID/bookmarks | j "[b['can_edit'] for b in d if b['id']=='$BID'][0]")" "False"
ok "an admin may edit anybody's"     "$(patch /tmp/bm-admin.jar $B/api/organisations/$OID/bookmarks/$BID '{"url":"https://example.com/runbook-v2"}' | j "d['url']")" "https://example.com/runbook-v2"
ok "a member may NOT delete it"      "$(code -b /tmp/bm-mem2.jar -X DELETE $B/api/organisations/$OID/bookmarks/$BID)" "403"
ok "it survived that"                "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "sum(1 for b in d if b['id']=='$BID')")" "1"

echo "== pinning: the OWNER, and not even an admin"
ok "an admin cannot pin (403)"   "$(pcode /tmp/bm-admin.jar $B/api/organisations/$OID/bookmarks/$BID/pinned '{"pinned":true}')" "403"
ok "a member cannot pin (403)"   "$(pcode /tmp/bm-mem.jar   $B/api/organisations/$OID/bookmarks/$BID/pinned '{"pinned":true}')" "403"
ok "still unpinned after both"   "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "[b['pinned'] for b in d if b['id']=='$BID'][0]")" "False"
ok "the owner can pin"           "$(post /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks/$BID/pinned '{"pinned":true}' | j "d['pinned']")" "True"
ok "a pinned row sorts first"    "$(curl -s -b /tmp/bm-mem.jar $B/api/organisations/$OID/bookmarks | j "d[0]['id']")" "$BID"
ok "…for every member, not just the owner" "$(curl -s -b /tmp/bm-admin.jar $B/api/organisations/$OID/bookmarks | j "d[0]['pinned']")" "True"
ok "the owner can unpin"         "$(post /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks/$BID/pinned '{"pinned":false}' | j "d['pinned']")" "False"

echo "== ordering: any member may tidy the list"
# The client computes the midpoint of a row's new neighbours; nothing
# server-side ever renumbers, so this is one plain integer.
LAST=$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "d[-1]['id']")
FIRSTPOS=$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "d[0]['position']")
ok "a member may move somebody else's row" "$(pcode /tmp/bm-mem2.jar $B/api/organisations/$OID/bookmarks/$LAST/position "{\"position\":$((FIRSTPOS-1000))}")" "200"
ok "it is now first"  "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "d[0]['id']")" "$LAST"
ok "reordering does not pin it" "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "d[0]['pinned']")" "False"
# A pinned row outranks position, so a member cannot drag a link past one.
post /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks/$BID/pinned '{"pinned":true}' >/dev/null
post /tmp/bm-mem2.jar $B/api/organisations/$OID/bookmarks/$LAST/position "{\"position\":$((FIRSTPOS-99000))}" >/dev/null
ok "…and cannot outrank a pinned one by dragging" "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "d[0]['id']")" "$BID"

echo "== scoped to the organisation named in the URL"
ok "invisible through another org's URL" "$(code -b /tmp/bm-owner.jar -X DELETE $B/api/organisations/$OID2/bookmarks/$BID)" "404"
ok "…and cannot be pinned through it"    "$(pcode /tmp/bm-owner.jar $B/api/organisations/$OID2/bookmarks/$BID/pinned '{"pinned":true}')" "404"
ok "a stranger's organisation 404s"      "$(code -b /tmp/bm-mem.jar $B/api/organisations/$OID2/bookmarks)" "404"
ok "still on org1's shelf"               "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "sum(1 for b in d if b['id']=='$BID')")" "1"

echo "== a link outlives whoever added it"
# There is no reassignment step for bookmarks, unlike a task or a project
# (`organisations._reassign_everything_owned_by`), because a bookmark has no
# owner — only somebody who happened to type it in. So removing that person
# from the organisation has to succeed *and* leave the link on the shelf.
LEAVER=$(post /tmp/bm-mem2.jar $B/api/organisations/$OID/bookmarks '{"url":"https://example.com/leaver","description":"Added by the leaver"}' | j "d['id']")
MID=$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$MEM2'][0]")
ok "the member can be removed"   "$(code -b /tmp/bm-owner.jar -X DELETE $B/api/organisations/$OID/members/$MID)" "204"
ok "their link is still there"   "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "sum(1 for b in d if b['id']=='$LEAVER')")" "1"
ok "…and it still says who added it" "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "[b['added_by']['email'] for b in d if b['id']=='$LEAVER'][0]")" "$MEM2"
ok "an admin can still tidy it away" "$(code -b /tmp/bm-admin.jar -X DELETE $B/api/organisations/$OID/bookmarks/$LEAVER)" "204"

echo "== deleting"
ok "the author may delete their own" "$(code -b /tmp/bm-mem.jar -X DELETE $B/api/organisations/$OID/bookmarks/$BID)" "204"
ok "four remain"                     "$(curl -s -b /tmp/bm-owner.jar $B/api/organisations/$OID/bookmarks | j "len(d)")" "4"
ok "deleting it again 404s"          "$(code -b /tmp/bm-mem.jar -X DELETE $B/api/organisations/$OID/bookmarks/$BID)" "404"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
