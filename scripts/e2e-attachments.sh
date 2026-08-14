#!/usr/bin/env bash
#
# Phase 6b end-to-end: the three-step upload handshake.
#
#   docker compose up -d && ./scripts/e2e-attachments.sh
#
# Most of this file is about **step 3**, because with a presigned PUT the bytes
# never pass through the API and confirm is the only moment it can look at what
# actually landed. A client that declares "image/png, 2KB" and uploads 60MB of
# something else is caught there or not at all.
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

A=fa$S@example.com; BB=fb$S@example.com
signup /tmp/fa.jar $A; signup /tmp/fb.jar $BB

OID=$(post /tmp/fa.jar $B/api/organisations "{\"name\":\"Files $S\"}" | j "d['id']")
T=$(post /tmp/fa.jar $B/api/organisations/$OID/invites "{\"email\":\"$BB\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/fb.jar -X POST $B/api/invites/$T/accept
TID=$(post /tmp/fa.jar $B/api/organisations/$OID/tasks '{"title":"Photo evidence"}' | j "d['id']")
ATT=$B/api/organisations/$OID/tasks/$TID/attachments
CONF=$B/api/organisations/$OID/attachments

# A tiny real PNG, so RustFS is storing genuine bytes rather than a text file
# wearing an image content type.
python3 -c "
import base64,sys
sys.stdout.buffer.write(base64.b64decode(
 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='))
" > /tmp/dot.png

echo "== step 1: the ticket"
TICKET=$(post /tmp/fa.jar $ATT '{"filename":"dot.png","content_type":"image/png"}')
AID=$(echo "$TICKET" | j "d['attachment']['id']")
URL=$(echo "$TICKET" | j "d['upload_url']")
ok "a ticket comes back"        "$(echo "$TICKET" | j "d['content_type']")" "image/png"
ok "signed for the public host" "$(echo "$TICKET" | j "d['upload_url'].startswith('$B/media/')")" "True"
ok "the key is not the filename" "$(echo "$TICKET" | j "'dot.png' in d['upload_url'] and 'comments/' in d['upload_url']")" "True"
ok "a disallowed type is refused" "$(code -b /tmp/fa.jar -H 'Content-Type: application/json' -X POST $ATT -d '{"filename":"x.exe","content_type":"application/x-msdownload"}')" "422"
# The codec parameter has to be stripped: SigV4 covers Content-Type byte for
# byte, so what comes home is what the client must send.
ok "codec parameters are stripped" "$(post /tmp/fa.jar $ATT '{"filename":"note.webm","content_type":"audio/webm;codecs=opus"}' | j "d['content_type']")" "audio/webm"

echo "== step 2: the browser PUTs straight to storage"
# No session cookie: the presigned URL IS the authorisation, and the bytes
# never touch the API.
ok "the PUT is accepted"        "$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H 'Content-Type: image/png' --data-binary @/tmp/dot.png "$URL")" "200"
ok "the wrong content type fails the signature" "$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H 'Content-Type: image/jpeg' --data-binary @/tmp/dot.png "$URL")" "403"

echo "== step 3: confirm is the only inspection"
CONFIRMED=$(post /tmp/fa.jar $CONF/$AID/confirm '{}')
ok "size comes from the object"  "$(echo "$CONFIRMED" | j "d['size_bytes'] == $(wc -c < /tmp/dot.png | tr -d ' ')")" "True"
ok "and a view URL is minted"    "$(echo "$CONFIRMED" | j "d['url'].startswith('$B/media/')")" "True"
ok "confirming twice is fine"    "$(code -b /tmp/fa.jar -H 'Content-Type: application/json' -X POST $CONF/$AID/confirm -d '{}')" "200"
# Nothing was ever uploaded for this one.
GHOST=$(post /tmp/fa.jar $ATT '{"filename":"ghost.png","content_type":"image/png"}' | j "d['attachment']['id']")
ok "confirming a no-show: 409"   "$(code -b /tmp/fa.jar -H 'Content-Type: application/json' -X POST $CONF/$GHOST/confirm -d '{}')" "409"
ok "someone else cannot confirm yours" "$(code -b /tmp/fb.jar -H 'Content-Type: application/json' -X POST $CONF/$AID/confirm -d '{}')" "404"

echo "== the size limit is enforced against the real bytes"
# Declared as a small png in step 1; 60MB actually uploaded. Only step 3 can
# possibly notice.
python3 -c "open('/tmp/big.bin','wb').write(b'0'*(60*1024*1024))"
BIGT=$(post /tmp/fa.jar $ATT '{"filename":"big.png","content_type":"image/png"}')
BID=$(echo "$BIGT" | j "d['attachment']['id']")
curl -s -o /dev/null -X PUT -H 'Content-Type: image/png' --data-binary @/tmp/big.bin "$(echo "$BIGT" | j "d['upload_url']")"
ok "an oversized upload is rejected" "$(code -b /tmp/fa.jar -H 'Content-Type: application/json' -X POST $CONF/$BID/confirm -d '{}')" "413"
ok "and the row is gone"         "$(code -b /tmp/fa.jar -H 'Content-Type: application/json' -X POST $CONF/$BID/confirm -d '{}')" "404"
rm -f /tmp/big.bin

echo "== binding to a comment"
M=$(post /tmp/fa.jar $B/api/organisations/$OID/tasks/$TID/comments "{\"body\":\"Here it is\",\"attachment_ids\":[\"$AID\"]}")
ok "the comment carries the file" "$(echo "$M" | j "d['attachments'][0]['filename']")" "dot.png"
ok "it reads back on the thread"  "$(curl -s -b /tmp/fa.jar $B/api/organisations/$OID/tasks/$TID/comments | j "d['messages'][0]['attachments'][0]['filename']")" "dot.png"
ok "with a fresh URL each time"   "$(curl -s -b /tmp/fa.jar $B/api/organisations/$OID/tasks/$TID/comments | j "'X-Amz-Signature' in d['messages'][0]['attachments'][0]['url']")" "True"
# An id already spent cannot be attached to a second comment.
M2=$(post /tmp/fa.jar $B/api/organisations/$OID/tasks/$TID/comments "{\"body\":\"Again\",\"attachment_ids\":[\"$AID\"]}")
ok "an id cannot be reused"       "$(echo "$M2" | j "len(d['attachments'])")" "0"

echo "== you cannot borrow someone else's upload"
# Bob has no access to Alice's loose task at all.
ok "no access to the thread: 404" "$(code -b /tmp/fb.jar -H 'Content-Type: application/json' -X POST $ATT -d '{"filename":"x.png","content_type":"image/png"}')" "404"
# Give Bob access, then check he still can't attach Alice's staged upload to
# his own comment: binding is scoped to the uploader.
AUID=$(curl -s -b /tmp/fa.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$A'][0]")
BUID=$(curl -s -b /tmp/fa.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$BB'][0]")
post /tmp/fa.jar $B/api/organisations/$OID/tasks/$TID/access "{\"user_id\":\"$BUID\",\"level\":\"read\"}" >/dev/null
STAGED=$(post /tmp/fa.jar $ATT '{"filename":"mine.png","content_type":"image/png"}')
SID=$(echo "$STAGED" | j "d['attachment']['id']")
curl -s -o /dev/null -X PUT -H 'Content-Type: image/png' --data-binary @/tmp/dot.png "$(echo "$STAGED" | j "d['upload_url']")"
post /tmp/fa.jar $CONF/$SID/confirm '{}' >/dev/null
BM=$(post /tmp/fb.jar $B/api/organisations/$OID/tasks/$TID/comments "{\"body\":\"Not mine\",\"attachment_ids\":[\"$SID\"]}")
ok "binding is scoped to the uploader" "$(echo "$BM" | j "len(d['attachments'])")" "0"
ok "a viewer can attach their own"     "$(code -b /tmp/fb.jar -H 'Content-Type: application/json' -X POST $ATT -d '{"filename":"his.png","content_type":"image/png"}')" "201"

echo "== unconfirmed uploads never appear"
UNSEEN=$(post /tmp/fa.jar $ATT '{"filename":"pending.png","content_type":"image/png"}' | j "d['attachment']['id']")
PM=$(post /tmp/fa.jar $B/api/organisations/$OID/tasks/$TID/comments "{\"body\":\"Nothing attached\",\"attachment_ids\":[\"$UNSEEN\"]}")
ok "a pending upload does not bind" "$(echo "$PM" | j "len(d['attachments'])")" "0"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
