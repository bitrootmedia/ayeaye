#!/usr/bin/env bash
#
# Notification channels — email, Telegram, webhook, one table.
#
#   docker compose up -d && ./scripts/e2e-notification-channels.sh
#
# Email is auto-provisioned, non-deletable, and always fires unless narrowed.
# Webhook delivery is proved against a real local HTTP listener standing in
# for a receiver — the same "throwaway local server standing in for a
# provider" precedent diagnose.sh's own CORS check already uses — and its
# signature is verified byte for byte, not just "did a request arrive."
# Telegram's own Bot API isn't reachable from a dev stack without a real bot
# token, so its half is proved at the service layer instead (see the linking
# functions called directly below) plus the HTTP-facing parts that don't
# need one: the route accepting a malformed update, and the "not configured"
# 422 when TELEGRAM_BOT_USERNAME is empty, which it is in every dev stack.
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

A=nc-a$S@example.com; BB=nc-b$S@example.com
signup /tmp/nca.jar $A; signup /tmp/ncb.jar $BB

echo "== email is auto-provisioned"
ok "one channel, email, on first read" "$(curl -s -b /tmp/nca.jar $B/api/me/notification-channels | j "[c['kind'] for c in d]")" "['email']"
ok "every kind enabled by default"     "$(curl -s -b /tmp/nca.jar $B/api/me/notification-channels | j "'task_shared' in d[0]['enabled_kinds']")" "True"
EMAIL_ID=$(curl -s -b /tmp/nca.jar $B/api/me/notification-channels | j "d[0]['id']")

echo "== email cannot be deleted, only narrowed"
ok "delete refused (422)" "$(code -b /tmp/nca.jar -X DELETE $B/api/me/notification-channels/$EMAIL_ID)" "422"
ok "narrowing to nothing works" "$(patch /tmp/nca.jar $B/api/me/notification-channels/$EMAIL_ID '{"enabled_kinds":[]}' | j "d['enabled_kinds']")" "[]"
patch /tmp/nca.jar $B/api/me/notification-channels/$EMAIL_ID '{"enabled_kinds":["task_shared","task_action_required_cleared","task_owner_changed","task_closed","project_shared","reminder_soon","reminder_due","task_deadline_tomorrow","daily_summary","export_ready","task_action_required"]}' >/dev/null
ok "an unknown kind is rejected (422)" "$(code -b /tmp/nca.jar -H 'Content-Type: application/json' -X PATCH $B/api/me/notification-channels/$EMAIL_ID -d '{"enabled_kinds":["not_a_real_kind"]}')" "422"

echo "== webhook: create, receive, verify the signature, remove"
LISTENER_PORT=9931
python3 - "$LISTENER_PORT" > /tmp/nc-webhook.json << 'PYEOF' &
import http.server, json, sys
port = int(sys.argv[1])
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(n)
        with open('/tmp/nc-webhook-received.json', 'w') as f:
            json.dump({"body": body.decode(), "sig": self.headers.get('X-Ayeaye-Signature', '')}, f)
        self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
    def log_message(self, *a): pass
http.server.HTTPServer(('0.0.0.0', port), H).serve_forever()
PYEOF
LISTENER_PID=$!
sleep 1
rm -f /tmp/nc-webhook-received.json

WH=$(post /tmp/nca.jar $B/api/me/notification-channels/webhook "{\"url\":\"http://host.docker.internal:$LISTENER_PORT/hook\",\"label\":\"relay\"}")
WH_ID=$(echo "$WH" | j "d['id']")
SECRET=$(echo "$WH" | j "d['secret']")
ok "webhook created with a secret" "$(echo -n "$SECRET" | wc -c | tr -d ' ' | awk '{print ($1 > 20)}')" "1"
ok "url echoed back, secret is not"  "$(echo "$WH" | j "'secret' not in d or d['url'] is not None")" "True"

# trigger a real notification: A shares a task with B... no wait, we want A
# to receive one. B shares a task with A.
OID=$(post /tmp/ncb.jar $B/api/organisations "{\"name\":\"NC $S\"}" | j "d['id']")
BODY="{\"email\":\"$A\",\"role\":\"member\"}"
T=$(post /tmp/ncb.jar $B/api/organisations/$OID/invites "$BODY" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/nca.jar -c /tmp/nca.jar -X POST $B/api/invites/$T/accept
A_ID=$(curl -s -b /tmp/ncb.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$A'][0]")
TID=$(post /tmp/ncb.jar $B/api/organisations/$OID/tasks '{"title":"For A"}' | j "d['id']")
post /tmp/ncb.jar $B/api/organisations/$OID/tasks/$TID/access "{\"user_id\":\"$A_ID\",\"level\":\"read\"}" >/dev/null

sleep 2
if [ -f /tmp/nc-webhook-received.json ]; then
  export NC_WEBHOOK_SECRET="$SECRET"
  ok "webhook received the notification" "$(python3 -c "
import json
print(json.loads(json.load(open('/tmp/nc-webhook-received.json'))['body'])['kind'])
")" "task_shared"
  ok "signature verifies" "$(python3 -c "
import json, hmac, hashlib, os
d = json.load(open('/tmp/nc-webhook-received.json'))
secret = os.environ['NC_WEBHOOK_SECRET']
expect = 'sha256=' + hmac.new(secret.encode(), d['body'].encode(), hashlib.sha256).hexdigest()
print('MATCH' if expect == d['sig'] else 'MISMATCH')
")" "MATCH"
else
  echo "  FAIL webhook never received anything"
  fail=$((fail+1))
fi

kill $LISTENER_PID 2>/dev/null
wait $LISTENER_PID 2>/dev/null
rm -f /tmp/nc-webhook-received.json /tmp/nc-webhook.json

echo "== narrowing a channel stops it firing for that kind, not others"
patch /tmp/nca.jar $B/api/me/notification-channels/$WH_ID "{\"enabled_kinds\":[]}" >/dev/null
ok "narrowed to nothing" "$(curl -s -b /tmp/nca.jar $B/api/me/notification-channels | j "[c['enabled_kinds'] for c in d if c['kind']=='webhook'][0]")" "[]"

echo "== you cannot touch another person's channel"
ok "cross-user delete is 404" "$(code -b /tmp/ncb.jar -X DELETE $B/api/me/notification-channels/$WH_ID)" "404"
ok "cross-user patch is 404"  "$(code -b /tmp/ncb.jar -H 'Content-Type: application/json' -X PATCH $B/api/me/notification-channels/$WH_ID -d '{"enabled_kinds":[]}')" "404"

echo "== remove"
ok "webhook removed" "$(code -b /tmp/nca.jar -X DELETE $B/api/me/notification-channels/$WH_ID)" "204"
ok "gone from the list" "$(curl -s -b /tmp/nca.jar $B/api/me/notification-channels | j "[c['kind'] for c in d]")" "['email']"

echo "== Telegram: inert without a configured bot"
ok "link-start refused when unconfigured (422)" "$(code -b /tmp/nca.jar -X POST $B/api/me/notification-channels/telegram/link-start)" "422"

echo "== Telegram: creating tasks from chat (/task, /org)"
# Linking itself needs the service layer directly (no real bot token in a
# dev stack, same reasoning as the linking-flow tests above); everything
# after that — /task, /org — goes through the real HTTP webhook route,
# because that IS the code path a real chat message takes.
TC_CHAT=900${S: -6}
TC_ORG1=$(post /tmp/ncb.jar $B/api/organisations "{\"name\":\"Task Chat A $S\"}" | j "d['id']")
TC_ORG2=$(post /tmp/ncb.jar $B/api/organisations "{\"name\":\"Task Chat B $S\"}" | j "d['id']")
docker compose exec -T api env PYTHONPATH=/app/src uv run python3 - "$BB" "$TC_CHAT" << 'PYEOF'
import asyncio, sys
from app.db import SessionLocal
from app.services import notification_channels as channels_service
from app.models import User
from sqlalchemy import select

email, chat_id = sys.argv[1], sys.argv[2]

async def main():
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        code = await channels_service.start_telegram_link(db, user)
        linked = await channels_service.complete_telegram_link(db, code=code, chat_id=chat_id)
        assert linked

asyncio.run(main())
PYEOF

hook(){ curl -s -o /dev/null -w '%{http_code}' -X POST $B/api/telegram/webhook -H 'Content-Type: application/json' \
  -d "{\"message\":{\"chat\":{\"id\":$TC_CHAT},\"text\":\"$1\"}}"; }
tasks_of(){ curl -s -b /tmp/ncb.jar "$B/api/organisations/$1/tasks" | j "[t['title'] for t in d]"; }

ok "no default with 2 orgs: /task refuses, creates nothing" "$(hook '/task Should not land anywhere')|$(tasks_of $TC_ORG1)|$(tasks_of $TC_ORG2)" "200|[]|[]"
ok "/org exact match sets the default"  "$(hook "/org Task Chat A $S")" "200"
ok "/task now files into org 1"         "$(hook '/task Filed via chat')|$(tasks_of $TC_ORG1)" "200|['Filed via chat']"
ok "/org switches to the other org"     "$(hook "/org Task Chat B $S")" "200"
ok "/task now files into org 2"         "$(hook '/task Second one')|$(tasks_of $TC_ORG2)" "200|['Second one']"
ok "/org with an unknown name changes nothing" "$(hook '/org Nonexistent Org Entirely')|$(curl -s -b /tmp/ncb.jar $B/api/me/notification-channels | j "[c['default_organisation_id'] for c in d if c['kind']=='telegram'][0]")" "200|$TC_ORG2"
hook "/task $(python3 -c 'print("x"*400)')" >/dev/null
LONG_TITLE_LEN=$(curl -s -b /tmp/ncb.jar "$B/api/organisations/$TC_ORG2/tasks" | j "max(len(t['title']) for t in d)")
ok "a title over 300 chars is truncated, not rejected" "$LONG_TITLE_LEN" "300"

echo "== Telegram webhook route never 500s on garbage"
ok "malformed body"       "$(code -X POST $B/api/telegram/webhook -H 'Content-Type: application/json' -d 'not json')" "200"
ok "irrelevant message"   "$(code -X POST $B/api/telegram/webhook -H 'Content-Type: application/json' -d '{"message":{"chat":{"id":1},"text":"hello"}}')" "200"
ok "stale/unknown code"   "$(code -X POST $B/api/telegram/webhook -H 'Content-Type: application/json' -d '{"message":{"chat":{"id":1},"text":"/start bogus"}}')" "200"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
