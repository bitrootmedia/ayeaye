#!/usr/bin/env bash
#
# Task revisions — recovering a title or description somebody saved over.
#
#   docker compose up -d && ./scripts/e2e-task-revisions.sh
#
# The bug this exists for: a description edit used to write no history at
# all, so an overwrite was unrecoverable. Four things worth a dedicated
# suite, none of which a unit test can reach:
#
#   * a row holds the content the save REPLACED, not the new content — so
#     the live task stays the only answer to "what does this say now";
#   * one row per save, however many of the two fields moved, because the
#     Details card saves both in one PATCH;
#   * a save that changes neither records nothing, so the list stays a list
#     of real overwrites;
#   * restoring is `write` and is itself undoable — putting a version back
#     snapshots what it replaced, like any other edit.
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
# Bodies are built by python, never as an inline shell literal: a `{...}`
# containing a comma, nested two quote-levels deep inside a "$(...)"
# capture, is silently torn in two by brace expansion. See the bash gotcha
# in CLAUDE.md's MFA section — it cost an hour there.
body(){ python3 -c "import json,sys; print(json.dumps(dict(a.split('=',1) for a in sys.argv[1:])))" "$@"; }

OWNER=rev-owner$S@example.com; OTHER=rev-other$S@example.com
signup /tmp/revo.jar $OWNER; signup /tmp/revt.jar $OTHER

OID=$(post /tmp/revo.jar $B/api/organisations "{\"name\":\"Revs $S\"}" | j "d['id']")
INV=$(post /tmp/revo.jar $B/api/organisations/$OID/invites "$(body email=$OTHER role=member)")
T=$(echo "$INV" | j "d['invite_url'].rsplit('/',1)[1]")
curl -s -o /dev/null -b /tmp/revt.jar -c /tmp/revt.jar -X POST $B/api/invites/$T/accept
OTHER_ID=$(curl -s -b /tmp/revo.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$OTHER'][0]")

TID=$(post /tmp/revo.jar $B/api/organisations/$OID/tasks "$(body title='Rebuild the windlass' description='<p>The original notes</p>')" | j "d['id']")
REVS=$B/api/organisations/$OID/tasks/$TID/revisions

echo "== a brand-new task has nothing to recover"
ok "no revisions yet" "$(curl -s -b /tmp/revo.jar $REVS | j "len(d)")" "0"

echo "== a save that changes nothing records nothing"
patch /tmp/revo.jar $B/api/organisations/$OID/tasks/$TID "$(body title='Rebuild the windlass' description='<p>The original notes</p>')" >/dev/null
ok "resaving identical content is not an overwrite" "$(curl -s -b /tmp/revo.jar $REVS | j "len(d)")" "0"

echo "== overwriting the description keeps what it replaced"
patch /tmp/revo.jar $B/api/organisations/$OID/tasks/$TID "$(body description='<p>Replaced by someone in a hurry</p>')" >/dev/null
ok "one revision"            "$(curl -s -b /tmp/revo.jar $REVS | j "len(d)")" "1"
ok "it holds the OLD text"   "$(curl -s -b /tmp/revo.jar $REVS | j "d[0]['description']")" "<p>The original notes</p>"
ok "…not the new text"       "$(curl -s -b /tmp/revo.jar $REVS | j "d[0]['description'] == '<p>Replaced by someone in a hurry</p>'")" "False"
ok "attributed to whoever saved over it" "$(curl -s -b /tmp/revo.jar $REVS | j "d[0]['replaced_by']['email']")" "$OWNER"
ok "the live task has the new text" "$(curl -s -b /tmp/revo.jar $B/api/organisations/$OID/tasks/$TID | j "d['description']")" "<p>Replaced by someone in a hurry</p>"

echo "== a description edit now writes history, which it never used to"
ok "description_changed event" "$(curl -s -b /tmp/revo.jar $B/api/organisations/$OID/tasks/$TID/events | j "[e['kind'] for e in d if e['kind']=='description_changed']")" "['description_changed']"

echo "== title and description in one save is ONE revision"
patch /tmp/revo.jar $B/api/organisations/$OID/tasks/$TID "$(body title='Windlass, rebuilt' description='<p>Third version</p>')" >/dev/null
ok "two revisions, not three" "$(curl -s -b /tmp/revo.jar $REVS | j "len(d)")" "2"
ok "newest first"             "$(curl -s -b /tmp/revo.jar $REVS | j "d[0]['title']")" "Rebuild the windlass"
ok "and it carries that save's outgoing description" "$(curl -s -b /tmp/revo.jar $REVS | j "d[0]['description']")" "<p>Replaced by someone in a hurry</p>"

echo "== restoring puts a version back"
RID=$(curl -s -b /tmp/revo.jar $REVS | j "d[1]['id']")
ok "restore returns the task"    "$(post /tmp/revo.jar $REVS/$RID/restore '{}' | j "d['description']")" "<p>The original notes</p>"
ok "the live task is back"       "$(curl -s -b /tmp/revo.jar $B/api/organisations/$OID/tasks/$TID | j "d['description']")" "<p>The original notes</p>"
ok "and its title came with it"  "$(curl -s -b /tmp/revo.jar $B/api/organisations/$OID/tasks/$TID | j "d['title']")" "Rebuild the windlass"
ok "the restore is in the history" "$(curl -s -b /tmp/revo.jar $B/api/organisations/$OID/tasks/$TID/events | j "[e['kind'] for e in d if e['kind']=='restored']")" "['restored']"

echo "== a restore is itself undoable"
ok "it snapshotted what it replaced" "$(curl -s -b /tmp/revo.jar $REVS | j "len(d)")" "3"
ok "…which was the third version"    "$(curl -s -b /tmp/revo.jar $REVS | j "d[0]['description']")" "<p>Third version</p>"

echo "== a revision from another task is not reachable through this one"
OTHER_TASK=$(post /tmp/revo.jar $B/api/organisations/$OID/tasks "$(body title='Something else' description='<p>Private-ish</p>')" | j "d['id']")
patch /tmp/revo.jar $B/api/organisations/$OID/tasks/$OTHER_TASK "$(body description='<p>changed</p>')" >/dev/null
FOREIGN=$(curl -s -b /tmp/revo.jar $B/api/organisations/$OID/tasks/$OTHER_TASK/revisions | j "d[0]['id']")
ok "wrong task's revision id is 404" "$(code -b /tmp/revo.jar -H 'Content-Type: application/json' -X POST $REVS/$FOREIGN/restore -d '{}')" "404"

echo "== reading is read, restoring is write"
post /tmp/revo.jar $B/api/organisations/$OID/tasks/$TID/access "$(body user_id=$OTHER_ID level=read)" >/dev/null
ok "a read-only grantee can read the versions" "$(curl -s -b /tmp/revt.jar $REVS | j "len(d)")" "3"
ok "…and cannot restore one"                   "$(code -b /tmp/revt.jar -H 'Content-Type: application/json' -X POST $REVS/$RID/restore -d '{}')" "403"
curl -s -o /dev/null -b /tmp/revo.jar -X DELETE "$B/api/organisations/$OID/tasks/$TID/access/$(curl -s -b /tmp/revo.jar $B/api/organisations/$OID/tasks/$TID/access | j "d['grants'][0]['id']")"
ok "with no access at all it is 404, not 403"  "$(code -b /tmp/revt.jar $REVS)" "404"

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
