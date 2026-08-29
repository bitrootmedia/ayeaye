#!/usr/bin/env bash
#
# Phase 1 end-to-end: organisations, roles and invitations, driven over HTTP
# against a running stack.
#
#   docker compose up -d && ./scripts/e2e-organisations.sh
#
# This exists because the unit suite is deliberately infra-free: it covers the
# rule *functions* exhaustively and cannot cover the SQL those rules sit on —
# the partial unique indexes, the pending-invite bind, the 404-not-403
# convention. Those only fail against a real Postgres.
#
# It creates real accounts (alice/bob/carol/dave + a timestamp) and leaves them
# behind. Point it at a dev stack, never at anything real.
set -u
B=http://localhost
S=$(date +%s)
pass=0; fail=0
ok(){ if [ "$2" = "$3" ]; then echo "  ok   $1"; pass=$((pass+1)); else echo "  FAIL $1: expected [$3] got [$2]"; fail=$((fail+1)); fi; }

signup(){ # $1=jar $2=email
  curl -s -c "$1" -o /dev/null -H 'Content-Type: application/json' -H 'rid: emailpassword' \
    -H 'st-auth-mode: cookie' -X POST $B/api/auth/signup \
    -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$2\"},{\"id\":\"password\",\"value\":\"Testpass123\"}]}"
}
code(){ curl -s -o /dev/null -w '%{http_code}' "$@"; }
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

ALICE=alice$S@example.com; BOB=bob$S@example.com; CAROL=carol$S@example.com; DAVE=dave$S@example.com
signup /tmp/alice.jar $ALICE; signup /tmp/bob.jar $BOB; signup /tmp/carol.jar $CAROL

echo "== create + own"
# Unique per run: slugs are global, so a fixed name would collide with the
# leftovers of the previous run and shift every expected suffix.
NAME="Acme $S & Co."
ORG=$(curl -s -b /tmp/alice.jar -H 'Content-Type: application/json' -X POST $B/api/organisations -d "{\"name\":\"$NAME\"}")
OID=$(echo "$ORG" | j "d['id']")
ok "creator becomes owner"      "$(echo "$ORG" | j "d['role']")" "owner"
ok "slug is derived"            "$(echo "$ORG" | j "d['slug']")" "acme-$S-co"
ok "slug collides -> suffix"    "$(curl -s -b /tmp/bob.jar -H 'Content-Type: application/json' -X POST $B/api/organisations -d "{\"name\":\"$NAME\"}" | j "d['slug']")" "acme-$S-co-2"

echo "== isolation"
ok "non-member gets 404"        "$(code -b /tmp/carol.jar $B/api/organisations/$OID)" "404"
ok "member list excludes it"    "$(curl -s -b /tmp/carol.jar $B/api/organisations | j "sum(1 for o in d if o['id']=='$OID')")" "0"

echo "== invite an existing account"
INV=$(curl -s -b /tmp/alice.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/invites -d "{\"email\":\"$CAROL\",\"role\":\"member\"}")
ok "invite returns a link"      "$(echo "$INV" | j "d['invite_url'].startswith('$B/invites/')")" "True"
ok "and says it emailed"        "$(echo "$INV" | j "str(d['emailed'])")" "True"
ok "duplicate invite -> 409"    "$(code -b /tmp/alice.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/invites -d "{\"email\":\"$CAROL\",\"role\":\"member\"}")" "409"
ok "invited is NOT yet a member" "$(code -b /tmp/carol.jar $B/api/organisations/$OID)" "404"
ok "it shows in her pending"    "$(curl -s -b /tmp/carol.jar $B/api/me/invites | j "sum(1 for i in d if i['organisation_id']=='$OID')")" "1"

MID=$(curl -s -b /tmp/carol.jar $B/api/me/invites | j "[i['id'] for i in d if i['organisation_id']=='$OID'][0]")
ok "accepting from the list"    "$(curl -s -b /tmp/carol.jar -X POST $B/api/me/invites/$MID/accept | j "d['role']")" "member"
ok "now she is in"              "$(code -b /tmp/carol.jar $B/api/organisations/$OID)" "200"

echo "== what a member may not do"
ok "member cannot invite"       "$(code -b /tmp/carol.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/invites -d '{"email":"x@example.com"}')" "403"
ok "member cannot rename"       "$(code -b /tmp/carol.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID -d '{"name":"Mine"}')" "403"
ok "member cannot delete"       "$(code -b /tmp/carol.jar -X DELETE $B/api/organisations/$OID)" "403"
ok "but CAN see the roster"     "$(code -b /tmp/carol.jar $B/api/organisations/$OID/members)" "200"

echo "== the copyable link, for an address with no account"
INV2=$(curl -s -b /tmp/alice.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/invites -d "{\"email\":\"$DAVE\",\"role\":\"admin\"}")
TOKEN=$(echo "$INV2" | j "d['invite_url'].rsplit('/',1)[1]")
ok "preview needs no session"   "$(curl -s $B/api/invites/$TOKEN | j "d['organisation_name']")" "$NAME"
ok "preview shows the role"     "$(curl -s $B/api/invites/$TOKEN | j "d['role']")" "admin"
signup /tmp/dave.jar $DAVE
ok "bound on signup, pending"   "$(curl -s -b /tmp/dave.jar $B/api/me/invites | j "sum(1 for i in d if i['organisation_id']=='$OID')")" "1"
ok "still not a member"         "$(code -b /tmp/dave.jar $B/api/organisations/$OID)" "404"
ok "link accepts him"           "$(curl -s -b /tmp/dave.jar -X POST $B/api/invites/$TOKEN/accept | j "d['role']")" "admin"
ok "token is single-use"        "$(code -b /tmp/dave.jar -X POST $B/api/invites/$TOKEN/accept)" "404"

echo "== role rules"
ADMINMID=$(curl -s -b /tmp/dave.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$ALICE'][0]")
ok "admin cannot demote owner"  "$(code -b /tmp/dave.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/members/$ADMINMID -d '{"role":"member"}')" "403"
ok "admin cannot appoint owner" "$(code -b /tmp/dave.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/invites -d '{"email":"nope@example.com","role":"owner"}')" "403"
CMID=$(curl -s -b /tmp/alice.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$CAROL'][0]")
ok "owner promotes to admin"    "$(curl -s -b /tmp/alice.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/members/$CMID -d '{"role":"admin"}' | j "d['role']")" "admin"

echo "== last owner"
AMID=$(curl -s -b /tmp/alice.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$ALICE'][0]")
ok "last owner can't demote"    "$(code -b /tmp/alice.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/members/$AMID -d '{"role":"admin"}')" "409"
ok "last owner can't leave"     "$(code -b /tmp/alice.jar -X DELETE $B/api/organisations/$OID/members/$AMID)" "409"
ok "promote carol to owner"     "$(curl -s -b /tmp/alice.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/members/$CMID -d '{"role":"owner"}' | j "d['role']")" "owner"
ok "now alice may leave"        "$(code -b /tmp/alice.jar -X DELETE $B/api/organisations/$OID/members/$AMID)" "204"
ok "and loses access"           "$(code -b /tmp/alice.jar $B/api/organisations/$OID)" "404"

echo "== invite link secrecy"
INV3=$(curl -s -b /tmp/carol.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/invites -d '{"email":"erin'$S'@example.com"}')
EMID=$(echo "$INV3" | j "d['member']['id']")
ok "admin sees links on roster" "$(curl -s -b /tmp/dave.jar $B/api/organisations/$OID/members | j "sum(1 for m in d if m.get('invite_url'))")" "1"
# demote dave to member, then he must not see the link
DMID=$(curl -s -b /tmp/carol.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$DAVE'][0]")
curl -s -o /dev/null -b /tmp/carol.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/members/$DMID -d '{"role":"member"}'
ok "plain member sees none"     "$(curl -s -b /tmp/dave.jar $B/api/organisations/$OID/members | j "sum(1 for m in d if m.get('invite_url'))")" "0"
ok "reissue invalidates old"    "$(curl -s -b /tmp/carol.jar -X POST $B/api/organisations/$OID/members/$EMID/invite-link | j "d['invite_url'] != '$(echo "$INV3" | j "d['invite_url']")'")" "True"
ok "revoking kills the token"   "$(code -b /tmp/carol.jar -X DELETE $B/api/organisations/$OID/members/$EMID)" "204"

echo "== disable / enable"
DMID2=$(curl -s -b /tmp/carol.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$DAVE'][0]")
DUID=$(curl -s -b /tmp/carol.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$DAVE'][0]")
DTID=$(curl -s -b /tmp/dave.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/tasks -d '{"title":"Daves task"}' | j "d['id']")
ok "member cannot disable"      "$(code -b /tmp/dave.jar -X POST $B/api/organisations/$OID/members/$DMID2/disable)" "403"
ok "owner disables dave"        "$(curl -s -b /tmp/carol.jar -X POST $B/api/organisations/$OID/members/$DMID2/disable | j "d['status']")" "disabled"
ok "dave loses access"          "$(code -b /tmp/dave.jar $B/api/organisations/$OID)" "404"
ok "disabling again -> 409"     "$(code -b /tmp/carol.jar -X POST $B/api/organisations/$OID/members/$DMID2/disable)" "409"
ok "roster still shows dave"    "$(curl -s -b /tmp/carol.jar $B/api/organisations/$OID/members | j "sum(1 for m in d if m['id']=='$DMID2')")" "1"
ok "his task is still his — no reassignment, unlike remove" "$(curl -s -b /tmp/carol.jar $B/api/organisations/$OID/tasks/$DTID | j "d['owner']['id']")" "$DUID"
ok "owner re-enables dave"      "$(curl -s -b /tmp/carol.jar -X POST $B/api/organisations/$OID/members/$DMID2/enable | j "d['status']")" "active"
ok "dave regains access"        "$(code -b /tmp/dave.jar $B/api/organisations/$OID)" "200"
ok "enabling an active one -> 409" "$(code -b /tmp/carol.jar -X POST $B/api/organisations/$OID/members/$DMID2/enable)" "409"
# rule 4, same as remove_member: a sole owner can act on themselves (that's
# how leaving works) but the last-owner check still catches it.
ok "sole owner disabling self -> 409" "$(code -b /tmp/carol.jar -X POST $B/api/organisations/$OID/members/$CMID/disable)" "409"
ok "promote dave to owner"      "$(curl -s -b /tmp/carol.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/members/$DMID2 -d '{"role":"owner"}' | j "d['role']")" "owner"
ok "two owners: carol disables dave" "$(curl -s -b /tmp/carol.jar -X POST $B/api/organisations/$OID/members/$DMID2/disable | j "d['status']")" "disabled"
ok "now carol is the last owner again" "$(code -b /tmp/carol.jar -X POST $B/api/organisations/$OID/members/$CMID/disable)" "409"
ok "re-enable dave, demote back" "$(curl -s -b /tmp/carol.jar -X POST $B/api/organisations/$OID/members/$DMID2/enable | j "d['status']")" "active"
curl -s -o /dev/null -b /tmp/carol.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/members/$DMID2 -d '{"role":"member"}'

echo "== delete"
ok "owner deletes"              "$(code -b /tmp/carol.jar -X DELETE $B/api/organisations/$OID)" "204"
ok "and it is gone"             "$(code -b /tmp/carol.jar $B/api/organisations/$OID)" "404"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
