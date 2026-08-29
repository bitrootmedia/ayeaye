#!/usr/bin/env bash
#
# The notepad: free-form personal notes, scoped to an organisation.
#
#   docker compose up -d && ./scripts/e2e-notepad.sh
#
# One rule, and it's the whole feature: only the author, ever — no branch,
# not even for an organisation admin. This proves that against real SQL,
# the same way e2e-notes.sh proves it for a private task note.
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

OWNER=np-owner$S@example.com; ADMIN=np-admin$S@example.com
signup /tmp/np-owner.jar $OWNER; signup /tmp/np-admin.jar $ADMIN

OID=$(post /tmp/np-owner.jar $B/api/organisations "{\"name\":\"Notepad $S\"}" | j "d['id']")
T=$(post /tmp/np-owner.jar $B/api/organisations/$OID/invites "{\"email\":\"$ADMIN\",\"role\":\"admin\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/np-admin.jar -X POST $B/api/invites/$T/accept

# A second organisation, to prove the list doesn't leak across the boundary.
OID2=$(post /tmp/np-owner.jar $B/api/organisations "{\"name\":\"Notepad2 $S\"}" | j "d['id']")

echo "== creating a note"
N=$(post /tmp/np-owner.jar $B/api/organisations/$OID/notes "{\"title\":\"Shopping list\",\"body\":\"milk, eggs\"}")
NID=$(echo "$N" | j "d['id']")
ok "returns the title and body" "$(echo "$N" | j "d['title']+'|'+d['body']")" "Shopping list|milk, eggs"
ok "has created and updated stamps" "$(echo "$N" | j "bool(d['created_at']) and bool(d['updated_at'])")" "True"
ok "empty title -> 422" "$(code -b /tmp/np-owner.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/notes -d '{"title":""}')" "422"
ok "body defaults to empty" "$(post /tmp/np-owner.jar $B/api/organisations/$OID/notes '{"title":"Bare"}' | j "d['body']")" ""

echo "== listing, most recently updated first"
N2=$(post /tmp/np-owner.jar $B/api/organisations/$OID/notes "{\"title\":\"Ideas\"}" | j "d['id']")
ok "newest first" "$(curl -s -b /tmp/np-owner.jar $B/api/organisations/$OID/notes | j "d[0]['title']")" "Ideas"
patch /tmp/np-owner.jar $B/api/organisations/$OID/notes/$NID '{"body":"milk, eggs, bread"}' >/dev/null
ok "editing bumps it back to the top" "$(curl -s -b /tmp/np-owner.jar $B/api/organisations/$OID/notes | j "d[0]['id']")" "$NID"

echo "== only the author, ever — not even an org admin"
ok "admin's own list is empty"   "$(curl -s -b /tmp/np-admin.jar $B/api/organisations/$OID/notes | j "len(d)")" "0"
ok "admin cannot fetch it by id (404, not 403)" "$(code -b /tmp/np-admin.jar -X DELETE $B/api/organisations/$OID/notes/$NID)" "404"
ok "…nor edit it" "$(code -b /tmp/np-admin.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/notes/$NID -d '{"title":"Hijacked"}')" "404"
ok "owner's note is untouched" "$(curl -s -b /tmp/np-owner.jar $B/api/organisations/$OID/notes | j "[n['title'] for n in d if n['id']=='$NID'][0]")" "Shopping list"

echo "== scoped to the organisation named in the URL"
ok "invisible through a different org's URL" "$(code -b /tmp/np-owner.jar -X DELETE $B/api/organisations/$OID2/notes/$NID)" "404"
ok "still there afterwards" "$(curl -s -b /tmp/np-owner.jar $B/api/organisations/$OID/notes | j "sum(1 for n in d if n['id']=='$NID')")" "1"
ok "org2's own list starts empty" "$(curl -s -b /tmp/np-owner.jar $B/api/organisations/$OID2/notes | j "len(d)")" "0"

echo "== deleting"
ok "delete one"  "$(code -b /tmp/np-owner.jar -X DELETE $B/api/organisations/$OID/notes/$N2)" "204"
ok "two remain"  "$(curl -s -b /tmp/np-owner.jar $B/api/organisations/$OID/notes | j "len(d)")" "2"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
