#!/usr/bin/env bash
#
# Instance administration end-to-end: suspension actually stops somebody.
#
#   docker compose up -d && ./scripts/e2e-instance.sh
#
# The claim worth proving isn't that a column flipped — it's that a
# suspended person cannot sign in AND cannot keep using the session they
# already had, which are two different mechanisms (an emailpassword API
# override, and revoking sessions plus a re-check on every request). A test
# that only checked one of them would pass while the other silently let
# somebody carry on working.
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
signin_status(){ curl -s -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  -H 'st-auth-mode: cookie' -X POST $B/api/auth/signin \
  -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$1\"},{\"id\":\"password\",\"value\":\"Testpass123\"}]}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))"; }
code(){ curl -s -o /dev/null -w '%{http_code}' "$@"; }
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }

A=inst-a$S@example.com; BB=inst-b$S@example.com
signup /tmp/inst-a.jar $A; signup /tmp/inst-b.jar $BB
# A real session doing real work, so there's something to actually cut off.
OID=$(post /tmp/inst-a.jar $B/api/organisations "{\"name\":\"Inst $S\"}" | j "d['id']")

echo "before suspension"
ok "signed in and working"        "$(code -b /tmp/inst-a.jar $B/api/organisations/$OID)" "200"
ok "can sign in"                  "$(signin_status $A)"                                  "OK"

echo "suspend"
./scripts/instance.sh suspend "$A" --reason "e2e $S" >/tmp/inst-out 2>&1
ok "the command reports it"       "$(grep -c 'suspended' /tmp/inst-out)"                 "1"
# 401, not 403: the session was revoked, so SuperTokens turns the request
# away before it ever reaches a route. That's the stronger of the two
# mechanisms and the one that fires in practice. `deps.py`'s own 403 is
# defence in depth behind it — it only matters where an access token
# outlives its revocation (a deployment verifying tokens without a core
# round trip), which this stack doesn't do, so asserting 403 here would
# have been asserting the weaker path and calling the real one a failure.
ok "the open session is refused"  "$(code -b /tmp/inst-a.jar $B/api/organisations/$OID)" "401"
ok "…and so is /me"               "$(code -b /tmp/inst-a.jar $B/api/me)"                 "401"
# The front door: the emailpassword override, before any password check.
ok "signing in is refused"        "$(signin_status $A)"                    "SIGN_IN_NOT_ALLOWED"

echo "nobody else is affected"
ok "a bystander still signs in"   "$(signin_status $BB)"                                 "OK"
ok "…and their session works"     "$(code -b /tmp/inst-b.jar $B/api/me)"                 "200"

echo "restore"
./scripts/instance.sh restore "$A" >/dev/null 2>&1
ok "can sign in again"            "$(signin_status $A)"                                  "OK"
# Their organisation, and everything in it, survived untouched.
signup /tmp/inst-a2.jar $A >/dev/null 2>&1
curl -s -c /tmp/inst-a2.jar -o /dev/null -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  -H 'st-auth-mode: cookie' -X POST $B/api/auth/signin \
  -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$A\"},{\"id\":\"password\",\"value\":\"Testpass123\"}]}"
ok "their data is still there"    "$(code -b /tmp/inst-a2.jar $B/api/organisations/$OID)" "200"

echo "an account that signed up and never used the app"
# The local `users` row is created lazily, on the first authenticated
# request — so this account has no row at all. That's not an edge case for
# this tool, it's the target: a script that registers addresses and walks
# away produces exactly this. Suspending has to reach it anyway, by asking
# SuperTokens, which knew about them at signup.
G=inst-ghost$S@example.com
signup /tmp/inst-g.jar $G
ok "invisible until suspended"    "$(./scripts/instance.sh users --limit 200 | grep -c "$G")"  "0"
./scripts/instance.sh suspend "$G" --reason "never used it" >/tmp/inst-g-out 2>&1
ok "suspending still finds them"  "$(grep -c 'suspended' /tmp/inst-g-out)"                     "1"
ok "and they cannot sign in"      "$(signin_status $G)"                          "SIGN_IN_NOT_ALLOWED"
ok "the reason is on the listing" "$(./scripts/instance.sh users --limit 5 | grep -c 'never used it')" "1"

echo "  $pass passed, $fail failed"
[ $fail -eq 0 ]
