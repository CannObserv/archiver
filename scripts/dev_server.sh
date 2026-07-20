#!/usr/bin/env bash
# Launch the Archiver dev server (port 8021) against a NON-PRODUCTION database.
#
# Why this script exists (archiver, 2026-07-18 incident):
#
#   CLAUDE.md used to document a raw uvicorn recipe for the dev server that
#   began by sourcing /etc/archiver/.env. That file sets ARCHIVER_DATABASE_URL
#   to *production*, so the dev server on 8021 and the systemd service on 8020
#   shared one database. A dashboard verification run drove the dev server and
#   wrote a verify79.example.com Domain, two InfoSources, and an AppUser into
#   the production registry. Nothing in the loop was wrong except the recipe:
#   the leak was the documented procedure working as written.
#
#   tests/conftest.py already refuses to let pytest point at production
#   (_check_test_url_safety). That guard does nothing for a hand-run server.
#   This script is the same guard for the other way into the database.
#
# Resolution order for the dev database:
#   1. ARCHIVER_DEV_DATABASE_URL — a persistent dev DB, if you keep one.
#   2. TEST_DATABASE_URL         — the default.
#
# Note on (2): pytest teardown runs DROP SCHEMA information CASCADE against
# TEST_DATABASE_URL. Running the suite while a dev server is up on the same
# database wipes your dev data mid-session. That is a survivable annoyance and
# strictly better than writing to production, but if it bites, create a
# dedicated database and set ARCHIVER_DEV_DATABASE_URL.
#
# Env knobs:
#   ARCHIVER_DEV_PORT                   default 8021 (8020 is systemd's, refused)
#   ARCHIVER_DEV_SERVER_DRY_RUN=1       print resolution, do not exec uvicorn
#   ARCHIVER_DEV_SERVER_SKIP_ENV_FILES=1  skip sourcing env files (tests)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${ARCHIVER_DEV_SERVER_SKIP_ENV_FILES:-}" != "1" ]]; then
  set -a
  # shellcheck disable=SC1091
  [ -f /etc/archiver/.env ] && . /etc/archiver/.env
  # shellcheck disable=SC1091
  [ -f "$REPO_ROOT/.env" ] && . "$REPO_ROOT/.env"
  set +a
fi

PORT="${ARCHIVER_DEV_PORT:-8021}"

# Port 8020 belongs to systemd (archiver.service). Binding it from here either
# fails on a port clash or, worse, shadows the live service.
if [[ "$PORT" == "8020" ]]; then
  echo "dev_server: refusing to bind port 8020 — that port belongs to systemd" >&2
  echo "  (archiver.service). Use the default 8021, or set ARCHIVER_DEV_PORT." >&2
  exit 1
fi

DEV_URL="${ARCHIVER_DEV_DATABASE_URL:-${TEST_DATABASE_URL:-}}"

if [[ -z "$DEV_URL" ]]; then
  echo "dev_server: no non-production database URL available." >&2
  echo "  Set TEST_DATABASE_URL (or ARCHIVER_DEV_DATABASE_URL) in .env." >&2
  echo "  Refusing to start rather than fall back to ARCHIVER_DATABASE_URL." >&2
  exit 1
fi

# The incident condition: the resolved dev URL IS a production URL. Mirrors
# _check_test_url_safety in tests/conftest.py.
for prod_var in ARCHIVER_DATABASE_URL DATABASE_URL; do
  prod_url="${!prod_var:-}"
  if [[ -n "$prod_url" && "$DEV_URL" == "$prod_url" ]]; then
    echo "dev_server: resolved dev database equals \$$prod_var — that is the" >&2
    echo "  production database. Refusing to start; the dev server would write" >&2
    echo "  into the production registry (see archiver 2026-07-18 incident)." >&2
    echo "  Point TEST_DATABASE_URL at a dedicated database ('_test' suffix)." >&2
    exit 1
  fi
done

# Force the dev URL onto the child, and clear the DATABASE_URL fallback that
# src/api/deps consults when ARCHIVER_DATABASE_URL is unset — leaving a
# production value there would reopen the hole from the other side.
export ARCHIVER_DATABASE_URL="$DEV_URL"
unset DATABASE_URL

# pytest teardown drops the `information` schema from TEST_DATABASE_URL, so the
# dev database is frequently schema-less at launch. Migrating here keeps the
# safe path usable; an operator who finds it broken tends to reach for the old
# recipe that pointed at production.
if [[ "${ARCHIVER_DEV_SKIP_MIGRATE:-}" == "1" ]]; then
  MIGRATE_REPORT="(skipped)"
else
  MIGRATE_REPORT="$ARCHIVER_DATABASE_URL"
fi

if [[ "${ARCHIVER_DEV_SERVER_DRY_RUN:-}" == "1" ]]; then
  echo "ARCHIVER_DATABASE_URL=$ARCHIVER_DATABASE_URL"
  echo "DATABASE_URL=(cleared)"
  echo "PORT=$PORT"
  echo "MIGRATE=$MIGRATE_REPORT"
  exit 0
fi

cd "$REPO_ROOT"

if [[ "${ARCHIVER_DEV_SKIP_MIGRATE:-}" != "1" ]]; then
  echo "dev_server: alembic upgrade head → $ARCHIVER_DATABASE_URL"
  uv run alembic upgrade head
fi

echo "dev_server: port $PORT → $ARCHIVER_DATABASE_URL"
exec uv run uvicorn src.api.main:app --host 0.0.0.0 --port "$PORT" --reload
