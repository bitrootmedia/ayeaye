#!/usr/bin/env bash
#
# Walk through writing a .env for a deployment that isn't the plain default —
# in particular, one that brings its own Postgres and/or S3-compatible storage
# instead of the bundled containers.
#
#   ./scripts/setup-interactive.sh
#
# scripts/setup.sh stays deliberately non-interactive, because a prompt is
# useless in a provisioning script and this is software people install on
# servers. This is the opposite case: a person, at a terminal, who has a
# managed database or bucket already and would otherwise have to hand-compute
# a DATABASE_URL and remember which of eight S3_* variables matter. Answer six
# questions instead of reading .env.example end to end.
#
# Every answer here maps to exactly the variables .env.example documents —
# this script computes and writes them, it does not invent new configuration.
set -euo pipefail

cd "$(dirname "$0")/.."

# `openssl` is on every machine that can run Docker, but fall back anyway
# rather than emitting a weak secret or an empty one. Same as setup.sh.
secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "${1:-24}"
  else
    LC_ALL=C tr -dc 'a-f0-9' < /dev/urandom | head -c $(( ${1:-24} * 2 ))
  fi
}

ask() {  # ask PROMPT DEFAULT -> echoes the answer
  local prompt="$1" default="${2:-}" reply
  if [ -n "$default" ]; then
    read -r -p "$prompt [$default]: " reply
    echo "${reply:-$default}"
  else
    read -r -p "$prompt: " reply
    echo "$reply"
  fi
}

ask_secret() {  # like ask, but the terminal doesn't echo it back
  local prompt="$1" reply
  read -r -s -p "$prompt: " reply
  echo >&2
  echo "$reply"
}

confirm() {  # confirm PROMPT -> 0 (yes) or 1 (no); default is no
  local prompt="$1" reply
  read -r -p "$prompt [y/N]: " reply
  case "$reply" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

echo "ayeayecaptain setup"
echo "==================="
echo
echo "Answers with a default in brackets — press Enter to accept it."
echo

# --- site --------------------------------------------------------------------

SITE_URL=$(ask "Site URL, scheme included (https:// for a real domain)" "http://localhost")
case "$SITE_URL" in
  http://*|https://*) ;;
  *)
    echo "Needs a scheme, e.g. https://tasks.example.com" >&2
    exit 2 ;;
esac

ACME_EMAIL="admin@localhost"
if [ "${SITE_URL#https://}" != "$SITE_URL" ]; then
  ACME_EMAIL=$(ask "Contact email for Let's Encrypt" "you@example.com")
  if [ "$ACME_EMAIL" = "you@example.com" ] || [ -z "$ACME_EMAIL" ]; then
    echo "Let's Encrypt needs a real contact address." >&2
    exit 2
  fi
fi

# --- database ------------------------------------------------------------------

echo
echo "Database"
echo "--------"
echo "1) Run Postgres in this stack (default — nothing else to configure)"
echo "2) I have a managed Postgres instance"
DB_CHOICE=$(ask "Choose 1 or 2" "1")

PROFILES=()
POSTGRES_USER=app
POSTGRES_DB=app
POSTGRES_PASSWORD=""
DATABASE_URL=""
SUPERTOKENS_DATABASE_URL=""

if [ "$DB_CHOICE" = "2" ]; then
  echo
  echo "SuperTokens keeps identity in its OWN database on the same server —"
  echo "never the app's — so a managed instance needs two connection strings."
  DB_HOST=$(ask "Host" "")
  DB_PORT=$(ask "Port" "5432")
  DB_USER=$(ask "User" "")
  DB_PASS=$(ask_secret "Password (hidden)")
  APP_DB=$(ask "App database name" "app")
  ST_DB=$(ask "SuperTokens database name" "supertokens")
  SSL=""
  if confirm "Does this provider require SSL?"; then
    SSL="?sslmode=require"
  fi
  DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${APP_DB}${SSL}"
  SUPERTOKENS_DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${ST_DB}${SSL}"
  echo
  echo "Before bringing the stack up, on that instance:"
  echo "  CREATE DATABASE ${ST_DB};"
  echo "(the app database itself is usually already created by the provider)."
else
  PROFILES+=("local-db")
  POSTGRES_PASSWORD=$(secret 24)
  DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
  SUPERTOKENS_DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/supertokens"
fi

# --- object storage -------------------------------------------------------

echo
echo "Object storage"
echo "--------------"
echo "1) Run RustFS in this stack (default — nothing else to configure)"
echo "2) I have a managed S3-compatible bucket"
S3_CHOICE=$(ask "Choose 1 or 2" "1")

S3_ENDPOINT=""
S3_PUBLIC_ENDPOINT=""
S3_REGION="us-east-1"
S3_BUCKET="media"
S3_ACCESS_KEY=""
S3_SECRET_KEY=""
RUSTFS_ACCESS_KEY=""
RUSTFS_SECRET_KEY=""

if [ "$S3_CHOICE" = "2" ]; then
  S3_ENDPOINT=$(ask "Endpoint URL (e.g. https://s3.<region>.amazonaws.com)" "")
  S3_PUBLIC_ENDPOINT=$(ask "Public endpoint, if different (blank = same as above)" "$S3_ENDPOINT")
  S3_REGION=$(ask "Region" "$S3_REGION")
  S3_BUCKET=$(ask "Bucket name" "$S3_BUCKET")
  S3_ACCESS_KEY=$(ask "Access key" "")
  S3_SECRET_KEY=$(ask_secret "Secret key (hidden)")
  echo
  echo "Two things this product has never needed before, both real with a"
  echo "managed bucket:"
  echo "  - uploads go straight from the browser to storage, and it's no"
  echo "    longer the same origin as $SITE_URL — add a CORS rule on the"
  echo "    bucket allowing PUT and GET from that origin, or every upload"
  echo "    fails before it reaches storage."
  echo "  - this product signs path-style requests only. Most S3-compatible"
  echo "    providers support that; real AWS S3 does NOT in any region opened"
  echo "    after September 2020."
else
  PROFILES+=("local-storage")
  S3_ENDPOINT="http://rustfs:9000"
  S3_KEY=$(secret 12)
  S3_SECRET=$(secret 24)
  S3_ACCESS_KEY="$S3_KEY"
  S3_SECRET_KEY="$S3_SECRET"
  RUSTFS_ACCESS_KEY="$S3_KEY"
  RUSTFS_SECRET_KEY="$S3_SECRET"
fi

# --- email (optional) --------------------------------------------------------

echo
echo "Email (optional)"
echo "-----------------"
echo "Leave this out and the app logs what it would have sent, then carries"
echo "on — invites still produce a copyable link, and a password-reset link"
echo "appears in \`docker compose logs api\`. That's a supported way to run."
SMTP_HOST="" SMTP_PORT="587" SMTP_USERNAME="" SMTP_PASSWORD="" SMTP_START_TLS="true" MAIL_FROM=""
if confirm "Configure SMTP now?"; then
  SMTP_HOST=$(ask "SMTP host" "")
  SMTP_PORT=$(ask "SMTP port" "587")
  SMTP_USERNAME=$(ask "SMTP username" "")
  SMTP_PASSWORD=$(ask_secret "SMTP password (hidden)")
  MAIL_FROM=$(ask "From address (must be on a domain your provider verified)" "")
  if confirm "Use STARTTLS?"; then SMTP_START_TLS="true"; else SMTP_START_TLS="false"; fi
fi

# --- write it ------------------------------------------------------------------

SUPERTOKENS_API_KEY=$(secret 24)
PROFILES_CSV=$(IFS=,; echo "${PROFILES[*]:-}")

if [ -f .env ]; then
  echo
  if ! confirm ".env already exists. Overwrite it? This loses any password it holds"; then
    echo "Not touching .env." >&2
    exit 1
  fi
fi

umask 077  # the file is about to contain every secret this deployment has

cat > .env <<EOF
# Generated by scripts/setup-interactive.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ).
#
# This file is the deployment. Back it up somewhere other than the machine it
# is on. See .env.example for what each of these does.

SITE_URL=$SITE_URL
ACME_EMAIL=$ACME_EMAIL

# Which of the bundled containers actually run. Empty means both Postgres and
# storage are managed elsewhere.
COMPOSE_PROFILES=$PROFILES_CSV

SUPERTOKENS_API_KEY=$SUPERTOKENS_API_KEY

POSTGRES_USER=$POSTGRES_USER
POSTGRES_DB=$POSTGRES_DB
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
DATABASE_URL=$DATABASE_URL
SUPERTOKENS_DATABASE_URL=$SUPERTOKENS_DATABASE_URL

S3_ENDPOINT=$S3_ENDPOINT
S3_PUBLIC_ENDPOINT=$S3_PUBLIC_ENDPOINT
S3_REGION=$S3_REGION
S3_BUCKET=$S3_BUCKET
S3_ACCESS_KEY=$S3_ACCESS_KEY
S3_SECRET_KEY=$S3_SECRET_KEY
RUSTFS_ACCESS_KEY=$RUSTFS_ACCESS_KEY
RUSTFS_SECRET_KEY=$RUSTFS_SECRET_KEY

SMTP_HOST=$SMTP_HOST
SMTP_PORT=$SMTP_PORT
SMTP_USERNAME=$SMTP_USERNAME
SMTP_PASSWORD=$SMTP_PASSWORD
SMTP_START_TLS=$SMTP_START_TLS
MAIL_FROM=$MAIL_FROM
EOF

echo
echo "Wrote .env."
echo
if [ "$DB_CHOICE" = "2" ]; then
  echo "Before \`docker compose up -d\`, on your managed Postgres instance:"
  echo "  CREATE DATABASE ${ST_DB:-supertokens};"
fi
if [ "$S3_CHOICE" = "2" ]; then
  echo "Before \`docker compose up -d\`, on your bucket: a CORS rule allowing"
  echo "PUT and GET from $SITE_URL."
fi
echo
echo "Next:"
echo "  docker compose up -d"
if [ "${SITE_URL#https://}" != "$SITE_URL" ]; then
  echo
  echo "Point an A record at this machine first, or Caddy can't get a"
  echo "certificate and the site will be dark while every container looks fine."
fi
echo
echo "Back up .env. It holds every secret and connection string this"
echo "deployment has."
