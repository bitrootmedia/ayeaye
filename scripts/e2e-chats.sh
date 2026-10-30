#!/usr/bin/env bash
#
# Chats end-to-end: DMs and groups, the privacy rule that stops at the org
# admin, the one list of every conversation you're in, and presence.
#
#   docker compose up -d && ./scripts/e2e-chats.sh
#
# The privacy rule is the one worth testing hardest: an organisation admin can
# open every task in the company, and a DM is the one thing they must not. It
# fails silently — nothing errors, the admin just reads somebody's messages.
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
put(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PUT "$2" -d "$3"; }
say(){ post "$1" "$2" "{\"body\":\"$3\"}"; }
nots(){ curl -s -b "$1" $B/api/notifications | j "sum(1 for n in d if n['kind']=='$2')"; }

# Alice owns the organisation (so she is its admin), Bob and Carol are members.
A=ha$S@example.com; BB=hb$S@example.com; C=hc$S@example.com
signup /tmp/ha.jar $A; signup /tmp/hb.jar $BB; signup /tmp/hc.jar $C
OID=$(post /tmp/ha.jar $B/api/organisations "{\"name\":\"Chat $S\"}" | j "d['id']")
join(){ T=$(post /tmp/ha.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"$3\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/hb.jar $BB member
join /tmp/hc.jar $C member
uid(){ curl -s -b /tmp/ha.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$1'][0]"; }
AUID=$(uid $A); BUID=$(uid $BB); CUID=$(uid $C)
O=$B/api/organisations/$OID

echo "== a DM is one thread per pair"
DM=$(post /tmp/hb.jar $O/chats/direct "{\"user_id\":\"$CUID\"}" | j "d['id']")
ok "the other side opens the same one" "$(post /tmp/hc.jar $O/chats/direct "{\"user_id\":\"$BUID\"}" | j "d['id']")" "$DM"
ok "named after the other person"       "$(curl -s -b /tmp/hb.jar $O/chats/$DM | j "d['title']")" "$C"
ok "an empty DM isn't in Carol's list"  "$(curl -s -b /tmp/hc.jar $O/chats | j "len([c for c in d if c['id']=='$DM'])")" "0"
ok "but is in Bob's, who started it"    "$(curl -s -b /tmp/hb.jar $O/chats | j "len([c for c in d if c['id']=='$DM'])")" "1"
ok "a stranger to the org: 404"         "$(code -b /tmp/hb.jar -H 'Content-Type: application/json' -X POST $O/chats/direct -d "{\"user_id\":\"$(python3 -c 'import uuid;print(uuid.uuid4())')\"}")" "404"

echo "== messages, replies, unread"
M1=$(say /tmp/hb.jar $O/chats/$DM/messages "Lunch?" | j "d['id']")
ok "now Carol has it"                   "$(curl -s -b /tmp/hc.jar $O/chats | j "[c['unread'] for c in d if c['id']=='$DM'][0]")" "1"
ok "with a preview"                     "$(curl -s -b /tmp/hc.jar $O/chats | j "[c['last_message']['body'] for c in d if c['id']=='$DM'][0]")" "Lunch?"
R=$(post /tmp/hc.jar $O/chats/$DM/messages "{\"body\":\"Sure\",\"reply_to_id\":\"$M1\"}")
ok "a reply quotes the original"        "$(echo "$R" | j "d['reply_to']['body']")" "Lunch?"
ok "replying into another thread: 422"  "$(code -b /tmp/hb.jar -H 'Content-Type: application/json' -X POST $O/chats/$DM/messages -d "{\"body\":\"x\",\"reply_to_id\":\"$(python3 -c 'import uuid;print(uuid.uuid4())')\"}")" "422"
ok "Bob has one unread"                 "$(curl -s -b /tmp/hb.jar $O/chats/unread | j "d['messages']")" "1"
curl -s -o /dev/null -b /tmp/hb.jar -H 'Content-Type: application/json' -X POST $O/chats/$DM/read -d '{}'
ok "reading clears it"                  "$(curl -s -b /tmp/hb.jar $O/chats/unread | j "d['messages']")" "0"
ok "the page knows what's older"        "$(curl -s -b /tmp/hb.jar "$O/chats/$DM/messages?limit=1" | j "str(d['has_more'])")" "True"
ok "and pages back to it"               "$(curl -s -b /tmp/hb.jar "$O/chats/$DM/messages?limit=1&before=$(echo "$R" | j "d['id']")" | j "d['messages'][0]['body']")" "Lunch?"

echo "== an org admin cannot see a DM"
# Alice owns the organisation and can open every task in it. Not this.
ok "reading it: 404"                    "$(code -b /tmp/ha.jar $O/chats/$DM)" "404"
ok "its messages: 404"                  "$(code -b /tmp/ha.jar $O/chats/$DM/messages)" "404"
ok "posting into it: 404"               "$(code -b /tmp/ha.jar -H 'Content-Type: application/json' -X POST $O/chats/$DM/messages -d '{"body":"hi"}')" "404"
ok "editing a message in it: 404"       "$(code -b /tmp/ha.jar -H 'Content-Type: application/json' -X PATCH $O/comments/$M1 -d '{"body":"mine now"}')" "404"
ok "deleting one: 404"                  "$(code -b /tmp/ha.jar -X DELETE $O/comments/$M1)" "404"
ok "not in her list"                    "$(curl -s -b /tmp/ha.jar $O/chats | j "len([c for c in d if c['id']=='$DM'])")" "0"
ok "not found by searching"             "$(curl -s -b /tmp/ha.jar "$O/chats?q=Lunch" | j "len(d)")" "0"

echo "== your own words, and only yours"
ok "Carol can't edit Bob's message"     "$(code -b /tmp/hc.jar -H 'Content-Type: application/json' -X PATCH $O/comments/$M1 -d '{"body":"no"}')" "403"
ok "Bob can"                            "$(curl -s -b /tmp/hb.jar -H 'Content-Type: application/json' -X PATCH $O/comments/$M1 -d '{"body":"Lunch at 1?"}' | j "d['body']")" "Lunch at 1?"
ok "and delete it"                      "$(curl -s -b /tmp/hb.jar -X DELETE $O/comments/$M1 | j "str(d['deleted'])")" "True"
ok "the quote now says it's gone"       "$(curl -s -b /tmp/hc.jar $O/chats/$DM/messages | j "str(d['messages'][1]['reply_to']['deleted'])")" "True"

echo "== DM notifications: one per unread run, none when muted"
n0=$(nots /tmp/hc.jar direct_message)
say /tmp/hb.jar $O/chats/$DM/messages "one" >/dev/null
say /tmp/hb.jar $O/chats/$DM/messages "two" >/dev/null
ok "two messages, one notification"     "$(python3 -c "print($(nots /tmp/hc.jar direct_message) - $n0)")" "1"
curl -s -o /dev/null -b /tmp/hc.jar -H 'Content-Type: application/json' -X POST $O/chats/$DM/read -d '{}'
put /tmp/hc.jar $O/chats/$DM/state '{"muted":true}' >/dev/null
n1=$(nots /tmp/hc.jar direct_message)
say /tmp/hb.jar $O/chats/$DM/messages "three" >/dev/null
ok "muted: nothing"                     "$(python3 -c "print($(nots /tmp/hc.jar direct_message) - $n1)")" "0"
ok "and it's out of the total badge"    "$(curl -s -b /tmp/hc.jar $O/chats/unread | j "d['messages']")" "0"
ok "but still counted on the chat"      "$(curl -s -b /tmp/hc.jar $O/chats | j "[c['unread'] for c in d if c['id']=='$DM'][0]")" "1"

echo "== groups"
G=$(post /tmp/hb.jar $O/chats/groups "{\"title\":\"Lunch club\",\"user_ids\":[\"$CUID\"]}" | j "d['id']")
ok "named"                              "$(curl -s -b /tmp/hc.jar $O/chats/$G | j "d['title']")" "Lunch club"
ok "the admin isn't in it: 404"         "$(code -b /tmp/ha.jar $O/chats/$G)" "404"
ok "a member can add her"               "$(post /tmp/hc.jar $O/chats/$G/members "{\"user_ids\":[\"$AUID\"]}" | j "len(d['members'])")" "3"
ok "and now she's in"                   "$(code -b /tmp/ha.jar $O/chats/$G)" "200"
ok "but she can't edit Bob's words"     "$(code -b /tmp/ha.jar -H 'Content-Type: application/json' -X PATCH $O/comments/$(say /tmp/hb.jar $O/chats/$G/messages "hello club" | j "d['id']") -d '{"body":"no"}')" "403"
ok "a mention in a group notifies"      "$(say /tmp/hb.jar $O/chats/$G/messages "@$C bring forks" >/dev/null; curl -s -b /tmp/hc.jar $B/api/notifications | j "sum(1 for n in d if n['kind']=='comment_mention' and 'Lunch club' in n['title'])")" "1"
ok "only its starter removes others"    "$(code -b /tmp/hc.jar -X DELETE $O/chats/$G/members/$AUID)" "403"
ok "anyone can leave"                   "$(code -b /tmp/ha.jar -X DELETE $O/chats/$G/members/$AUID)" "204"
ok "and having left, it's gone"         "$(code -b /tmp/ha.jar $O/chats/$G)" "404"
ok "a DM has no members to add"         "$(code -b /tmp/hb.jar -H 'Content-Type: application/json' -X POST $O/chats/$DM/members -d "{\"user_ids\":[\"$AUID\"]}")" "409"

echo "== task threads are in the list for whoever has a stake"
PID=$(post /tmp/ha.jar $O/projects '{"name":"Refit"}' | j "d['id']")
TID=$(post /tmp/ha.jar $O/tasks "{\"title\":\"Survey the keel $S\",\"project_id\":\"$PID\"}" | j "d['id']")
post /tmp/ha.jar $O/projects/$PID/access "{\"user_id\":\"$BUID\",\"level\":\"read\"}" >/dev/null
say /tmp/hb.jar $O/tasks/$TID/comments "Osmosis, port side" >/dev/null
TC=$(curl -s -b /tmp/ha.jar $O/chats | j "[c['id'] for c in d if c['kind']=='task' and c['task']['id']=='$TID'][0]")
ok "the owner sees the comment there"   "$(curl -s -b /tmp/ha.jar $O/chats/$TC | j "d['unread']")" "1"
ok "titled after the task"              "$(curl -s -b /tmp/ha.jar $O/chats/$TC | j "d['title']")" "Survey the keel $S"
ok "replying from Chats is a comment"   "$(say /tmp/ha.jar $O/chats/$TC/messages "Noted" >/dev/null; curl -s -b /tmp/ha.jar $O/tasks/$TID/comments | j "d['messages'][-1]['body']")" "Noted"
ok "Carol, with no stake, hasn't it"    "$(curl -s -b /tmp/hc.jar $O/chats | j "len([c for c in d if c['id']=='$TC'])")" "0"
ok "nor can she open it"                "$(code -b /tmp/hc.jar $O/chats/$TC)" "404"
ok "search finds it by what was said"   "$(curl -s -b /tmp/ha.jar "$O/chats?q=osmosis" | j "[c['id'] for c in d][0]")" "$TC"
ok "filtered to tasks"                  "$(curl -s -b /tmp/ha.jar "$O/chats?filter=tasks" | j "all(c['kind']=='task' for c in d)")" "True"
ok "Bob has it before"                  "$(curl -s -b /tmp/hb.jar $O/chats | j "len([c for c in d if c['id']=='$TC'])")" "1"
GR=$(curl -s -b /tmp/ha.jar $O/projects/$PID/access | j "d['grants'][0]['id']")
curl -s -o /dev/null -b /tmp/ha.jar -X DELETE $O/projects/$PID/access/$GR
ok "losing access drops it from Bob's"  "$(curl -s -b /tmp/hb.jar $O/chats | j "len([c for c in d if c['id']=='$TC'])")" "0"
ok "and he can't open it by id"         "$(code -b /tmp/hb.jar $O/chats/$TC/messages)" "404"

echo "== pin and archive"
put /tmp/hb.jar $O/chats/$G/state '{"pinned":true}' >/dev/null
ok "a pinned chat comes first"          "$(curl -s -b /tmp/hb.jar $O/chats | j "d[0]['id']")" "$G"
put /tmp/hb.jar $O/chats/$G/state '{"archived":true}' >/dev/null
ok "archived leaves the list"           "$(curl -s -b /tmp/hb.jar $O/chats | j "len([c for c in d if c['id']=='$G'])")" "0"
ok "and unpins"                         "$(curl -s -b /tmp/hb.jar "$O/chats?filter=archived" | j "str([c['pinned'] for c in d if c['id']=='$G'][0])")" "False"
say /tmp/hc.jar $O/chats/$G/messages "anyone?" >/dev/null
ok "something new brings it back"       "$(curl -s -b /tmp/hb.jar $O/chats | j "len([c for c in d if c['id']=='$G'])")" "1"

echo "== a message can be only files"
printf 'hello' > /tmp/chat-note.txt
TK=$(post /tmp/hb.jar $O/chats/$DM/attachments '{"filename":"note.txt","content_type":"text/plain"}')
FID=$(echo "$TK" | j "d['attachment']['id']")
curl -s -o /dev/null -X PUT -H 'Content-Type: text/plain' --data-binary @/tmp/chat-note.txt "$(echo "$TK" | j "d['upload_url']")"
curl -s -o /dev/null -b /tmp/hb.jar -H 'Content-Type: application/json' -X POST $O/attachments/$FID/confirm -d '{}'
ok "nothing at all is still refused"    "$(code -b /tmp/hb.jar -H 'Content-Type: application/json' -X POST $O/chats/$DM/messages -d '{"body":""}')" "422"
ok "nor a file that isn't yours to send" "$(code -b /tmp/hc.jar -H 'Content-Type: application/json' -X POST $O/chats/$DM/messages -d "{\"body\":\"\",\"attachment_ids\":[\"$FID\"]}")" "422"
F=$(post /tmp/hb.jar $O/chats/$DM/messages "{\"body\":\"\",\"attachment_ids\":[\"$FID\"]}")
ok "a file with no words is sent"       "$(echo "$F" | j "(d['body'], len(d['attachments']))")" "('', 1)"
ok "and the preview counts it"          "$(curl -s -b /tmp/hc.jar $O/chats | j "[(c['last_message']['body'], c['last_message']['attachments']) for c in d if c['id']=='$DM'][0]")" "('', 1)"
ok "editing it down to nothing: 422"    "$(code -b /tmp/hb.jar -H 'Content-Type: application/json' -X PATCH $O/comments/$(echo "$F" | j "d['id']") -d '{"body":""}')" "422"

echo "== saved messages"
ME=$(post /tmp/hb.jar $O/chats/direct "{\"user_id\":\"$BUID\"}" | j "d['id']")
ok "a DM with yourself"                 "$(curl -s -b /tmp/hb.jar $O/chats/$ME | j "d['title']")" "Saved messages"
say /tmp/hb.jar $O/chats/$ME/messages "note to self" >/dev/null
ok "found by the name it's shown under" "$(curl -s -b /tmp/hb.jar "$O/chats?q=saved" | j "[c['id'] for c in d]")" "['$ME']"

echo "== presence"
ok "everyone in the org is listed"      "$(curl -s -b /tmp/hb.jar $O/presence | j "len(d)")" "3"
ok "nobody here has a socket open"      "$(curl -s -b /tmp/hb.jar $O/presence | j "sum(1 for p in d if p['online'])")" "0"
ok "a stranger can't ask"               "$(code -b /tmp/hb.jar $B/api/organisations/$(python3 -c 'import uuid;print(uuid.uuid4())')/presence)" "404"

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
