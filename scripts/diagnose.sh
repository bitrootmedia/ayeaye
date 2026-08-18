#!/usr/bin/env bash
#
# What's wrong with this installation.
#
#   ./scripts/diagnose.sh
#
# Written for the moment somebody's site is down and they have no idea why.
# Every check answers a question that has actually caused an outage in this
# stack's history, and each one prints what to do rather than just a verdict.
#
# Read-only: it looks, reports, and changes nothing.
set -uo pipefail
cd "$(dirname "$0")/.."

ok=0; warn=0; bad=0
say()  { printf '  %s\n' "$*"; }
good() { printf '  \033[32m✓\033[0m %s\n' "$*"; ok=$((ok+1)); }
soft() { printf '  \033[33m!\033[0m %s\n' "$*"; warn=$((warn+1)); }
hard() { printf '  \033[31m✗\033[0m %s\n' "$*"; bad=$((bad+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

head_ "Prerequisites"
if command -v docker >/dev/null 2>&1; then
  good "docker $(docker --version | sed 's/Docker version //;s/,.*//')"
else
  hard "docker is not installed — nothing else here will work"
  exit 1
fi
if docker compose version >/dev/null 2>&1; then
  good "compose $(docker compose version --short)"
else
  hard "docker compose v2 is missing (the 'docker-compose' script is not the same thing)"
fi

head_ "Configuration"
if [ ! -f .env ]; then
  hard ".env is missing — run ./scripts/setup.sh"
else
  good ".env exists"
  # The upgrade footgun: a release adds a variable and an older .env aborts
  # every container with one unhelpful line.
  missing=$(comm -13 <(grep -o '^[A-Z_]*' .env | sort -u) <(grep -o '^[A-Z_]*' .env.example | sort -u) | tr '\n' ' ')
  if [ -n "${missing// /}" ]; then
    hard "your .env is missing variables a newer release expects: $missing"
    say  "add them from .env.example"
  else
    good ".env has every variable .env.example does"
  fi

  SITE_URL=$(grep -E '^SITE_URL=' .env | cut -d= -f2-)
  say "SITE_URL is ${SITE_URL:-(unset)}"
  case "$SITE_URL" in
    http://*|https://*) ;;
    *) hard "SITE_URL needs a scheme — Caddy uses it to decide about certificates" ;;
  esac

  # compose.override.yml is committed — that's what makes local dev a plain
  # `git clone` — but Compose auto-loads it whenever it's present, and on a
  # real domain that runs the Vite dev server instead of the built app,
  # publishes Postgres's port to the internet, and turns on the RustFS/pgweb
  # dev consoles. This has actually happened: the symptom isn't a blank page,
  # it's Vite itself refusing the request with "Blocked request. This host
  # (…) is not allowed" — which reads like an app bug and is actually Vite
  # correctly refusing to serve a domain it was never told to trust.
  case "$SITE_URL" in
    http://localhost*) ;;
    *)
      if [ -f compose.override.yml ]; then
        hard "compose.override.yml exists AND SITE_URL is a real domain — the dev stack is what's running"
        say  "rm compose.override.yml && docker compose up -d"
      fi ;;
  esac

  # Which of the bundled containers this deployment actually uses. Everything
  # below has to ask this before treating "postgres isn't running" or
  # "POSTGRES_PASSWORD looks like the example" as a problem — for a managed
  # database or bucket, neither is.
  PROFILES=$(grep -E '^COMPOSE_PROFILES=' .env | cut -d= -f2-)
  case ",$PROFILES," in *,local-db,*) LOCAL_DB=1 ;; *) LOCAL_DB=0 ;; esac
  case ",$PROFILES," in *,local-storage,*) LOCAL_STORAGE=1 ;; *) LOCAL_STORAGE=0 ;; esac
  [ "$LOCAL_DB" = 1 ] && say "database: bundled Postgres" || say "database: managed (DATABASE_URL)"
  [ "$LOCAL_STORAGE" = 1 ] && say "storage: bundled RustFS" || say "storage: managed (S3_ENDPOINT)"

  # Shipping the example values to the internet is the failure this whole
  # script exists to catch early. Only for what's actually load-bearing in
  # THIS deployment: a managed database's own password was never .env's to
  # check, and DATABASE_URL / S3_ENDPOINT cover it either way.
  check_secret() {  # check_secret VAR
    value=$(grep -E "^$1=" .env | cut -d= -f2-)
    case "$value" in
      *dev-only*|*change-me*|"")
        case "$SITE_URL" in
          https://*) hard "$1 is still an example value on a public site" ;;
          *) soft "$1 is an example value (fine on localhost, not on a domain)" ;;
        esac ;;
      *) good "$1 is set to something of your own" ;;
    esac
  }
  [ "$LOCAL_DB" = 1 ] && check_secret POSTGRES_PASSWORD
  [ "$LOCAL_STORAGE" = 1 ] && check_secret RUSTFS_SECRET_KEY
  check_secret S3_SECRET_KEY
  check_secret SUPERTOKENS_API_KEY
  for var in DATABASE_URL SUPERTOKENS_DATABASE_URL S3_ENDPOINT; do
    value=$(grep -E "^$var=" .env | cut -d= -f2-)
    [ -n "$value" ] && good "$var is set" || hard "$var is empty — nothing can reach the database or storage"
  done
fi

head_ "Containers"
if ! docker compose ps --format '{{.Service}}' >/dev/null 2>&1; then
  hard "cannot talk to this project's containers — is the daemon running?"
else
  expected="caddy api worker scheduler web redis supertokens"
  [ "${LOCAL_DB:-1}" = 1 ] && expected="$expected postgres"
  [ "${LOCAL_STORAGE:-1}" = 1 ] && expected="$expected rustfs"
  running=$(docker compose ps --status running --format '{{.Service}}' 2>/dev/null | tr '\n' ' ')
  for service in $expected; do
    case " $running " in
      *" $service "*) good "$service is up" ;;
      *) hard "$service is NOT running — docker compose logs $service" ;;
    esac
  done
  # migrate is a one-shot; exited(0) is success and exited(non-zero) blocks
  # the API from ever starting.
  code=$(docker compose ps -a --format '{{.Service}} {{.ExitCode}}' 2>/dev/null | awk '$1=="migrate"{print $2}' | tail -1)
  case "${code:-}" in
    0)  good "migrate finished cleanly (it is meant to exit)" ;;
    "") soft "migrate has not run yet" ;;
    *)  hard "migrate exited $code — the API will not start. docker compose logs migrate" ;;
  esac
  unhealthy=$(docker compose ps --format '{{.Service}} {{.Health}}' 2>/dev/null | awk '$2=="unhealthy"{print $1}' | tr '\n' ' ')
  [ -n "${unhealthy// /}" ] && hard "unhealthy: $unhealthy" || good "no unhealthy containers"
fi

head_ "Reachability"
probe() {  # $1=label $2=url
  code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 "$2" 2>/dev/null)
  case "$code" in
    000) hard "$1 unreachable ($2)" ;;
    2*|3*) good "$1 → $code" ;;
    *) soft "$1 → $code ($2)" ;;
  esac
}
BASE="${SITE_URL:-http://localhost}"
probe "health probe" "$BASE/health"
probe "the app"      "$BASE/"
if [ "${LOCAL_STORAGE:-1}" = 1 ]; then
  # Storage is the one probe where 403 is the RIGHT answer: S3 refuses an
  # anonymous bucket listing, which proves RustFS itself replied. A 200 here
  # would mean the SPA catch-all swallowed /media/* and every attachment is
  # quietly broken.
  storage=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 "$BASE/media/" 2>/dev/null)
  case "$storage" in
    403|404) good "storage → $storage (S3 is answering)" ;;
    200)     hard "storage → 200, which means the SPA is answering /media/*, not RustFS" ;;
    000)     hard "storage unreachable ($BASE/media/)" ;;
    *)       soft "storage → $storage" ;;
  esac
else
  # Caddy's /media/* rule always points at rustfs:9000 — dead code once
  # storage is managed, not a health signal. Uploads reach the provider
  # directly, at S3_PUBLIC_ENDPOINT, never through SITE_URL at all.
  say "storage is managed — SITE_URL/media/* isn't wired to it; see Storage below"
fi

head_ "Storage"
S3_ENDPOINT_VAL=$(grep -E '^S3_ENDPOINT=' .env 2>/dev/null | cut -d= -f2-)
S3_BUCKET_VAL=$(grep -E '^S3_BUCKET=' .env 2>/dev/null | cut -d= -f2- || echo media)
if ! docker compose ps --format '{{.Service}}' 2>/dev/null | grep -qx api; then
  soft "api isn't running — can't check bucket access from here"
else
  # The exact call the app itself makes at startup (ensure_bucket) and before
  # every upload ticket — same endpoint, same credentials, same signing. If
  # this fails, the browser's presigned PUT was never going to work either,
  # and the error here says which of endpoint/credentials/bucket is wrong
  # instead of a browser console full of an opaque SignatureDoesNotMatch.
  result=$(docker compose exec -T -e PYTHONPATH=/app/src api uv run python -c "
from app.core.config import settings
from app.storage.s3 import internal_client
try:
    internal_client().head_bucket(Bucket=settings.s3_bucket)
    print('OK')
except Exception as e:
    print('FAIL: ' + repr(e))
" 2>&1)
  case "$result" in
    OK) good "bucket '$S3_BUCKET_VAL' reachable at $S3_ENDPOINT_VAL with these credentials" ;;
    *403*|*Forbidden*)
      hard "bucket '$S3_BUCKET_VAL' answered 403 — S3_ACCESS_KEY/S3_SECRET_KEY are wrong, or the bucket policy denies this key"
      say  "$result" ;;
    *404*)
      hard "bucket '$S3_BUCKET_VAL' answered 404 — it doesn't exist at this endpoint, or S3_BUCKET is misspelled"
      say  "$result" ;;
    *EndpointConnectionError*|*"Could not connect"*)
      hard "could not reach $S3_ENDPOINT_VAL from inside the api container"
      say  "check S3_ENDPOINT — a typo, a firewall, or a provider that needs a different port"
      say  "$result" ;;
    *)
      hard "bucket check failed"
      say  "$result" ;;
  esac
fi

if [ "${LOCAL_STORAGE:-1}" = 0 ]; then
  S3_PUBLIC_VAL=$(grep -E '^S3_PUBLIC_ENDPOINT=' .env 2>/dev/null | cut -d= -f2-)
  S3_PUBLIC_VAL="${S3_PUBLIC_VAL:-$S3_ENDPOINT_VAL}"
  # Same-origin uploads (the bundled RustFS, fronted by Caddy on SITE_URL)
  # need no CORS at all — that's the whole reason this check only runs for a
  # managed bucket, which is a genuinely different origin from SITE_URL.
  # A real preflight, not a guess: this is the exact request the browser
  # sends before the presigned PUT, and providers that don't recognise the
  # origin answer it with no Access-Control-* headers at all rather than an
  # error, which is invisible unless you go looking for it.
  cors=$(curl -sk -D - -o /dev/null --max-time 5 -X OPTIONS \
    "$S3_PUBLIC_VAL/$S3_BUCKET_VAL/diagnose-probe" \
    -H "Origin: $SITE_URL" \
    -H "Access-Control-Request-Method: PUT" \
    -H "Access-Control-Request-Headers: content-type" 2>/dev/null)
  if [ -z "$cors" ]; then
    hard "could not reach $S3_PUBLIC_VAL for a CORS preflight check"
  elif echo "$cors" | grep -qi "^access-control-allow-origin:"; then
    good "bucket CORS allows PUT from $SITE_URL"
  else
    hard "bucket has no CORS rule for $SITE_URL — uploads will fail in the browser before reaching storage"
    say  "add a CORS rule on the bucket allowing PUT/GET from $SITE_URL"
  fi
fi

head_ "Data"
if [ "${LOCAL_DB:-1}" = 1 ]; then
  if docker compose exec -T postgres pg_isready -U "$(grep -E '^POSTGRES_USER=' .env 2>/dev/null | cut -d= -f2- || echo app)" >/dev/null 2>&1; then
    good "postgres is accepting connections"
    # Both databases have to exist. init.sql only runs on an empty data
    # directory, so a stale volume silently skips creating the second one.
    dbs=$(docker compose exec -T postgres psql -U app -tAc "select datname from pg_database" 2>/dev/null | tr '\n' ' ')
    case " $dbs " in
      *" supertokens "*) good "the supertokens database exists" ;;
      *) hard "the supertokens database is missing — init.sql only runs on an empty volume" ;;
    esac
    version=$(docker compose exec -T postgres psql -U app -d app -tAc "select version_num from alembic_version" 2>/dev/null | tr -d '\r')
    [ -n "$version" ] && good "schema at $version" || soft "no alembic_version row — has migrate run?"
  else
    hard "postgres is not accepting connections"
  fi
else
  # Nothing local to reach into — this script is read-only and doesn't carry
  # a Postgres client of its own, so a managed instance's own health is
  # between it and its provider. `migrate`'s exit code (Containers, above) is
  # still the real signal for whether the schema applied.
  say "database is managed — not checked directly; see migrate's exit code above"
fi

for volume in postgres_data rustfs_data; do
  profile_var="LOCAL_DB"; [ "$volume" = "rustfs_data" ] && profile_var="LOCAL_STORAGE"
  if docker volume inspect "ayeayecaptain_$volume" >/dev/null 2>&1; then
    good "volume $volume exists"
  elif [ "${!profile_var:-1}" = 1 ]; then
    soft "volume $volume does not exist yet"
  else
    good "volume $volume does not exist (storage is managed elsewhere, as configured)"
  fi
done

head_ "Disk"
avail=$(df -Pk . | awk 'NR==2{print int($4/1048576)}')
if [ "${avail:-0}" -lt 2 ]; then
  hard "${avail}GB free — Postgres stops accepting writes when the disk fills"
elif [ "${avail:-0}" -lt 10 ]; then
  soft "${avail}GB free"
else
  good "${avail}GB free"
fi

head_ "Summary"
printf '  %d ok, %d warning(s), %d problem(s)\n\n' "$ok" "$warn" "$bad"
if [ "$bad" -gt 0 ]; then
  say "Start with: docker compose logs --tail=50 caddy api"
  say "If the site is dark on https, DNS probably isn't pointing here yet —"
  say "Caddy can't get a certificate and serves nothing while every container"
  say "reports healthy."
  exit 1
fi
exit 0
