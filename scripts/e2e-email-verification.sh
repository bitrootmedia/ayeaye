#!/usr/bin/env bash
#
# Email verification: the enforced path, end to end.
#
#   docker compose up -d && ./scripts/e2e-email-verification.sh
#
# **This restarts the API twice**, which no other suite does. Verification is
# a process-wide setting — SuperTokens' recipe is configured at init, not per
# request — so the only way to exercise the enforced path is to turn it on,
# test, and put it back. A checkout runs with it off so that every other
# suite can sign up accounts without fishing links out of Mailpit first (see
# compose.override.yml), and this is the price of that trade.
#
# Restoring is in a trap, so an interrupted run doesn't leave a dev stack
# refusing to let anyone in.
#
# Dev stacks only: needs Mailpit on :8025.
set -u
B=http://localhost
M=http://localhost:8025
S=$(date +%s)
pass=0; fail=0
ok(){ if [ "$2" = "$3" ]; then echo "  ok   $1"; pass=$((pass+1)); else echo "  FAIL $1: expected [$3] got [$2]"; fail=$((fail+1)); fi; }

j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
code(){ curl -s -o /dev/null -w '%{http_code}' "$@"; }
signup(){ curl -s -c "$1" -o /dev/null -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  -H 'st-auth-mode: cookie' -X POST $B/api/auth/signup \
  -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$2\"},{\"id\":\"password\",\"value\":\"Testpass123\"}]}"; }

restore(){
  echo "== putting the API back the way it was"
  ( cd "$(dirname "$0")/.." && docker compose up -d api >/dev/null 2>&1 )
  sleep 6
}
trap restore EXIT

echo "== turning verification on"
( cd "$(dirname "$0")/.." && EMAIL_VERIFICATION=required docker compose up -d api >/dev/null 2>&1 )
# Wait for it to answer rather than sleeping a guessed amount.
for _ in $(seq 1 40); do
  [ "$(code $B/health)" = "200" ] && break
  sleep 1
done

E=ev$S@example.com
signup /tmp/ev.jar "$E"

echo "== an unverified account is refused, and told why"
BODY=$(curl -s -b /tmp/ev.jar $B/api/me)
ok "GET /me is 403"                "$(code -b /tmp/ev.jar $B/api/me)" "403"
# The claim id is what the frontend matches on to show the right screen — a
# bare 403 would send it to the generic error page instead.
ok "…naming the email claim"       "$(echo "$BODY" | j "[c['id'] for c in d.get('claimValidationErrors',[])]")" "['st-ev']"
ok "a blocked session can still learn its own address" \
   "$(curl -s -b /tmp/ev.jar $B/api/me/pending-identity | j "d['email']")" "$E"

echo "== the email goes out on sign-up, without anyone asking for it"
# SuperTokens sends when a *client* asks it to, which an API sign-up never
# does — so the server sends it (see `_override_emailpassword_apis`).
LINK=""
for _ in $(seq 1 25); do
  LINK=$(curl -s "$M/api/v1/messages?limit=30" | TO="$E" python3 -c "
import json, os, sys, urllib.request
want = os.environ['TO']
for m in json.load(sys.stdin).get('messages', []):
    if m['To'][0]['Address'] != want or 'Confirm your email' not in m['Subject']:
        continue
    raw = json.loads(urllib.request.urlopen('http://localhost:8025/api/v1/message/' + m['ID']).read())
    for word in raw.get('Text', '').split():
        if 'verify-email' in word:
            print(word)
            break
    break
" 2>/dev/null)
  [ -n "$LINK" ] && break
  sleep 1
done
ok "a confirmation email arrived" "$([ -n "$LINK" ] && echo yes || echo no)" "yes"

echo "== the link lets them in"
TOKEN=$(python3 -c "import sys,urllib.parse as u; print(u.parse_qs(u.urlparse(sys.argv[1]).query).get('token',[''])[0])" "$LINK")
VERIFIED=$(curl -s -b /tmp/ev.jar -c /tmp/ev.jar -H 'Content-Type: application/json' -H 'rid: emailverification' \
  -X POST $B/api/auth/user/email/verify -d "{\"method\":\"token\",\"token\":\"$TOKEN\"}" | j "d['status']")
ok "the token verifies"          "$VERIFIED" "OK"
# The session's own copy of the claim is still stale until it refreshes —
# which is why the gate in the browser refreshes before re-checking, and why
# a test that skipped this would report a working feature as broken.
curl -s -o /dev/null -b /tmp/ev.jar -c /tmp/ev.jar -X POST $B/api/auth/session/refresh
ok "and then /me works"          "$(code -b /tmp/ev.jar $B/api/me)" "200"

echo "== a bad token changes nothing"
BAD=ev-bad$S@example.com
signup /tmp/evb.jar "$BAD"
STATUS=$(curl -s -b /tmp/evb.jar -H 'Content-Type: application/json' -H 'rid: emailverification' \
  -X POST $B/api/auth/user/email/verify -d '{"method":"token","token":"not-a-real-token"}' | j "d['status']")
ok "refused"                     "$STATUS" "EMAIL_VERIFICATION_INVALID_TOKEN_ERROR"
curl -s -o /dev/null -b /tmp/evb.jar -c /tmp/evb.jar -X POST $B/api/auth/session/refresh
ok "still locked out"            "$(code -b /tmp/evb.jar $B/api/me)" "403"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
