#!/usr/bin/env bash
#
# Triage end-to-end: the queue of tasks nobody has been asked to act on.
#
#   docker compose up -d && ./scripts/e2e-triage.sh
#
# `action_required_unset` is one more filter on `access.visible_tasks_stmt`,
# so what actually needs proving is that it composes with the access
# expression rather than replacing it: the queue is *your* unassigned work,
# not the organisation's. A plain member must not learn what the owner has
# lying around unassigned in loose tasks they have no route into.
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
j(){ python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
post(){ curl -s -b "$1" -H 'Content-Type: application/json' -X POST "$2" -d "$3"; }
patch(){ curl -s -b "$1" -H 'Content-Type: application/json' -X PATCH "$2" -d "$3"; }

# alice owns the organisation, bob is a plain member.
A=tri-a$S@example.com; BB=tri-b$S@example.com
signup /tmp/tri-a.jar $A; signup /tmp/tri-b.jar $BB

OID=$(post /tmp/tri-a.jar $B/api/organisations "{\"name\":\"Triage $S\"}" | j "d['id']")
T=$(post /tmp/tri-a.jar $B/api/organisations/$OID/invites "{\"email\":\"$BB\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/tri-b.jar -X POST $B/api/invites/$T/accept
BUID=$(curl -s -b /tmp/tri-a.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$BB'][0]")

mk(){ post /tmp/tri-a.jar $B/api/organisations/$OID/tasks "{\"title\":\"$1\"}" | j "d['id']"; }
T1=$(mk "Unassigned one"); T2=$(mk "Unassigned two")
T3=$(mk "Has an assignee"); T4=$(mk "Closed and unassigned")
patch /tmp/tri-a.jar $B/api/organisations/$OID/tasks/$T3 "{\"action_required_user_id\":\"$BUID\"}" >/dev/null
post /tmp/tri-a.jar $B/api/organisations/$OID/tasks/$T4/closed '{"closed":true}' >/dev/null

titles(){ curl -s -b "$1" "$2" | j "','.join(sorted(t['title'] for t in d))"; }

echo "the queue itself"
ok "only unassigned, open tasks" \
  "$(titles /tmp/tri-a.jar "$B/api/organisations/$OID/tasks?action_required_unset=true")" \
  "Unassigned one,Unassigned two"
ok "without the flag, every open task comes back" \
  "$(titles /tmp/tri-a.jar "$B/api/organisations/$OID/tasks")" \
  "Has an assignee,Unassigned one,Unassigned two"
# Closed is a separate axis, so the two filters have to compose rather than
# one implying the other.
ok "include_closed widens it, still excluding the assigned one" \
  "$(titles /tmp/tri-a.jar "$B/api/organisations/$OID/tasks?action_required_unset=true&include_closed=true")" \
  "Closed and unassigned,Unassigned one,Unassigned two"
ok "X-Total-Count counts the queue, not the whole list" \
  "$(curl -s -b /tmp/tri-a.jar -D - -o /dev/null "$B/api/organisations/$OID/tasks?action_required_unset=true&limit=1" | tr -d '\r' | awk -F': ' '/^[Xx]-[Tt]otal-[Cc]ount/{print $2}')" \
  "2"

echo "assigning is what empties it"
patch /tmp/tri-a.jar $B/api/organisations/$OID/tasks/$T1 "{\"action_required_user_id\":\"$BUID\"}" >/dev/null
ok "an assigned task drops straight out" \
  "$(titles /tmp/tri-a.jar "$B/api/organisations/$OID/tasks?action_required_unset=true")" \
  "Unassigned two"
# Being action-required is one of the six routes into a task, so this is also
# the moment bob can see it at all.
ok "and it never lands in the assignee's own queue" \
  "$(titles /tmp/tri-b.jar "$B/api/organisations/$OID/tasks?action_required_unset=true")" \
  ""

echo "the access model still decides"
ok "a plain member's queue holds none of the owner's loose tasks" \
  "$(curl -s -b /tmp/tri-b.jar "$B/api/organisations/$OID/tasks?action_required_unset=true" | j "len(d)")" \
  "0"
# Shared explicitly, and only then does it queue for him.
post /tmp/tri-a.jar $B/api/organisations/$OID/tasks/$T2/access "{\"user_id\":\"$BUID\",\"level\":\"read\"}" >/dev/null
ok "a task shared with him does" \
  "$(titles /tmp/tri-b.jar "$B/api/organisations/$OID/tasks?action_required_unset=true")" \
  "Unassigned two"

echo "  $pass passed, $fail failed"
[ $fail -eq 0 ]
