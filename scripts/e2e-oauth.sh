#!/usr/bin/env bash
#
# OAuth 2.1 for MCP connectors: Dynamic Client Registration, PKCE, and
# rotating refresh tokens — the flow that lets Claude.ai and ChatGPT add
# this server as a custom connector with nobody pasting a personal access
# token. See services/oauth.py and CLAUDE.md's OAuth section.
#
#   docker compose up -d && ./scripts/e2e-oauth.sh
#
# The properties worth proving: a bad/missing token gets a real 401 (not a
# 200 with an error buried in a JSON-RPC result — the actual bug that made
# claude.ai's connector unusable), a code or refresh token can never be
# replayed, a client never receives more scope than it registered for, and
# revoking a grant breaks the very next MCP call.
#
# Creates real accounts and OAuth clients and leaves them behind. Dev stacks
# only.
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

pkce(){ python3 -c "
import base64, hashlib, secrets
v = secrets.token_urlsafe(32)
c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b'=').decode()
print(v); print(c)
"; }

mcp_status(){ # extra curl args, e.g. -H 'Authorization: Bearer X'
  curl -s -o /dev/null -w '%{http_code}' -X POST $B/mcp \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -H 'MCP-Protocol-Version: 2025-06-18' "$@" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
}
mcp_call(){ # $1 token  $2 tool  $3 arguments-json
  python3 -c "import json,sys; print(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':sys.argv[1],'arguments':json.loads(sys.argv[2])}}))" "$2" "$3" > /tmp/oa-mcp.json
  curl -s -X POST $B/mcp -H "Authorization: Bearer $1" -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2025-06-18' \
    --data-binary @/tmp/oa-mcp.json
}

ALICE=oaa$S@example.com
signup /tmp/oaa.jar $ALICE
OID=$(post /tmp/oaa.jar $B/api/organisations "{\"name\":\"OAuth $S\"}" | j "d['id']")
REDIRECT="https://example.com/callback"

echo "== the discovery documents are real JSON, not the SPA's HTML"
ok "authorization-server metadata" \
  "$(curl -s $B/.well-known/oauth-authorization-server | j "d['issuer']")" "$B"
ok "protected-resource metadata (bare)" \
  "$(curl -s $B/.well-known/oauth-protected-resource | j "d['resource']")" "$B/mcp"
ok "protected-resource metadata (RFC 9728 path-inserted form)" \
  "$(curl -s $B/.well-known/oauth-protected-resource/mcp | j "d['resource']")" "$B/mcp"
ok "openid-configuration stays 404 — not an OIDC provider" \
  "$(code $B/.well-known/openid-configuration)" "404"

echo "== a missing or bad token gets a real 401, not a 200 with the error buried in JSON-RPC"
ok "no token at all"                    "$(mcp_status)" "401"
ok "...with WWW-Authenticate naming the resource" \
  "$(curl -sD - -o /dev/null -X POST $B/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{}' | grep -ci resource_metadata)" "1"
ok "a made-up token" "$(mcp_status -H 'Authorization: Bearer ayo_nonsense')" "401"

echo "== dynamic client registration"
REG=$(curl -s -X POST $B/api/oauth/register -H 'Content-Type: application/json' \
  -d "{\"redirect_uris\":[\"$REDIRECT\"],\"client_name\":\"E2E Connector\"}")
CLIENT_ID=$(echo "$REG" | j "d['client_id']")
ok "registration returns a client_id"   "$(echo "$REG" | j "bool(d['client_id'])")" "True"
ok "public by default, no secret"       "$(echo "$REG" | j "d.get('client_secret')")" "None"
# 422, not 400: this is the SDK's own OAuthClientMetadata rejecting an
# empty list before our own register_client ever runs, not our
# RegistrationError path — still refused, just refused one layer earlier.
ok "no redirect_uris is refused"        "$(code -X POST $B/api/oauth/register -H 'Content-Type: application/json' -d '{"redirect_uris":[]}')" "422"

echo "== authorize: preview then decision"
pkce > /tmp/oa-pkce.txt
VERIFIER=$(sed -n '1p' /tmp/oa-pkce.txt); CHALLENGE=$(sed -n '2p' /tmp/oa-pkce.txt)
PREVIEW=$(curl -s "$B/api/oauth/authorize/preview?client_id=$CLIENT_ID&redirect_uri=$REDIRECT&code_challenge=$CHALLENGE&code_challenge_method=S256")
ok "preview works unauthenticated"      "$(echo "$PREVIEW" | j "d['client_name']")" "E2E Connector"
ok "an unregistered redirect_uri is refused" \
  "$(code "$B/api/oauth/authorize/preview?client_id=$CLIENT_ID&redirect_uri=https://evil.example/&code_challenge=$CHALLENGE&code_challenge_method=S256")" "400"

DECISION=$(post /tmp/oaa.jar $B/api/oauth/authorize/decision \
  "{\"client_id\":\"$CLIENT_ID\",\"redirect_uri\":\"$REDIRECT\",\"code_challenge\":\"$CHALLENGE\",\"state\":\"s1\",\"allow\":true,\"scope\":\"write\"}")
REDIRECT_TO=$(echo "$DECISION" | j "d['redirect_to']")
CODE1=$(python3 -c "from urllib.parse import urlparse, parse_qs; print(parse_qs(urlparse('$REDIRECT_TO').query)['code'][0])")
ok "the redirect carries the original state" \
  "$(python3 -c "from urllib.parse import urlparse, parse_qs; print(parse_qs(urlparse('$REDIRECT_TO').query)['state'][0])")" "s1"
CLAMP_BODY="{\"client_id\":\"$CLIENT_ID\",\"redirect_uri\":\"$REDIRECT\",\"code_challenge\":\"$CHALLENGE\",\"allow\":true,\"scope\":\"write\"}"
post /tmp/oaa.jar $B/api/oauth/authorize/decision "$CLAMP_BODY" >/dev/null
ok "a fresh client's scope ceiling is read, so 'write' is clamped down" \
  "$(curl -s -b /tmp/oaa.jar $B/api/me/oauth-grants | j "[g['scope'] for g in d if g['client_name']=='E2E Connector'][0]")" "read"

echo "== token exchange, and every way it should be refused"
TOK=$(curl -s -X POST $B/api/oauth/token -d "grant_type=authorization_code" -d "client_id=$CLIENT_ID" -d "code=$CODE1" -d "redirect_uri=$REDIRECT" -d "code_verifier=$VERIFIER")
ACCESS=$(echo "$TOK" | j "d['access_token']")
REFRESH=$(echo "$TOK" | j "d['refresh_token']")
ok "exchange succeeds"                  "$(echo "$TOK" | j "d['token_type']")" "Bearer"
ok "replaying the same code fails"      "$(curl -s -X POST $B/api/oauth/token -d "grant_type=authorization_code" -d "client_id=$CLIENT_ID" -d "code=$CODE1" -d "redirect_uri=$REDIRECT" -d "code_verifier=$VERIFIER" | j "d['error']")" "invalid_grant"

# A second, fresh code to test the wrong-verifier and wrong-redirect_uri cases independently.
DECIDE_BODY="{\"client_id\":\"$CLIENT_ID\",\"redirect_uri\":\"$REDIRECT\",\"code_challenge\":\"$CHALLENGE\",\"allow\":true,\"scope\":\"read\"}"
DECISION2=$(post /tmp/oaa.jar $B/api/oauth/authorize/decision "$DECIDE_BODY")
CODE2=$(echo "$DECISION2" | python3 -c "import json,sys; from urllib.parse import urlparse, parse_qs; print(parse_qs(urlparse(json.load(sys.stdin)['redirect_to']).query)['code'][0])")
ok "wrong code_verifier is refused"     "$(curl -s -X POST $B/api/oauth/token -d "grant_type=authorization_code" -d "client_id=$CLIENT_ID" -d "code=$CODE2" -d "redirect_uri=$REDIRECT" -d "code_verifier=wrong-one" | j "d['error']")" "invalid_grant"

DECISION3=$(post /tmp/oaa.jar $B/api/oauth/authorize/decision "$DECIDE_BODY")
CODE3=$(echo "$DECISION3" | python3 -c "import json,sys; from urllib.parse import urlparse, parse_qs; print(parse_qs(urlparse(json.load(sys.stdin)['redirect_to']).query)['code'][0])")
ok "mismatched redirect_uri is refused" "$(curl -s -X POST $B/api/oauth/token -d "grant_type=authorization_code" -d "client_id=$CLIENT_ID" -d "code=$CODE3" -d "redirect_uri=https://somewhere-else.example" -d "code_verifier=$VERIFIER" | j "d['error']")" "invalid_grant"

echo "== the MCP endpoint accepts an OAuth access token exactly like a personal one"
ok "organisations"                      "$(mcp_call "$ACCESS" organisations '{}' | j "d['result']['content'][0]['text'].__contains__('$OID')")" "True"
CREATE_ARGS="{\"organisation_id\":\"$OID\",\"title\":\"nope\"}"
ok "read scope is refused by create_task" \
  "$(mcp_call "$ACCESS" create_task "$CREATE_ARGS" | j "d['result']['isError']")" "True"
ok "nothing was created"                "$(curl -s -b /tmp/oaa.jar $B/api/organisations/$OID/tasks | j "sum(1 for t in d if t['title']=='nope')")" "0"

echo "== refresh rotates both tokens, and reusing the old one is treated as theft"
REFRESH_RESP=$(curl -s -X POST $B/api/oauth/token -d "grant_type=refresh_token" -d "client_id=$CLIENT_ID" -d "refresh_token=$REFRESH")
NEW_ACCESS=$(echo "$REFRESH_RESP" | j "d['access_token']")
NEW_REFRESH=$(echo "$REFRESH_RESP" | j "d['refresh_token']")
ok "refresh succeeds"                   "$(echo "$REFRESH_RESP" | j "d['token_type']")" "Bearer"
ok "the new access token works"         "$(mcp_status -H "Authorization: Bearer $NEW_ACCESS")" "200"
ok "the OLD access token still works until it expires" \
  "$(mcp_status -H "Authorization: Bearer $ACCESS")" "200"
ok "replaying the OLD refresh token is refused" \
  "$(curl -s -X POST $B/api/oauth/token -d "grant_type=refresh_token" -d "client_id=$CLIENT_ID" -d "refresh_token=$REFRESH" | j "d['error']")" "invalid_grant"
ok "...and the theft response revoked the grant: the NEW refresh token is now dead too" \
  "$(curl -s -X POST $B/api/oauth/token -d "grant_type=refresh_token" -d "client_id=$CLIENT_ID" -d "refresh_token=$NEW_REFRESH" | j "d['error']")" "invalid_grant"
ok "...and so is the access token it issued" \
  "$(mcp_status -H "Authorization: Bearer $NEW_ACCESS")" "401"

echo "== the account screen: list and revoke"
# The theft test just above deliberately revoked the previous grant — a
# fresh authorize+exchange is what gives this section something real to
# list and a live token to prove revocation actually breaks.
DECISION4=$(post /tmp/oaa.jar $B/api/oauth/authorize/decision "$DECIDE_BODY")
CODE4=$(echo "$DECISION4" | python3 -c "import json,sys; from urllib.parse import urlparse, parse_qs; print(parse_qs(urlparse(json.load(sys.stdin)['redirect_to']).query)['code'][0])")
TOK4=$(curl -s -X POST $B/api/oauth/token -d "grant_type=authorization_code" -d "client_id=$CLIENT_ID" -d "code=$CODE4" -d "redirect_uri=$REDIRECT" -d "code_verifier=$VERIFIER")
LIVE_ACCESS=$(echo "$TOK4" | j "d['access_token']")

GRANT_ID=$(curl -s -b /tmp/oaa.jar $B/api/me/oauth-grants | j "[g['id'] for g in d if g['client_name']=='E2E Connector'][0]")
ok "the grant is listed"                "$(curl -s -b /tmp/oaa.jar $B/api/me/oauth-grants | j "any(g['id']=='$GRANT_ID' for g in d)")" "True"
ok "someone else can't see or revoke it" "$(BOB=oab$S@example.com; signup /tmp/oab.jar $BOB >/dev/null; code -b /tmp/oab.jar -X DELETE $B/api/me/oauth-grants/$GRANT_ID)" "404"
ok "confirmed working before revoke"    "$(mcp_status -H "Authorization: Bearer $LIVE_ACCESS")" "200"
ok "revoking the grant"                 "$(code -b /tmp/oaa.jar -X DELETE $B/api/me/oauth-grants/$GRANT_ID)" "204"
ok "the very next MCP call is refused"  "$(mcp_status -H "Authorization: Bearer $LIVE_ACCESS")" "401"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
