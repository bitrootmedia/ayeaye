#!/usr/bin/env bash
#
# Phase 2 end-to-end: teams, project groups, projects and the access model,
# driven over HTTP against a running stack.
#
#   docker compose up -d && ./scripts/e2e-projects.sh
#
# The point of this file is the SQL. `tests/test_access_matrix.py` proves the
# *rule* (`effective_level`) exhaustively and cannot touch the statement that
# implements it — `project_level_expression`. The two are separate
# implementations of most-permissive-wins, and this is what proves they agree:
# same grants, same answer, through Postgres.
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

# owner=alice(org owner) admin=bob designer=carol outsider=dave
A=a$S@example.com; BB=b$S@example.com; C=c$S@example.com; D=d$S@example.com
signup /tmp/pa.jar $A; signup /tmp/pb.jar $BB; signup /tmp/pc.jar $C; signup /tmp/pd.jar $D

OID=$(post /tmp/pa.jar $B/api/organisations "{\"name\":\"Ship $S\"}" | j "d['id']")
join(){ # $1=jar $2=email $3=role
  T=$(post /tmp/pa.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"$3\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/pb.jar $BB admin
join /tmp/pc.jar $C member
join /tmp/pd.jar $D member

echo "== rule 1: private until shared"
P=$(post /tmp/pc.jar $B/api/organisations/$OID/projects '{"name":"Carol only"}')
PID=$(echo "$P" | j "d['id']")
ok "creator owns it"            "$(echo "$P" | j "d['access']")" "owner"
ok "creator sees it listed"     "$(curl -s -b /tmp/pc.jar $B/api/organisations/$OID/projects | j "sum(1 for p in d if p['id']=='$PID')")" "1"
ok "another member: 404"        "$(code -b /tmp/pd.jar $B/api/organisations/$OID/projects/$PID)" "404"
ok "and not in their list"      "$(curl -s -b /tmp/pd.jar $B/api/organisations/$OID/projects | j "sum(1 for p in d if p['id']=='$PID')")" "0"
ok "org admin sees it"          "$(curl -s -b /tmp/pb.jar $B/api/organisations/$OID/projects/$PID | j "d['access']")" "owner"
ok "org owner sees it"          "$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/projects/$PID | j "d['access']")" "owner"

echo "== direct grants"
DUID=$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$D'][0]")
G=$(post /tmp/pc.jar $B/api/organisations/$OID/projects/$PID/access "{\"user_id\":\"$DUID\",\"level\":\"read\"}")
GID=$(echo "$G" | j "d['id']")
ok "read grant lands"           "$(curl -s -b /tmp/pd.jar $B/api/organisations/$OID/projects/$PID | j "d['access']")" "read"
ok "reader cannot edit"         "$(code -b /tmp/pd.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/projects/$PID -d '{"name":"Mine"}')" "403"
ok "reader cannot share"        "$(code -b /tmp/pd.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/projects/$PID/access -d '{"user_id":"'$DUID'","level":"read"}')" "403"
ok "upgrade to write"           "$(patch /tmp/pc.jar $B/api/organisations/$OID/projects/$PID/access/$GID '{"level":"write"}' | j "d['level']")" "write"
ok "writer can edit"            "$(patch /tmp/pd.jar $B/api/organisations/$OID/projects/$PID '{"description":"hello"}' | j "d['description']")" "hello"
ok "writer still cannot share"  "$(code -b /tmp/pd.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/projects/$PID/access -d '{"user_id":"'$DUID'","level":"read"}')" "403"
ok "writer cannot archive"      "$(code -b /tmp/pd.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/projects/$PID -d '{"archived":true}')" "403"
ok "writer cannot delete"       "$(code -b /tmp/pd.jar -X DELETE $B/api/organisations/$OID/projects/$PID)" "403"
ok "duplicate grant -> 409"     "$(code -b /tmp/pc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/projects/$PID/access -d '{"user_id":"'$DUID'","level":"read"}')" "409"
ok "granting the owner -> 409"  "$(code -b /tmp/pc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/projects/$PID/access -d '{"user_id":"'$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$C'][0]")'","level":"read"}')" "409"

echo "== team grants"
TEAM=$(post /tmp/pa.jar $B/api/organisations/$OID/teams "{\"name\":\"Design $S\"}")
TID=$(echo "$TEAM" | j "d['id']")
ok "member can list teams"      "$(code -b /tmp/pc.jar $B/api/organisations/$OID/teams)" "200"
ok "member cannot create one"   "$(code -b /tmp/pc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/teams -d '{"name":"Nope"}')" "403"
CUID=$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$C'][0]")
BUID=$(curl -s -b /tmp/pa.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$BB'][0]")
curl -s -o /dev/null -b /tmp/pa.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/teams/$TID/members -d "{\"user_id\":\"$DUID\"}"
ok "team membership alone: nothing extra" "$(curl -s -b /tmp/pd.jar $B/api/organisations/$OID/projects/$PID | j "d['access']")" "write"

# A second project, shared only with the team.
P2=$(post /tmp/pc.jar $B/api/organisations/$OID/projects '{"name":"Team only"}')
P2ID=$(echo "$P2" | j "d['id']")
ok "outsider to project 2: 404" "$(code -b /tmp/pd.jar $B/api/organisations/$OID/projects/$P2ID)" "404"
post /tmp/pc.jar $B/api/organisations/$OID/projects/$P2ID/access "{\"team_id\":\"$TID\",\"level\":\"read\"}" >/dev/null
ok "team grant reaches member"  "$(curl -s -b /tmp/pd.jar $B/api/organisations/$OID/projects/$P2ID | j "d['access']")" "read"
ok "and it lists"               "$(curl -s -b /tmp/pd.jar $B/api/organisations/$OID/projects | j "sum(1 for p in d if p['id']=='$P2ID')")" "1"
curl -s -o /dev/null -b /tmp/pa.jar -X DELETE $B/api/organisations/$OID/teams/$TID/members/$DUID
ok "leaving the team removes it" "$(code -b /tmp/pd.jar $B/api/organisations/$OID/projects/$P2ID)" "404"

echo "== rule 2: most-permissive-wins (the SQL, against the matrix)"
curl -s -o /dev/null -b /tmp/pa.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/teams/$TID/members -d "{\"user_id\":\"$DUID\"}"
patch /tmp/pc.jar $B/api/organisations/$OID/projects/$P2ID/access/$(curl -s -b /tmp/pc.jar $B/api/organisations/$OID/projects/$P2ID/access | j "[g['id'] for g in d['grants'] if g['team']][0]") '{"level":"write"}' >/dev/null
post /tmp/pc.jar $B/api/organisations/$OID/projects/$P2ID/access "{\"user_id\":\"$DUID\",\"level\":\"read\"}" >/dev/null
# Direct read + team write. Rule 2 says the weaker direct grant cannot reduce it.
ok "weak direct + strong team -> write" "$(curl -s -b /tmp/pd.jar $B/api/organisations/$OID/projects/$P2ID | j "d['access']")" "write"

echo "== who can see it, stated in full"
ACC=$(curl -s -b /tmp/pc.jar $B/api/organisations/$OID/projects/$P2ID/access)
ok "owner is named"             "$(echo "$ACC" | j "d['owner']['email']")" "$C"
ok "admins are listed too"      "$(echo "$ACC" | j "sorted(a['email'] for a in d['organisation_admins']) == sorted(['$A','$BB'])")" "True"
ok "grants are listed"          "$(echo "$ACC" | j "len(d['grants'])")" "2"
ok "owner may manage"           "$(echo "$ACC" | j "str(d['can_manage'])")" "True"
ok "a reader may not"           "$(curl -s -b /tmp/pd.jar $B/api/organisations/$OID/projects/$P2ID/access | j "str(d['can_manage'])")" "False"

echo "== groups are labels, not access"
GRP=$(post /tmp/pa.jar $B/api/organisations/$OID/project-groups "{\"name\":\"Q3 $S\"}")
GRPID=$(echo "$GRP" | j "d['id']")
patch /tmp/pc.jar $B/api/organisations/$OID/projects/$PID "{\"project_group_id\":\"$GRPID\"}" >/dev/null
ok "project files under it"     "$(curl -s -b /tmp/pc.jar $B/api/organisations/$OID/projects/$PID | j "d['project_group_name']")" "Q3 $S"
# Someone with no grant still can't see it just because they can see the group.
ok "grouping grants nothing"    "$(code -b /tmp/pb.jar $B/api/organisations/$OID/project-groups)" "200"
curl -s -o /dev/null -b /tmp/pa.jar -X DELETE $B/api/organisations/$OID/project-groups/$GRPID
ok "deleting the folder keeps the work" "$(curl -s -b /tmp/pc.jar $B/api/organisations/$OID/projects/$PID | j "str(d['project_group_id'])")" "None"

echo "== archive and ownership"
ok "owner archives"             "$(patch /tmp/pc.jar $B/api/organisations/$OID/projects/$PID '{"archived":true}' | j "str(d['archived'])")" "True"
ok "archived drops off the list" "$(curl -s -b /tmp/pc.jar $B/api/organisations/$OID/projects | j "sum(1 for p in d if p['id']=='$PID')")" "0"
ok "but a direct link still works" "$(code -b /tmp/pc.jar $B/api/organisations/$OID/projects/$PID)" "200"
ok "include_archived brings it back" "$(curl -s -b /tmp/pc.jar "$B/api/organisations/$OID/projects?include_archived=true" | j "sum(1 for p in d if p['id']=='$PID')")" "1"
patch /tmp/pc.jar $B/api/organisations/$OID/projects/$PID '{"archived":false}' >/dev/null
ok "hand over to dave"          "$(code -b /tmp/pc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/projects/$PID/owner -d "{\"owner_user_id\":\"$DUID\"}")" "204"
ok "dave now owns it"           "$(curl -s -b /tmp/pd.jar $B/api/organisations/$OID/projects/$PID | j "d['access']")" "owner"
# Carol's only route in WAS ownership. Handing it over costs her the project,
# which is exactly why the endpoint returns no body — see the route docstring.
ok "carol loses access entirely" "$(code -b /tmp/pc.jar $B/api/organisations/$OID/projects/$PID)" "404"
ok "cannot hand to an outsider" "$(code -b /tmp/pd.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/projects/$PID/owner -d '{"owner_user_id":"'$(python3 -c "import uuid;print(uuid.uuid4())")'"}')" "404"

echo "== org admins can do anything"
ok "admin archives someone else's" "$(patch /tmp/pb.jar $B/api/organisations/$OID/projects/$PID '{"archived":true}' | j "str(d['archived'])")" "True"
ok "admin revokes a grant"      "$(code -b /tmp/pb.jar -X DELETE $B/api/organisations/$OID/projects/$P2ID/access/$(curl -s -b /tmp/pb.jar $B/api/organisations/$OID/projects/$P2ID/access | j "d['grants'][0]['id']"))" "204"
ok "admin deletes the project"  "$(code -b /tmp/pb.jar -X DELETE $B/api/organisations/$OID/projects/$PID)" "204"

echo "== cross-organisation isolation"
OTHER=$(post /tmp/pd.jar $B/api/organisations "{\"name\":\"Other $S\"}" | j "d['id']")
ok "project id from another org: 404" "$(code -b /tmp/pd.jar $B/api/organisations/$OTHER/projects/$P2ID)" "404"
ok "non-member on that org: 404"      "$(code -b /tmp/pc.jar $B/api/organisations/$OTHER/projects)" "404"

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
