#!/usr/bin/env bash
#
# Phase 6a end-to-end: comment threads, their access, notification debouncing
# and realtime delivery.
#
#   docker compose up -d && ./scripts/e2e-comments.sh
#
# The debounce is the part worth testing hardest: it fails *silently* in both
# directions. Too eager and a back-and-forth is one email per line; too lazy
# and the notification nobody got is the one that mattered.
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
say(){ post "$1" "$2" "{\"body\":\"$3\"}"; }

A=ca$S@example.com; BB=cb$S@example.com; C=cc$S@example.com
signup /tmp/ca.jar $A; signup /tmp/cb.jar $BB; signup /tmp/cc.jar $C

OID=$(post /tmp/ca.jar $B/api/organisations "{\"name\":\"Talk $S\"}" | j "d['id']")
join(){ T=$(post /tmp/ca.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"$3\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/cb.jar $BB member
join /tmp/cc.jar $C member
uid(){ curl -s -b /tmp/ca.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$1'][0]"; }
BUID=$(uid $BB); CUID=$(uid $C)

PID=$(post /tmp/ca.jar $B/api/organisations/$OID/projects '{"name":"Refit"}' | j "d['id']")
TID=$(post /tmp/ca.jar $B/api/organisations/$OID/tasks "{\"title\":\"Survey the keel\",\"project_id\":\"$PID\"}" | j "d['id']")
TASKC=$B/api/organisations/$OID/tasks/$TID/comments
PROJC=$B/api/organisations/$OID/projects/$PID/comments

echo "== a thread appears when someone uses it"
ok "empty to begin with"        "$(curl -s -b /tmp/ca.jar $TASKC | j "len(d['messages'])")" "0"
ok "owner may post"             "$(curl -s -b /tmp/ca.jar $TASKC | j "str(d['can_post'])")" "True"
M1=$(say /tmp/ca.jar $TASKC "Keel looks sound")
ok "the comment lands"          "$(echo "$M1" | j "d['body']")" "Keel looks sound"
ok "and is attributed"          "$(echo "$M1" | j "d['author']['email']")" "$A"
ok "it reads back"              "$(curl -s -b /tmp/ca.jar $TASKC | j "d['messages'][0]['body']")" "Keel looks sound"
ok "empty comments refused"     "$(code -b /tmp/ca.jar -H 'Content-Type: application/json' -X POST $TASKC -d '{"body":"   "}')" "422"

echo "== a thread is as private as what it hangs off"
ok "no access to the task: 404" "$(code -b /tmp/cb.jar $TASKC)" "404"
ok "nor can they post: 404"     "$(code -b /tmp/cb.jar -H 'Content-Type: application/json' -X POST $TASKC -d '{"body":"hello"}')" "404"
post /tmp/ca.jar $B/api/organisations/$OID/projects/$PID/access "{\"user_id\":\"$BUID\",\"level\":\"read\"}" >/dev/null
ok "project access reveals it"  "$(curl -s -b /tmp/cb.jar $TASKC | j "len(d['messages'])")" "1"

echo "== read access is enough to comment"
# A comment is a contribution, not a change to the work — the commonest reason
# to share something read-only is to get somebody's input.
ok "a viewer may post"          "$(curl -s -b /tmp/cb.jar $TASKC | j "str(d['can_post'])")" "True"
M2=$(say /tmp/cb.jar $TASKC "Found some osmosis")
ok "and it lands"               "$(echo "$M2" | j "d['body']")" "Found some osmosis"
ok "but still cannot edit the task" "$(code -b /tmp/cb.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/tasks/$TID -d '{"title":"Mine"}')" "403"

echo "== your own words"
M2ID=$(echo "$M2" | j "d['id']")
ok "the author edits"           "$(curl -s -b /tmp/cb.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/comments/$M2ID -d '{"body":"Found osmosis, port side"}' | j "d['body']")" "Found osmosis, port side"
ok "and it is marked edited"    "$(curl -s -b /tmp/cb.jar $TASKC | j "str([m['edited_at'] for m in d['messages'] if m['id']=='$M2ID'][0] is not None)")" "True"
ok "someone with no access: 404" "$(code -b /tmp/cc.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/comments/$M2ID -d '{"body":"no"}')" "404"

# Owning the work does not make you the editor of what people said about it.
# Tested between two PLAIN members: Alice is the org owner and would be allowed
# for a different reason entirely, which is exactly the confusion this guards.
BT=$(post /tmp/cb.jar $B/api/organisations/$OID/tasks '{"title":"Bobs own task"}' | j "d['id']")
post /tmp/cb.jar $B/api/organisations/$OID/tasks/$BT/access "{\"user_id\":\"$CUID\",\"level\":\"read\"}" >/dev/null
CM=$(say /tmp/cc.jar $B/api/organisations/$OID/tasks/$BT/comments "Carol was here" | j "d['id']")
ok "the task owner cannot edit it" "$(code -b /tmp/cb.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/comments/$CM -d '{"body":"no"}')" "403"
ok "nor delete it"                 "$(code -b /tmp/cb.jar -X DELETE $B/api/organisations/$OID/comments/$CM)" "403"
ok "but an org admin can"          "$(code -b /tmp/ca.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/comments/$CM -d '{"body":"tidied"}')" "200"

echo "== deleting leaves a tombstone, not a hole"
DEL=$(curl -s -b /tmp/cb.jar -X DELETE $B/api/organisations/$OID/comments/$M2ID)
ok "marked deleted"             "$(echo "$DEL" | j "str(d['deleted'])")" "True"
ok "the body is gone"           "$(echo "$DEL" | j "d['body']")" ""
ok "the row remains in order"   "$(curl -s -b /tmp/ca.jar $TASKC | j "len(d['messages'])")" "2"

echo "== notification debouncing"
# Bob has a stake (he has spoken). Alice replies three times; that is ONE
# notification, not three — the whole point of debouncing on the unread run.
before=$(curl -s -b /tmp/cb.jar $B/api/notifications | j "sum(1 for n in d if 'commented on' in n['title'])")
say /tmp/ca.jar $TASKC "Reply one" >/dev/null
say /tmp/ca.jar $TASKC "Reply two" >/dev/null
say /tmp/ca.jar $TASKC "Reply three" >/dev/null
after=$(curl -s -b /tmp/cb.jar $B/api/notifications | j "sum(1 for n in d if 'commented on' in n['title'])")
ok "three replies, one notification" "$(python3 -c "print($after - $before)")" "1"
ok "he has three unread"        "$(curl -s -b /tmp/cb.jar $TASKC | j "d['unread']")" "3"
# Reading the thread clears the run, so the next reply notifies again.
curl -s -o /dev/null -b /tmp/cb.jar $TASKC
ok "reading marks it read"      "$(curl -s -b /tmp/cb.jar $TASKC | j "d['unread']")" "0"
say /tmp/ca.jar $TASKC "Reply four" >/dev/null
after2=$(curl -s -b /tmp/cb.jar $B/api/notifications | j "sum(1 for n in d if 'commented on' in n['title'])")
ok "after reading, it notifies again" "$(python3 -c "print($after2 - $after)")" "1"

echo "== you are never notified about your own comment"
# Alice legitimately has notifications here — Bob commented on her task. What
# must be true is that HER posting adds none.
mine_before=$(curl -s -b /tmp/ca.jar $B/api/notifications | j "sum(1 for n in d if 'commented on' in n['title'])")
say /tmp/ca.jar $TASKC "Talking to myself" >/dev/null
mine_after=$(curl -s -b /tmp/ca.jar $B/api/notifications | j "sum(1 for n in d if 'commented on' in n['title'])")
ok "posting notifies nobody about themselves" "$(python3 -c "print($mine_after - $mine_before)")" "0"
ok "and their own post is read" "$(curl -s -b /tmp/ca.jar $TASKC | j "d['unread']")" "0"

echo "== projects have threads too"
ok "project thread is empty"    "$(curl -s -b /tmp/ca.jar $PROJC | j "len(d['messages'])")" "0"
ok "and takes a comment"        "$(say /tmp/ca.jar $PROJC "Kick-off Monday" | j "d['body']")" "Kick-off Monday"
ok "separate from the task's"   "$(curl -s -b /tmp/ca.jar $TASKC | j "sum(1 for m in d['messages'] if m['body']=='Kick-off Monday')")" "0"
ok "a viewer sees it"           "$(curl -s -b /tmp/cb.jar $PROJC | j "len(d['messages'])")" "1"
ok "an outsider does not: 404"  "$(code -b /tmp/cc.jar $PROJC)" "404"

echo "== realtime"
# The socket carries no content — just "conversation X moved". Run with the
# API's own interpreter: `websockets` ships with uvicorn[standard], so there is
# nothing extra to install on the host.
export TASKC
PYWS=(uv run --project apps/api --quiet python)
if "${PYWS[@]}" -c "import websockets" 2>/dev/null; then
  if "${PYWS[@]}" - <<'PYEOF'
import asyncio, json, os, urllib.request
from websockets.asyncio.client import connect

def cookies(jar):
    # curl writes HttpOnly cookies with a "#HttpOnly_" prefix, so a naive
    # "skip lines starting with #" drops the session cookie — which is the
    # only one that matters here.
    out = []
    for line in open(jar):
        line = line.removeprefix("#HttpOnly_")
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            out.append(f"{parts[5]}={parts[6].strip()}")
    return "; ".join(out)

async def main():
    async with connect(
        "ws://localhost/api/ws", additional_headers={"Cookie": cookies("/tmp/cb.jar")}
    ) as ws:
        req = urllib.request.Request(
            os.environ["TASKC"],
            data=json.dumps({"body": "live ping"}).encode(),
            headers={"Content-Type": "application/json", "Cookie": cookies("/tmp/ca.jar")},
            method="POST",
        )
        urllib.request.urlopen(req).read()
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert event["type"] == "message", event
        # The whole design: one authorisation path for content. If a body ever
        # rides the socket, it has bypassed the access check on the way out.
        assert "live ping" not in json.dumps(event), "the socket must not carry content"

asyncio.run(main())
PYEOF
  then
    echo "  ok   the socket delivers to a participant"
    echo "  ok   and carries no message content"
    pass=$((pass+2))
  else
    echo "  FAIL realtime delivery"; fail=$((fail+1))
  fi

  echo "== the socket needs a session"
  ok "no cookie is refused" "$("${PYWS[@]}" -c "
import asyncio
from websockets.asyncio.client import connect
async def main():
    try:
        async with connect('ws://localhost/api/ws') as ws:
            await asyncio.wait_for(ws.recv(), timeout=3)
            print('accepted')
    except Exception:
        print('refused')
asyncio.run(main())")" "refused"
else
  echo "  ..   realtime skipped (no websockets client available)"
fi

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
