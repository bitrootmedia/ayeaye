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
# The panel half is here for the same reason. `/api/instance/*` is 404 for
# anybody without an `instance_admins` row, the row can only be granted from
# the shell, and an instance admin gets no extra access inside any
# organisation — three claims that are each one missing line away from being
# false, and none of which a unit test can see.
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

echo "the panel is 404 for everybody, until the shell says otherwise"
# 404 rather than 403, deliberately: a 403 confirms the route exists and that
# some session would reach it, which is a map of where to aim.
ok "a plain account gets 404"     "$(code -b /tmp/inst-b.jar $B/api/instance/overview)"      "404"
ok "…on the user list too"        "$(code -b /tmp/inst-b.jar $B/api/instance/users)"         "404"
ok "…and cannot suspend anybody"  "$(code -b /tmp/inst-b.jar -X POST -H 'Content-Type: application/json' -d '{"suspended":true}' $B/api/instance/users/$(curl -s -b /tmp/inst-b.jar $B/api/me | j "d['id']")/suspended)" "404"
ok "/me says they are not one"    "$(curl -s -b /tmp/inst-b.jar $B/api/me | j "d['is_instance_admin']")" "False"

./scripts/instance.sh grant-admin "$BB" --note "e2e $S" >/tmp/inst-grant 2>&1
ok "granting reports it"          "$(grep -c 'instance admin' /tmp/inst-grant)"               "1"
ok "…and the listing shows them"  "$(./scripts/instance.sh admins | grep -c "$BB")"           "1"
ok "/me now says they are one"    "$(curl -s -b /tmp/inst-b.jar $B/api/me | j "d['is_instance_admin']")" "True"
ok "the panel opens"              "$(code -b /tmp/inst-b.jar $B/api/instance/overview)"       "200"
ok "…with real totals"            "$(curl -s -b /tmp/inst-b.jar $B/api/instance/overview | j "d['users']>0")" "True"

echo "the panel lists what the CLI lists"
USERS=$(curl -s -b /tmp/inst-b.jar "$B/api/instance/users?limit=200")
ok "the account is in it"         "$(echo "$USERS" | j "sum(1 for u in d if u['email']=='$A')")" "1"
ok "it says who administers"      "$(echo "$USERS" | j "[u['is_instance_admin'] for u in d if u['email']=='$BB'][0]")" "True"
# Derived from what somebody actually did, never stamped — so an account that
# has only ever signed in still shows a time, and one that did nothing at all
# is a real null rather than an epoch date.
ok "last active is derived"       "$(echo "$USERS" | j "[u['last_active_at'] is not None for u in d if u['email']=='$A'][0]")" "True"
ok "search narrows it"            "$(curl -s -b /tmp/inst-b.jar "$B/api/instance/users?q=$A" | j "len(d)")" "1"
ok "X-Total-Count is the whole"   "$(curl -s -D - -o /dev/null -b /tmp/inst-b.jar "$B/api/instance/users?limit=1" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-total-count"{print ($2>1)}')" "1"
ORGS=$(curl -s -b /tmp/inst-b.jar "$B/api/instance/organisations?limit=200")
ok "the organisation is in it"    "$(echo "$ORGS" | j "sum(1 for o in d if o['id']=='$OID')")" "1"
ok "…with its owner"              "$(echo "$ORGS" | j "[o['owner_email'] for o in d if o['id']=='$OID'][0]")" "$A"

echo "an instance admin gets no extra access inside an organisation"
# The single most important claim on this surface, and the one a careless
# implementation breaks: the panel can COUNT an organisation's tasks and
# cannot OPEN it. services/access.py never learns instance_admins exists.
ok "still 404 on somebody's org"  "$(code -b /tmp/inst-b.jar $B/api/organisations/$OID)"        "404"
ok "…and on its task list"        "$(code -b /tmp/inst-b.jar $B/api/organisations/$OID/tasks)"  "404"

echo "suspending a whole organisation"
ok "its owner is working"         "$(code -b /tmp/inst-a2.jar $B/api/organisations/$OID)"       "200"
SUSPEND_ORG='{"suspended":true,"reason":"spam"}'
ok "the panel suspends it"        "$(code -b /tmp/inst-b.jar -X POST -H 'Content-Type: application/json' -d "$SUSPEND_ORG" $B/api/instance/organisations/$OID/suspended)" "204"
# 403 and not 404: they ARE a member, it IS there, and it is coming back.
# Telling them it vanished would send them to support believing they had
# been removed.
ok "its owner is locked out"      "$(code -b /tmp/inst-a2.jar $B/api/organisations/$OID)"       "403"
ok "…and told why"                "$(curl -s -b /tmp/inst-a2.jar $B/api/organisations/$OID | j "'spam' in d['detail']")" "True"
ok "…on every route under it"     "$(code -b /tmp/inst-a2.jar $B/api/organisations/$OID/tasks)" "403"
# Nothing was deleted and nobody was signed out of the product: the rest of
# their account still works, which is the difference between suspending an
# organisation and suspending a person.
ok "their account still works"    "$(code -b /tmp/inst-a2.jar $B/api/me)"                       "200"
ok "the panel marks it suspended" "$(curl -s -b /tmp/inst-b.jar "$B/api/instance/organisations?q=Inst+$S" | j "[o['suspended_at'] is not None for o in d if o['id']=='$OID'][0]")" "True"
RESTORE_ORG='{"suspended":false}'
ok "restoring lets them back"     "$(code -b /tmp/inst-b.jar -X POST -H 'Content-Type: application/json' -d "$RESTORE_ORG" $B/api/instance/organisations/$OID/suspended)" "204"
ok "…exactly where they were"     "$(code -b /tmp/inst-a2.jar $B/api/organisations/$OID)"       "200"
ok "the CLI can do it too"        "$(./scripts/instance.sh suspend-org "$(curl -s -b /tmp/inst-a2.jar $B/api/organisations/$OID | j "d['slug']")" --reason "cli" >/dev/null 2>&1; code -b /tmp/inst-a2.jar $B/api/organisations/$OID)" "403"
./scripts/instance.sh restore-org "$(curl -s -b /tmp/inst-b.jar "$B/api/instance/organisations?q=Inst+$S" | j "[o['slug'] for o in d if o['id']=='$OID'][0]")" >/dev/null 2>&1
ok "…and undo it"                 "$(code -b /tmp/inst-a2.jar $B/api/organisations/$OID)"       "200"

echo "the panel cannot appoint its own successors, or lock itself out"
# The whole reason a web panel is acceptable at all: one stolen session
# cannot become a permanent foothold, because there is no route that grants
# the row. Only the shell does.
ok "no grant route exists"        "$(curl -s $B/api/openapi.json | j "sum(1 for p in d['paths'] if 'instance' in p and 'admin' in p)")" "0"
SELF=$(curl -s -b /tmp/inst-b.jar $B/api/me | j "d['id']")
SUSPEND_SELF='{"suspended":true}'
ok "you can't suspend yourself"   "$(code -b /tmp/inst-b.jar -X POST -H 'Content-Type: application/json' -d "$SUSPEND_SELF" $B/api/instance/users/$SELF/suspended)" "400"
ok "…and are still an admin"      "$(code -b /tmp/inst-b.jar $B/api/instance/overview)"         "200"

echo "revoking takes the panel away on the next request"
./scripts/instance.sh revoke-admin "$BB" >/dev/null 2>&1
ok "the panel closes"             "$(code -b /tmp/inst-b.jar $B/api/instance/overview)"         "404"
ok "/me agrees, same session"     "$(curl -s -b /tmp/inst-b.jar $B/api/me | j "d['is_instance_admin']")" "False"

echo "  $pass passed, $fail failed"
[ $fail -eq 0 ]
