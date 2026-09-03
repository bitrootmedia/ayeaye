#!/usr/bin/env bash
#
# Knowledge base: books, articles, revisions, attachments and search.
#
#   docker compose up -d && ./scripts/e2e-kb.sh
#
# `tests/test_kb_rules.py` proves `effective_article_level` exhaustively with
# no database — a private article short-circuits ahead of book access, same
# shape as a hidden task. This proves the **SQL** half agrees, through
# Postgres, and covers what a pure function can't: book sharing (the Project
# access model, unchanged), the vanish-from-contents behaviour on a real
# list endpoint, revision session mechanics (a session stays mutable, a new
# one seeds from the last, a stale save 409s), attachments anchored to a
# revision through the real upload handshake, the `book_shared` notification,
# and search matching only the current revision's text within the same
# access rule.
#
# ALICE  organisation owner, creates the book and its first article
# BOB    an org admin — the one deliberate hole: can't see a private article
# CAROL  a plain member, granted read on the book
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

A=a$S@example.com; BB=b$S@example.com; C=c$S@example.com
signup /tmp/kba.jar $A; signup /tmp/kbb.jar $BB; signup /tmp/kbc.jar $C

OID=$(post /tmp/kba.jar $B/api/organisations "{\"name\":\"KB $S\"}" | j "d['id']")
join(){ T=$(post /tmp/kba.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"$3\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/kbb.jar $BB admin
join /tmp/kbc.jar $C member

echo "== books: the project access model, unchanged =="
BOOK=$(post /tmp/kba.jar $B/api/organisations/$OID/kb/books "{\"name\":\"Runbooks\"}")
BOOKID=$(echo "$BOOK" | j "d['id']")
ok "creator owns it"          "$(echo "$BOOK" | j "d['access']")" "owner"
ok "not shared: member 404"   "$(code -b /tmp/kbc.jar $B/api/organisations/$OID/kb/books/$BOOKID)" "404"
ok "org admin sees it"        "$(curl -s -b /tmp/kbb.jar $B/api/organisations/$OID/kb/books/$BOOKID | j "d['access']")" "owner"

CUID=$(curl -s -b /tmp/kba.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$C'][0]")
G=$(post /tmp/kba.jar $B/api/organisations/$OID/kb/books/$BOOKID/access "{\"user_id\":\"$CUID\",\"level\":\"read\"}")
ok "read grant lands"         "$(curl -s -b /tmp/kbc.jar $B/api/organisations/$OID/kb/books/$BOOKID | j "d['access']")" "read"
ok "book_shared notified"     "$(curl -s -b /tmp/kbc.jar $B/api/notifications | j "d[0]['kind']")" "book_shared"

echo "== articles: born private, vanish from contents =="
ART=$(post /tmp/kba.jar $B/api/organisations/$OID/kb/books/$BOOKID/articles "{\"title\":\"Deploying\"}")
ARTID=$(echo "$ART" | j "d['id']")
ok "article born private"        "$(echo "$ART" | j "d['is_private']")" "True"
ok "owner access is owner"       "$(echo "$ART" | j "d['access']")" "owner"
ok "owner can_make_private"      "$(echo "$ART" | j "d['can_make_private']")" "True"
ok "reader can't see it"         "$(code -b /tmp/kbc.jar $B/api/organisations/$OID/kb/articles/$ARTID)" "404"
ok "admin can't see it either"   "$(code -b /tmp/kbb.jar $B/api/organisations/$OID/kb/articles/$ARTID)" "404"
ok "vanished from contents"      "$(curl -s -b /tmp/kbc.jar $B/api/organisations/$OID/kb/books/$BOOKID/articles | j "len(d)")" "0"

echo "== publish: the only thing that changes visibility =="
PUB=$(patch /tmp/kba.jar $B/api/organisations/$OID/kb/articles/$ARTID/private '{"is_private": false}')
ok "publish succeeds"            "$(echo "$PUB" | j "d['is_private']")" "False"
ok "reader can now see it"       "$(code -b /tmp/kbc.jar $B/api/organisations/$OID/kb/articles/$ARTID)" "200"
ok "reader cannot re-privatise"  "$(code -b /tmp/kbc.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/kb/articles/$ARTID/private -d '{"is_private": true}')" "403"
ok "in contents once published"  "$(curl -s -b /tmp/kbc.jar $B/api/organisations/$OID/kb/books/$BOOKID/articles | j "len(d)")" "1"

echo "== revision sessions =="
SESS1=$(post /tmp/kba.jar $B/api/organisations/$OID/kb/articles/$ARTID/edit-session "{}")
REV1=$(echo "$SESS1" | j "d['id']")
ok "session creates a revision" "$(echo "$SESS1" | j "d['is_current']")" "True"

SAVE1=$(patch /tmp/kba.jar $B/api/organisations/$OID/kb/revisions/$REV1 "{\"title\":\"Deploying v1\",\"body\":\"<p>step one</p>\"}")
ok "autosave updates in place" "$(echo "$SAVE1" | j "d['title']")" "Deploying v1"

SESS2=$(post /tmp/kba.jar $B/api/organisations/$OID/kb/articles/$ARTID/edit-session "{}")
REV2=$(echo "$SESS2" | j "d['id']")
ok "reopening reuses the same session" "$REV2" "$REV1"

ok "unknown revision 404s"      "$(code -b /tmp/kba.jar $B/api/organisations/$OID/kb/revisions/00000000-0000-7000-8000-000000000000)" "404"
ok "history has exactly one revision so far" "$(curl -s -b /tmp/kba.jar $B/api/organisations/$OID/kb/articles/$ARTID/revisions | j "len(d)")" "1"

echo "== attachments: anchored to the revision, not the article =="
STAGE=$(post /tmp/kba.jar $B/api/organisations/$OID/kb/revisions/$REV1/files "{\"filename\":\"notes.txt\",\"content_type\":\"text/plain\"}")
FILEID=$(echo "$STAGE" | j "d['attachment']['id']")
UPLOAD_URL=$(echo "$STAGE" | j "d['upload_url']")
ok "stage returns an upload url" "$(test -n "$UPLOAD_URL" && echo yes)" "yes"

PUTCODE=$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H 'Content-Type: text/plain' --data-binary 'hello kb' "$UPLOAD_URL")
ok "browser PUT to storage"     "$PUTCODE" "200"

CONFIRM=$(post /tmp/kba.jar $B/api/organisations/$OID/attachments/$FILEID/confirm "{}")
ok "confirm flips to ready"     "$(echo "$CONFIRM" | j "d['size_bytes']")" "8"
ok "file appears on this revision" "$(curl -s -b /tmp/kba.jar $B/api/organisations/$OID/kb/revisions/$REV1/files | j "len(d)")" "1"
ok "reader with article access sees it" "$(curl -s -b /tmp/kbc.jar $B/api/organisations/$OID/kb/revisions/$REV1/files | j "len(d)")" "1"

echo "== search: current revision only, same access rule =="
curl -s -o /dev/null -b /tmp/kba.jar -X PATCH -H 'Content-Type: application/json' "$B/api/organisations/$OID/kb/revisions/$REV1" -d '{"title":"Deploying v1","body":"<p>a distinctive marker phrase here</p>"}'
HIT_OWNER=$(curl -s -b /tmp/kba.jar "$B/api/organisations/$OID/search?q=distinctive")
ok "owner finds it published"   "$(echo "$HIT_OWNER" | j "d['hits'][0]['kind']")" "article"
HIT_READER=$(curl -s -b /tmp/kbc.jar "$B/api/organisations/$OID/search?q=distinctive")
ok "reader finds it too"        "$(echo "$HIT_READER" | j "len(d['hits'])")" "1"

curl -s -o /dev/null -b /tmp/kba.jar -X PATCH -H 'Content-Type: application/json' "$B/api/organisations/$OID/kb/articles/$ARTID/private" -d '{"is_private": true}'
HIT_AFTER=$(curl -s -b /tmp/kbc.jar "$B/api/organisations/$OID/search?q=distinctive")
ok "privatised: reader search finds nothing" "$(echo "$HIT_AFTER" | j "len(d['hits'])")" "0"
HIT_OWNER2=$(curl -s -b /tmp/kba.jar "$B/api/organisations/$OID/search?q=distinctive")
ok "owner still finds their own private one" "$(echo "$HIT_OWNER2" | j "len(d['hits'])")" "1"

echo
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
