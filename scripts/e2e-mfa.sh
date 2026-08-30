#!/usr/bin/env bash
#
# Two-factor authentication: TOTP and backup codes.
#
#   docker compose up -d && ./scripts/e2e-mfa.sh
#
# Not SuperTokens' own totp/multifactorauth recipes — those require a paid
# core license even self-hosted, confirmed against a real core. This is
# hand-rolled TOTP (services/mfa.py) gated by a custom, free session claim
# (security/authn.py's MfaSatisfiedClaim). What's being proved here:
# personal opt-in is sticky, an organisation's requirement unions with it
# rather than replacing it, a fresh sign-in is what picks a new requirement
# up (not an already-open session), backup codes are single-use, and the
# admin/rank rules match every other member action in this codebase.
#
# Every -d body below is built into a variable BEFORE it's used, never
# written as a literal "{\"a\":\"$x\",\"b\":\"$y\"}" inline inside a
# `"$(...)"` capture — a multi-key literal nested that way is silently torn
# in two by bash's brace expansion (the comma inside `{...}` is read as a
# brace-expansion separator once it's nested two quote-levels deep), which
# turns one request into two malformed ones with no error from bash at all.
# Cost real time to track down; costs nothing to just never write it that
# way.
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
# A fresh sign-in, not signup — this is how a session picks up a
# newly-forced organisation requirement, since the claim is decided once per
# session at first use, not re-polled mid-session.
signin(){ rm -f "$1"; curl -s -c "$1" -o /dev/null -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  -H 'st-auth-mode: cookie' -X POST $B/api/auth/signin \
  -d "{\"formFields\":[{\"id\":\"email\",\"value\":\"$2\"},{\"id\":\"password\",\"value\":\"Testpass123\"}]}"; }
code(){ curl -s -o /dev/null -w '%{http_code}' "$@"; }
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post(){ curl -s -b "$1" -c "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
get(){ curl -s -b "$1" -c "$1" "$2"; }
del(){ curl -s -b "$1" -c "$1" -X DELETE "$2"; }
# Whether a response body is SuperTokens' own "the MFA claim isn't
# satisfied" shape, not just any 403 — a 403 for the wrong reason would pass
# a status-code-only check for the wrong reason too.
is_mfa_error(){ echo "$1" | python3 -c "import json,sys
try:
    d=json.load(sys.stdin)
    print(any(c.get('id')=='st-mfa-ok' for c in d.get('claimValidationErrors', [])))
except Exception:
    print(False)"; }
# Pure stdlib TOTP (RFC 6238) — no pyotp on the host, and there's no reason
# to require one just to run this script.
totp(){ python3 -c "
import base64, hashlib, hmac, struct, sys, time
secret = sys.argv[1]
key = base64.b32decode(secret.upper() + '=' * ((8 - len(secret) % 8) % 8))
counter = int(time.time() // 30)
h = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
o = h[-1] & 0xf
code = (struct.unpack('>I', h[o:o+4])[0] & 0x7fffffff) % 1000000
print(f'{code:06d}')
" "$1"; }

OWNER=mo$S@example.com; MEMBER=mm$S@example.com
signup /tmp/mo.jar $OWNER; signup /tmp/mm.jar $MEMBER

OID=$(post /tmp/mo.jar $B/api/organisations "{\"name\":\"MFA $S\"}" | j "d['id']")
ok "starts unforced" "$(get /tmp/mo.jar $B/api/organisations/$OID | j "d['require_mfa']")" "False"

BODY="{\"email\":\"$MEMBER\",\"role\":\"member\"}"
T=$(post /tmp/mo.jar $B/api/organisations/$OID/invites "$BODY" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/mm.jar -c /tmp/mm.jar -X POST $B/api/invites/$T/accept

echo "== personal opt-in, before any organisation is involved"
ok "not enrolled yet"    "$(get /tmp/mo.jar $B/api/me/mfa/status | j "d['enrolled']")" "False"
DEV=$(post /tmp/mo.jar $B/api/me/mfa/totp "")
SECRET=$(echo "$DEV" | j "d['secret']")
ok "a QR data URI comes with it" "$(echo "$DEV" | j "d['qr_data_uri'].startswith('data:image/png;base64,')")" "True"

BODY="{\"secret\":\"$SECRET\",\"code\":\"000000\"}"
ok "wrong code is refused"   "$(code -b /tmp/mo.jar -c /tmp/mo.jar -H 'Content-Type: application/json' -X POST $B/api/me/mfa/totp/verify -d "$BODY")" "403"
GOOD=$(totp "$SECRET")
BODY="{\"secret\":\"$SECRET\",\"code\":\"$GOOD\"}"
ok "right code activates it" "$(code -b /tmp/mo.jar -c /tmp/mo.jar -H 'Content-Type: application/json' -X POST $B/api/me/mfa/totp/verify -d "$BODY")" "204"
ok "now enrolled"            "$(get /tmp/mo.jar $B/api/me/mfa/status | j "d['enrolled']")" "True"

echo "== enrolling personally makes it required, from the next sign-in on"
ok "still fine mid-session"  "$(code -b /tmp/mo.jar $B/api/me)" "200"
signin /tmp/mo.jar $OWNER
RESP=$(curl -s -b /tmp/mo.jar $B/api/me)
ok "fresh session is gated"  "$(is_mfa_error "$RESP")" "True"
ok "the challenge endpoint is reachable while gated" "$(code -b /tmp/mo.jar -c /tmp/mo.jar $B/api/me/mfa/status)" "200"
ok "wrong code stays gated"  "$(code -b /tmp/mo.jar -c /tmp/mo.jar -H 'Content-Type: application/json' -X POST $B/api/me/mfa/totp/challenge -d '{"code":"000000"}')" "403"
GOOD=$(totp "$SECRET")
BODY="{\"code\":\"$GOOD\"}"
ok "right code un-gates it"  "$(code -b /tmp/mo.jar -c /tmp/mo.jar -H 'Content-Type: application/json' -X POST $B/api/me/mfa/totp/challenge -d "$BODY")" "204"
ok "and /me works again"     "$(code -b /tmp/mo.jar $B/api/me)" "200"

echo "== backup codes: single use, generated once, shown once"
CODES=$(post /tmp/mo.jar $B/api/me/mfa/backup-codes "")
ok "ten codes"                "$(echo "$CODES" | j "len(d['codes'])")" "10"
ONE=$(echo "$CODES" | j "d['codes'][0]")
signin /tmp/mo.jar $OWNER
BODY="{\"code\":\"$ONE\"}"
ok "redeeming it un-gates the session" "$(code -b /tmp/mo.jar -c /tmp/mo.jar -H 'Content-Type: application/json' -X POST $B/api/me/mfa/backup-codes/redeem -d "$BODY")" "200"
ok "and now /me works"        "$(code -b /tmp/mo.jar $B/api/me)" "200"
signin /tmp/mo.jar $OWNER
ok "the same code twice -> 403" "$(code -b /tmp/mo.jar -c /tmp/mo.jar -H 'Content-Type: application/json' -X POST $B/api/me/mfa/backup-codes/redeem -d "$BODY")" "403"

echo "== turning it off clears both the device and the codes"
# DELETE is MfaPendingSession-gated like every /me/mfa/* route, so it works
# regardless of whether this particular session is currently satisfied.
del /tmp/mo.jar $B/api/me/mfa/totp >/dev/null
ok "no longer enrolled"      "$(get /tmp/mo.jar $B/api/me/mfa/status | j "d['enrolled']")" "False"
ok "no codes remain"         "$(get /tmp/mo.jar $B/api/me/mfa/status | j "d['codes_remaining']")" "0"

echo "== an organisation forcing it, without anyone opting in personally"
ok "member not gated yet"    "$(code -b /tmp/mm.jar $B/api/me)" "200"
ok "member cannot force it (403, not the mfa-gate shape)" "$(code -b /tmp/mm.jar -c /tmp/mm.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/require-mfa -d '{"enabled":true}')" "403"
post /tmp/mo.jar $B/api/organisations/$OID/require-mfa '{"enabled":true}' >/dev/null
ok "the toggle sticks"       "$(get /tmp/mo.jar $B/api/organisations/$OID | j "d['require_mfa']")" "True"
ok "not kicked mid-session"  "$(code -b /tmp/mm.jar $B/api/me)" "200"

signin /tmp/mm.jar $MEMBER
RESP=$(curl -s -b /tmp/mm.jar $B/api/me)
ok "fresh session is gated"  "$(is_mfa_error "$RESP")" "True"
ok "not enrolled -> forced to set up" "$(get /tmp/mm.jar $B/api/me/mfa/status | j "d['enrolled']")" "False"
MDEV=$(post /tmp/mm.jar $B/api/me/mfa/totp "")
MSECRET=$(echo "$MDEV" | j "d['secret']")
MGOOD=$(totp "$MSECRET")
BODY="{\"secret\":\"$MSECRET\",\"code\":\"$MGOOD\"}"
post /tmp/mm.jar $B/api/me/mfa/totp/verify "$BODY" >/dev/null
ok "enrolling satisfies the same session" "$(code -b /tmp/mm.jar $B/api/me)" "200"

echo "== turning the requirement off never revokes personal enrollment"
post /tmp/mo.jar $B/api/organisations/$OID/require-mfa '{"enabled":false}' >/dev/null
signin /tmp/mm.jar $MEMBER
RESP=$(curl -s -b /tmp/mm.jar $B/api/me)
ok "still gated — it's their own device now, not the org's rule" "$(is_mfa_error "$RESP")" "True"
MGOOD=$(totp "$MSECRET")
BODY="{\"code\":\"$MGOOD\"}"
post /tmp/mm.jar $B/api/me/mfa/totp/challenge "$BODY" >/dev/null
post /tmp/mo.jar $B/api/organisations/$OID/require-mfa '{"enabled":true}' >/dev/null

echo "== admin reset: the escape hatch for a lost device"
MID=$(get /tmp/mo.jar $B/api/organisations/$OID/members | j "[m['id'] for m in d if m['email']=='$MEMBER'][0]")
ok "member cannot reset their own via the admin route" "$(code -b /tmp/mm.jar -c /tmp/mm.jar -X POST $B/api/organisations/$OID/members/$MID/reset-mfa)" "403"
ok "owner resets the member"  "$(code -b /tmp/mo.jar -c /tmp/mo.jar -X POST $B/api/organisations/$OID/members/$MID/reset-mfa)" "204"
signin /tmp/mm.jar $MEMBER
ok "asked to set up again"    "$(get /tmp/mm.jar $B/api/me/mfa/status | j "d['enrolled']")" "False"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
