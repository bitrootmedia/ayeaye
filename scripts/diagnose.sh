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

  # Shipping the example values to the internet is the failure this whole
  # script exists to catch early.
  for var in POSTGRES_PASSWORD S3_SECRET_KEY SUPERTOKENS_API_KEY; do
    value=$(grep -E "^$var=" .env | cut -d= -f2-)
    case "$value" in
      *dev-only*|*change-me*|"")
        case "$SITE_URL" in
          https://*) hard "$var is still an example value on a public site" ;;
          *) soft "$var is an example value (fine on localhost, not on a domain)" ;;
        esac ;;
      *) good "$var is set to something of your own" ;;
    esac
  done
fi

head_ "Containers"
if ! docker compose ps --format '{{.Service}}' >/dev/null 2>&1; then
  hard "cannot talk to this project's containers — is the daemon running?"
else
  expected="caddy api worker scheduler web postgres redis supertokens rustfs"
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

head_ "Data"
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

for volume in postgres_data rustfs_data; do
  if docker volume inspect "ayeayecaptain_$volume" >/dev/null 2>&1; then
    good "volume $volume exists"
  else
    soft "volume $volume does not exist yet"
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
