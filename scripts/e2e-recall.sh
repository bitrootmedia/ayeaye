#!/usr/bin/env bash
#
# Facts and recall: the knowledge base as the team's shared memory.
#
#   docker compose up -d && ./scripts/e2e-recall.sh
#
# Needs the dev stack's embeddings (compose.override.yml turns the bundled
# Ollama on in every checkout). Embedding on a CPU takes seconds per chunk, so
# this suite is slower than its neighbours — most of its time is the sweep.
#
# What it proves, and why these:
#
#   * a fact is its book's — readers read, writers write, strangers get 404;
#   * recall finds by meaning, not just by text: the paraphrase checks share
#     no word with what they find, so a pass cannot be the trigram half;
#   * **access is in the statement, on the meaning half too.** A member with
#     no route to the book recalls nothing; revoking a grant removes the fact
#     from recall on the next question with no re-index — the whole argument
#     for vectors in Postgres rather than beside it;
#   * a private article and somebody else's loose task stay invisible by
#     meaning exactly as they are by text;
#   * superseding takes a fact out of recall without deleting it;
#   * tags narrow, and one vocabulary spans tasks, articles and facts;
#   * MCP `remember`/`recall` act as the token's person, attributed "via".
#
# ALICE  organisation owner; owns the book
# CAROL  a member, granted read (later write) on the book
# DAVE   a member with no route to anything
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
# A JSON body from python, never from escaped quotes — see e2e-mcp.sh's `rpc`.
body(){ python3 -c "import json,sys; print(json.dumps(json.loads(sys.argv[1])))" "$1"; }
q(){ python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))" "$1"; }
# Retried while `semantic` is false. A question that times out behind the
# dev stack's own backfill — tens of thousands of tasks from every other
# suite, embedded on a CPU — falls back to text, which is the product doing
# the right thing and not what any assertion here is about.
recall(){ # $1 jar  $2 query  [$3 extra query string]
  for _ in 1 2 3; do
    OUT=$(curl -s -b "$1" "$B/api/organisations/$OID/kb/recall?q=$(q "$2")${3:-}")
    [ "$(echo "$OUT" | j "d.get('semantic')")" = "True" ] && break
  done
  echo "$OUT"; }
# Where in the results an id sits, 1-based; 0 if absent.
rank_of(){ python3 -c "
import json,sys
d=json.load(sys.stdin); ids=[i['id'] for i in d['items']]
print(ids.index(sys.argv[1])+1 if sys.argv[1] in ids else 0)" "$1"; }
matched_of(){ python3 -c "
import json,sys
d=json.load(sys.stdin)
print(next((i['matched'] for i in d['items'] if i['id']==sys.argv[1]), 'absent'))" "$1"; }

# Make every article and task in this organisation look settled, then index
# this organisation until nothing in it is stale. Reaching into the stack
# rather than waiting out `SETTLE` — the same move e2e-reminders.sh makes for
# its clock — and indexing *this organisation* rather than running the sweep,
# because on a dev database the scheduled sweep is busy backfilling every
# other suite's tasks and holds its lock while it does.
settle(){
  docker compose exec -T postgres psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-app}" -q -c "
    UPDATE tasks SET updated_at = now() - interval '5 minutes' WHERE organisation_id = '$OID';
    UPDATE article_revisions r SET updated_at = now() - interval '5 minutes'
      FROM articles a JOIN books b ON b.id = a.book_id
      WHERE r.article_id = a.id AND b.organisation_id = '$OID';" >/dev/null
  for _ in 1 2 3; do
    LEFT=$(docker compose exec -T -e PYTHONPATH=/app/src api uv run --no-sync python -c "
import asyncio, uuid
from app.db import SessionLocal
from app.services import embeddings as e
async def main():
    org = uuid.UUID('$OID')
    async with SessionLocal() as db:
        while sources := await e.stale_sources(db, organisation_id=org):
            await e.index(db, sources)
        print(len(await e.stale_sources(db, organisation_id=org)))
asyncio.run(main())" 2>&1 | tail -1)
    [ "$LEFT" = "0" ] && return
    sleep 2
  done
  echo "  (settle gave up with $LEFT stale)"
}

A=a$S@example.com; C=c$S@example.com; D=d$S@example.com
signup /tmp/rca.jar $A; signup /tmp/rcc.jar $C; signup /tmp/rcd.jar $D
OID=$(post /tmp/rca.jar $B/api/organisations "{\"name\":\"Recall $S\"}" | j "d['id']")
join(){ T=$(post /tmp/rca.jar $B/api/organisations/$OID/invites "{\"email\":\"$2\",\"role\":\"member\"}" | j "d['invite_url'].rsplit('/',1)[1]")
  curl -s -o /dev/null -b "$1" -X POST $B/api/invites/$T/accept; }
join /tmp/rcc.jar $C
join /tmp/rcd.jar $D
CUID=$(curl -s -b /tmp/rca.jar $B/api/organisations/$OID/members | j "[m['user_id'] for m in d if m['email']=='$C'][0]")

BOOKID=$(post /tmp/rca.jar $B/api/organisations/$OID/kb/books '{"name":"Gotchas"}' | j "d['id']")
FACTS=$B/api/organisations/$OID/kb/books/$BOOKID/facts

echo "== a fact is its book's =="
F1=$(post /tmp/rca.jar $FACTS "$(body '{"body":"Passbolt on passbolt2: after certbot renews the TLS certificate, nginx must be reloaded or it keeps serving the expired one. Found 2026-10-20.","tags":["app:passbolt","type:gotcha","APP:passbolt"]}')")
F1ID=$(echo "$F1" | j "d['id']")
ok "written, no draft step"         "$(echo "$F1" | j "d['superseded_at']")" "None"
ok "tags deduplicated, case-folded" "$(echo "$F1" | j "sorted(t['name'] for t in d['tags'])")" "['app:passbolt', 'type:gotcha']"
ok "attributed to a person"         "$(echo "$F1" | j "d['written_by']['email']")" "$A"
ok "a stranger: 404"                "$(code -b /tmp/rcc.jar $B/api/organisations/$OID/kb/facts/$F1ID)" "404"
ok "nor the list"                   "$(code -b /tmp/rcc.jar $FACTS)" "404"
ok "empty body: 422"                "$(code -b /tmp/rca.jar -H 'Content-Type: application/json' -X POST $FACTS -d '{"body":"   "}')" "422"
LONG=$(python3 -c "import json; print(json.dumps({'body':'x'*4001}))")
ok "too long: 422, not truncated"   "$(code -b /tmp/rca.jar -H 'Content-Type: application/json' -X POST $FACTS -d "$LONG")" "422"

GRANT=$(post /tmp/rca.jar $B/api/organisations/$OID/kb/books/$BOOKID/access "{\"user_id\":\"$CUID\",\"level\":\"read\"}" | j "d['id']")
ok "read grant: reader sees it"     "$(curl -s -b /tmp/rcc.jar $B/api/organisations/$OID/kb/facts/$F1ID | j "d['can_edit']")" "False"
ok "reader can't write one"         "$(code -b /tmp/rcc.jar -H 'Content-Type: application/json' -X POST $FACTS -d '{"body":"mine"}')" "403"
ok "reader can't edit"              "$(code -b /tmp/rcc.jar -H 'Content-Type: application/json' -X PATCH $B/api/organisations/$OID/kb/facts/$F1ID -d '{"body":"edited"}')" "403"
ok "reader can't supersede"         "$(code -b /tmp/rcc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/kb/facts/$F1ID/supersede -d '{}')" "403"
ok "reader can't delete"            "$(code -b /tmp/rcc.jar -X DELETE $B/api/organisations/$OID/kb/facts/$F1ID)" "403"

F2ID=$(post /tmp/rca.jar $FACTS "$(body '{"body":"Leadflow: the celery workers stop consuming after Redis restarts because the broker connection is never retried. Restart the worker containers after any Redis maintenance.","tags":["app:leadflow","type:gotcha"]}')" | j "d['id']")
F3ID=$(post /tmp/rca.jar $FACTS "$(body '{"body":"Decision 2026-09: invoices are generated on the first working day of the month, not the first calendar day, so finance never receives them on a weekend.","tags":["domain:billing","type:decision"]}')" | j "d['id']")

echo "== an article, a private draft and a loose task =="
ARTID=$(post /tmp/rca.jar $B/api/organisations/$OID/kb/books/$BOOKID/articles '{"title":"Restoring the database from backup"}' | j "d['id']")
REV=$(post /tmp/rca.jar $B/api/organisations/$OID/kb/articles/$ARTID/edit-session '{}' | j "d['id']")
patch /tmp/rca.jar $B/api/organisations/$OID/kb/revisions/$REV "$(body '{"title":"Restoring the database from backup","body":"<p>Take the latest pg_dumpall from the bucket, stop the API, and pipe it into psql against an empty cluster. SuperTokens lives in its own database, so a plain pg_dump restores tasks but nobody can log in.</p>"}')" >/dev/null
patch /tmp/rca.jar $B/api/organisations/$OID/kb/articles/$ARTID/private '{"is_private": false}' >/dev/null
ok "tag an article"                 "$(post /tmp/rca.jar $B/api/organisations/$OID/kb/articles/$ARTID/tags '{"name":"domain:database"}' | j "[t['name'] for t in d]")" "['domain:database']"
ok "reader can't tag it"            "$(code -b /tmp/rcc.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/kb/articles/$ARTID/tags -d '{"name":"x"}')" "403"

DRAFTID=$(post /tmp/rca.jar $B/api/organisations/$OID/kb/books/$BOOKID/articles '{"title":"Salary bands for next year"}' | j "d['id']")
DREV=$(post /tmp/rca.jar $B/api/organisations/$OID/kb/articles/$DRAFTID/edit-session '{}' | j "d['id']")
patch /tmp/rca.jar $B/api/organisations/$OID/kb/revisions/$DREV "$(body '{"title":"Salary bands for next year","body":"<p>How much each engineer will be paid next year, by level.</p>"}')" >/dev/null

EMPTYID=$(post /tmp/rca.jar $B/api/organisations/$OID/kb/books/$BOOKID/articles '{}' | j "d['id']")

TASKID=$(post /tmp/rca.jar $B/api/organisations/$OID/tasks "$(body '{"title":"Incident: helm droplet ran out of disk","description":"Docker images accumulated until the root volume filled and Postgres stopped accepting writes. Fixed by pruning images and adding a weekly prune timer."}')" | j "d['id']")

echo "== recall by text, before anything is embedded =="
ok "an exact word finds the fact"   "$(recall /tmp/rca.jar "certbot" | rank_of $F1ID)" "1"

echo "== the sweep =="
settle
ROWS=$(docker compose exec -T postgres psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-app}" -tA -c "SELECT count(*) FROM embeddings WHERE organisation_id = '$OID'")
ok "facts, articles and tasks embedded" "$([ "${ROWS:-0}" -ge 6 ] && echo yes || echo "no ($ROWS)")" "yes"
ok "a private draft is embedded too — access decides at read time" "$(docker compose exec -T postgres psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-app}" -tA -c "SELECT count(*) FROM embeddings WHERE article_id = '$DRAFTID'")" "1"
ok "an empty article never is"      "$(docker compose exec -T postgres psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-app}" -tA -c "SELECT count(*) FROM embeddings WHERE article_id = '$EMPTYID'")" "0"
settle
ROWS2=$(docker compose exec -T postgres psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-app}" -tA -c "SELECT count(*) FROM embeddings WHERE organisation_id = '$OID'")
ok "a second sweep embeds nothing new" "$ROWS2" "$ROWS"

echo "== recall by meaning: no shared words =="
R=$(recall /tmp/rca.jar "background job queue stopped processing after the cache server rebooted")
ok "a paraphrase finds the gotcha"  "$(echo "$R" | rank_of $F2ID)" "1"
# The assertion that a pass can't be the trigram half: not one word of the
# question is in the fact, and `matched` says which search found it.
ok "by meaning alone"               "$(echo "$R" | matched_of $F2ID)" "meaning"
ok "semantic half ran"              "$(echo "$R" | j "d['semantic']")" "True"
R=$(recall /tmp/rca.jar "web server still shows an old expired certificate after renewal")
ok "both halves agree, it leads"    "$(echo "$R" | rank_of $F1ID)" "1"
ok "an article by meaning"          "$(recall /tmp/rca.jar "how to bring back our data after losing the server" | rank_of $ARTID)" "1"
ok "a task by meaning"              "$(recall /tmp/rca.jar "machine had no storage space left" | rank_of $TASKID)" "1"
ok "nothing related: nothing back"  "$(recall /tmp/rca.jar "recipe for sourdough bread with rye flour" | j "len(d['items'])")" "0"

echo "== access is in the statement, both halves =="
ok "reader recalls the fact"        "$(recall /tmp/rcc.jar "background job queue stopped processing after the cache server rebooted" | rank_of $F2ID)" "1"
ok "reader: not the private draft"  "$(recall /tmp/rcc.jar "what each engineer earns" | rank_of $DRAFTID)" "0"
ok "owner: the private draft"       "$(recall /tmp/rca.jar "what each engineer earns" | rank_of $DRAFTID)" "1"
ok "reader: not Alice's loose task" "$(recall /tmp/rcc.jar "machine had no storage space left" | rank_of $TASKID)" "0"
ok "no route: recalls nothing"      "$(recall /tmp/rcd.jar "background job queue stopped processing after the cache server rebooted" | j "len(d['items'])")" "0"
curl -s -o /dev/null -b /tmp/rca.jar -X DELETE $B/api/organisations/$OID/kb/books/$BOOKID/access/$GRANT
ok "revoked: gone on the next question, no re-index" "$(recall /tmp/rcc.jar "background job queue stopped processing after the cache server rebooted" | rank_of $F2ID)" "0"

echo "== tags narrow, one vocabulary =="
ok "tag filter keeps the match"     "$(recall /tmp/rca.jar "celery workers" "&tags=app:leadflow" | j "[i['id'] for i in d['items']]")" "['$F2ID']"
ok "tags AND, not OR"               "$(recall /tmp/rca.jar "celery workers" "&tags=app:leadflow&tags=app:passbolt" | j "len(d['items'])")" "0"
ok "an unknown tag says so"         "$(recall /tmp/rca.jar "gotcha" "&tags=app:nope" | j "d['unknown_tags']")" "['app:nope']"
ok "kinds narrow"                   "$(recall /tmp/rca.jar "database backup restore" "&kinds=fact" | j "set(i['kind'] for i in d['items']) <= {'fact'}")" "True"
ok "vocabulary counts facts and articles" "$(curl -s -b /tmp/rca.jar $B/api/organisations/$OID/tags | j "{t['name']: t['task_count'] for t in d}['type:gotcha']")" "2"
ok "⌘K finds a fact"                "$(curl -s -b /tmp/rca.jar "$B/api/organisations/$OID/search?q=certbot" | j "[h['kind'] for h in d['hits']]")" "['fact']"

echo "== superseding =="
F4ID=$(post /tmp/rca.jar $FACTS "$(body '{"body":"Passbolt on passbolt2: certbot now runs a deploy hook that reloads nginx, so renewals no longer need a manual reload.","tags":["app:passbolt"]}')" | j "d['id']")
ok "by a fact you can't name: 404"  "$(code -b /tmp/rca.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/kb/facts/$F1ID/supersede -d '{"by_fact_id":"00000000-0000-7000-8000-000000000000"}')" "404"
ok "not by itself"                  "$(code -b /tmp/rca.jar -H 'Content-Type: application/json' -X POST $B/api/organisations/$OID/kb/facts/$F1ID/supersede -d "{\"by_fact_id\":\"$F1ID\"}")" "422"
SUP=$(post /tmp/rca.jar $B/api/organisations/$OID/kb/facts/$F1ID/supersede "{\"by_fact_id\":\"$F4ID\"}")
ok "superseded, pointing on"        "$(echo "$SUP" | j "d['superseded_by_fact_id']")" "$F4ID"
ok "out of recall"                  "$(recall /tmp/rca.jar "certbot" | rank_of $F1ID)" "0"
ok "…unless asked for"              "$(recall /tmp/rca.jar "certbot" "&include_inactive=true" | j "[i['inactive'] for i in d['items'] if i['id']=='$F1ID']")" "[True]"
ok "out of the book's list"         "$(curl -s -b /tmp/rca.jar $FACTS | j "'$F1ID' in [f['id'] for f in d]")" "False"
ok "still there by id"              "$(code -b /tmp/rca.jar $B/api/organisations/$OID/kb/facts/$F1ID)" "200"
ok "restore"                        "$(post /tmp/rca.jar $B/api/organisations/$OID/kb/facts/$F1ID/restore '{}' | j "d['superseded_at']")" "None"
ok "paged, says of what"            "$(curl -s -D - -o /dev/null -b /tmp/rca.jar "$FACTS?limit=1" | grep -i x-total-count | tr -d '\r' | cut -d' ' -f2)" "4"

echo "== deleting: the author or the book's owner =="
post /tmp/rca.jar $B/api/organisations/$OID/kb/books/$BOOKID/access "{\"user_id\":\"$CUID\",\"level\":\"write\"}" >/dev/null
CF=$(post /tmp/rcc.jar $FACTS '{"body":"Carol was here."}' | j "d['id']")
ok "writer can't delete Alice's"    "$(code -b /tmp/rcc.jar -X DELETE $B/api/organisations/$OID/kb/facts/$F3ID)" "403"
ok "writer can edit Alice's"        "$(patch /tmp/rcc.jar $B/api/organisations/$OID/kb/facts/$F3ID "$(body '{"body":"Decision 2026-09: invoices go out on the first working day of the month."}')" | j "d['body'][:13]")" "Decision 2026"
ok "writer deletes their own"       "$(code -b /tmp/rcc.jar -X DELETE $B/api/organisations/$OID/kb/facts/$CF)" "204"
ok "owner deletes anything"         "$(code -b /tmp/rca.jar -X DELETE $B/api/organisations/$OID/kb/facts/$F3ID)" "204"
ok "its chunks go with it"          "$(docker compose exec -T postgres psql -U "${POSTGRES_USER:-app}" -d "${POSTGRES_DB:-app}" -tA -c "SELECT count(*) FROM embeddings WHERE fact_id = '$F3ID'")" "0"

echo "== MCP: remember and recall, as a person =="
TOK=$(post /tmp/rca.jar $B/api/me/tokens '{"name":"Claude","scope":"write"}' | j "d['token']")
READTOK=$(post /tmp/rca.jar $B/api/me/tokens '{"name":"Reader","scope":"read"}' | j "d['token']")
tool(){ python3 -c "import json,sys; print(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':sys.argv[1],'arguments':json.loads(sys.argv[2])}}))" "$2" "$3" > /tmp/rc-mcp.json
  curl -s -X POST $B/mcp -H "Authorization: Bearer $1" -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2025-06-18' \
    --data-binary @/tmp/rc-mcp.json | python3 -c "
import json,sys
d=json.loads(sys.stdin.read()); c=(d.get('result') or {}).get('content') or []
print(c[0].get('text','') if c else json.dumps(d))"; }
ARGS=$(python3 -c 'import json,sys; print(json.dumps({"organisation_id": sys.argv[1], "book_id": sys.argv[2], "body": "Metabase: the nightly sync job times out against the read replica unless statement_timeout is raised to five minutes.", "tags": ["app:metabase", "type:gotcha"]}))' "$OID" "$BOOKID")
REM=$(tool "$TOK" remember "$ARGS")
ok "remember"                       "$(echo "$REM" | cut -c1-12)" "Remembered ["
MFID=$(echo "$REM" | sed -E 's/^Remembered \[([^]]+)\].*/\1/')
ok "attributed via the token"       "$(curl -s -b /tmp/rca.jar $B/api/organisations/$OID/kb/facts/$MFID | j "d['via']")" "Claude"
ok "a read token can't remember"    "$(tool "$READTOK" remember "$ARGS" | grep -c 'read-only')" "1"
# Arguments built into a variable first, never inline: bash 3.2 mis-parses a
# brace inside `$(...)` inside a double-quoted string — see e2e-mcp.sh.
recall_args(){ python3 -c 'import json,sys
a = sys.argv[1:]
d = {"organisation_id": a[0], "query": a[1]}
if len(a) > 2: d["tags"] = a[2:]
print(json.dumps(d))' "$@"; }
RA=$(recall_args "$OID" "statement_timeout")
ok "MCP recall by text"             "$(tool "$READTOK" recall "$RA" | grep -c "$MFID")" "1"
settle
RA=$(recall_args "$OID" "dashboard tool scheduled refresh keeps failing on the replica database")
ok "MCP recall by meaning"          "$(tool "$READTOK" recall "$RA" | head -2 | grep -c "$MFID")" "1"
SUPARGS=$(python3 -c 'import json,sys; print(json.dumps({"organisation_id": sys.argv[1], "fact_id": sys.argv[2]}))' "$OID" "$MFID")
ok "supersede_fact"                 "$(tool "$TOK" supersede_fact "$SUPARGS" | cut -c1-11)" "Superseded "
RA=$(recall_args "$OID" "x" "app:nope")
ok "an unknown tag, said plainly"   "$(tool "$READTOK" recall "$RA" | grep -c 'No tag called')" "1"

echo
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
