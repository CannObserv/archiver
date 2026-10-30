#!/usr/bin/env bash
# Launch the Archiver dev server (port 8001) against a NON-PRODUCTION database.
#
# Why this script exists (archiver, 2026-07-18 incident):
#
#   CLAUDE.md used to document a raw uvicorn recipe for the dev server that
#   began by sourcing /etc/archiver/.env. That file sets ARCHIVER_DATABASE_URL
#   to *production*, so the dev server and the systemd service shared one
#   database. A dashboard verification run drove the dev server and
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
#   ARCHIVER_DEV_DATABASE_URL             persistent dev DB; wins over TEST_DATABASE_URL
#   ARCHIVER_DEV_PORT                     default 8001 (8000 is systemd's, refused)
#   ARCHIVER_DEV_SKIP_MIGRATE=1           skip the alembic upgrade
#   ARCHIVER_DEV_SERVER_DRY_RUN=1         print resolution, do not exec uvicorn
#   ARCHIVER_DEV_SERVER_SKIP_ENV_FILES=1  skip sourcing env files (tests)
#   ARCHIVER_DEV_POWER_MAP_API_KEY        Power Map read key for dev; unset → dormant
#   ARCHIVER_DEV_POWER_MAP_BASE_URL       Power Map base URL for dev (default: production)
#   ARCHIVER_DEV_NOTIFIER_BASE_URL        dev Notifier (:9001); with the key → enabled
#   ARCHIVER_DEV_NOTIFIER_API_KEY         dev tenant key; either unset → dormant
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${ARCHIVER_DEV_SERVER_SKIP_ENV_FILES:-}" != "1" ]]; then
  set -a
  # shellcheck disable=SC1091
  [ -r /etc/archiver/.env ] && . /etc/archiver/.env
  # shellcheck disable=SC1091
  [ -f "$REPO_ROOT/.env" ] && . "$REPO_ROOT/.env"
  set +a
fi

PORT="${ARCHIVER_DEV_PORT:-8001}"

# Port 8000 belongs to systemd (archiver.service). Binding it from here either
# fails on a port clash or, worse, shadows the live service.
if [[ "$PORT" == "8000" ]]; then
  echo "dev_server: refusing to bind port 8000 — that port belongs to systemd" >&2
  echo "  (archiver.service). Use the default 8001, or set ARCHIVER_DEV_PORT." >&2
  exit 1
fi

DEV_URL="${ARCHIVER_DEV_DATABASE_URL:-${TEST_DATABASE_URL:-}}"

if [[ -z "$DEV_URL" ]]; then
  echo "dev_server: no non-production database URL available." >&2
  echo "  Set TEST_DATABASE_URL (or ARCHIVER_DEV_DATABASE_URL) in .env." >&2
  echo "  Refusing to start rather than fall back to ARCHIVER_DATABASE_URL." >&2
  exit 1
fi

# db_name <url> — the database name (the path segment), or empty when the input
# is not a connection URL. Mirrors urlsplit() in src/core/db_safety.py; the
# ordering here is load-bearing (archiver#99):
#
#   1. Require '://'. A bare string like `archiver_test` is not a URL — return
#      nothing so the caller fails closed, matching urlsplit's scheme check.
#   2. Strip the query string BEFORE credentials. An '@' can appear inside a
#      query (e.g. ?options=endpoint%3Da@b); stripping credentials first with
#      `#*@` would eat through it and return the query tail as the name.
#   3. Then strip credentials, then host:port.
#   4. Require a path segment ('/after/host'); without one there is no database
#      name, so return nothing (matches urlsplit's empty-path -> None).
db_name() {
  local url="$1"
  case "$url" in
    *://*) ;;
    *) return 0 ;;          # not a URL — no name
  esac
  url="${url#*://}"         # drop scheme://
  url="${url%%\?*}"         # drop query string FIRST (may contain '@')
  url="${url#*@}"           # drop credentials, if any
  case "$url" in
    */*) url="${url#*/}" ;; # drop host:port, leaving the path
    *) return 0 ;;          # no path segment — no name
  esac
  printf '%s' "$url"
}

DEV_DB_NAME="$(db_name "$DEV_URL")"

# Positive assertion, not a comparison against known production URLs. String
# equality is defeated by cosmetic differences — postgresql://…/archiver and
# postgresql+asyncpg://…/archiver name the same database, as do localhost and
# 127.0.0.1. The database NAME is the boundary that actually holds. Mirrors
# src/core/db_safety.py, which enforces the same rule inside the application.
case "$DEV_DB_NAME" in
  *_test | *_dev) ;;
  *)
    echo "dev_server: refusing to start against database '${DEV_DB_NAME:-<unparseable>}'." >&2
    echo "  The dev database name must end in '_test' or '_dev'; anything else" >&2
    echo "  is treated as production (see archiver 2026-07-18 incident, where" >&2
    echo "  a dev server wrote into the production registry)." >&2
    echo "  Point TEST_DATABASE_URL or ARCHIVER_DEV_DATABASE_URL at a" >&2
    echo "  dedicated database, e.g. archiver_test." >&2
    exit 1
    ;;
esac

# Force the dev URL onto the child, and clear the DATABASE_URL fallback that
# src/api/deps consults when ARCHIVER_DATABASE_URL is unset — leaving a
# production value there would reopen the hole from the other side.
export ARCHIVER_DATABASE_URL="$DEV_URL"
unset DATABASE_URL

# redis_identity <url> — normalized `host:port` for a redis[s] URL
# (`unix:<path>` for a socket), or empty for empty input. The equality guard
# below compares identities, not raw strings, so cosmetic differences
# (localhost vs 127.0.0.1 vs [::1], omitted default port) do NOT slip a dev
# server onto prod's broker — the same reasoning the DB guard's db_name()
# applies (string equality is defeated by spelling; the addressed resource is
# the boundary). The /db index is deliberately NOT part of the identity
# (archiver#240): an index is no boundary — Redis ACLs cannot partition by it —
# and the broker runs `databases 1` with no `+select`, so `.../1` on prod's
# host:port is the same broker, refused here rather than failing later as a
# publisher-init error that reads like dormancy. Mirrors db_name()'s ordering:
# require a scheme-or-bare host, strip the query BEFORE credentials (an '@' can
# live in a query), then drop any /db and split host:port, applying the redis
# default port (6379).
#
# Names are compared, never resolved: `broker` vs its tailnet IP or FQDN reads
# as distinct and passes. Loopback is the only alias folded — the same
# two-names-one-host trap as docs/reference/tailscale.md.
redis_identity() {
  local url="$1"
  [[ -z "$url" ]] && return 0
  local scheme=""
  case "$url" in
    *://*) scheme="${url%%://*}"; url="${url#*://}" ;;   # drop scheme
  esac
  url="${url%%\?*}"              # drop query string FIRST (may contain '@')
  url="${url#*@}"               # drop credentials, if any
  if [[ "${scheme,,}" == "unix" ]]; then
    printf 'unix:%s' "$url"     # a socket is addressed by its path
    return 0
  fi
  local hostport="${url%%/*}"    # drop /db — not part of the identity
  local host port
  case "$hostport" in
    \[*\]:*) host="${hostport%]:*}]"; port="${hostport##*]:}" ;;  # [v6]:port
    \[*\])   host="$hostport"; port="6379" ;;   # [v6] — its colons are no port
    *:*)     host="${hostport%:*}"; port="${hostport##*:}" ;;
    *)       host="$hostport"; port="6379" ;;
  esac
  [[ -z "$port" ]] && port="6379"
  host="${host,,}"              # lowercase
  case "$host" in
    ""|localhost|"[::1]") host="127.0.0.1" ;;   # loopback, however spelled
  esac
  printf '%s:%s' "$host" "$port"
}

# --- Redis change-bus isolation (archiver#109) ---
# Same leak class as the DB (2026-07-18): /etc/archiver/.env sets the production
# ARCHIVER_REDIS_URL, so a dev server that inherited it would publish onto prod's
# info.changes stream. The dev server never inherits it — it either uses an
# explicit ARCHIVER_DEV_REDIS_URL (a distinct broker — in practice a local
# throwaway, see docs/ENVIRONMENT.md) or runs bus-dormant. And a dev override
# addressing the SAME broker as production (by normalized host:port, not just
# string, and whatever the DB index) is refused outright.
PROD_REDIS_URL="${ARCHIVER_REDIS_URL:-}"
DEV_REDIS_URL="${ARCHIVER_DEV_REDIS_URL:-}"
if [[ -n "$DEV_REDIS_URL" ]]; then
  DEV_REDIS_ID="$(redis_identity "$DEV_REDIS_URL")"
  if [[ "$DEV_REDIS_ID" == "$(redis_identity "$PROD_REDIS_URL")" ]]; then
    echo "dev_server: refusing — ARCHIVER_DEV_REDIS_URL addresses the same broker" >&2
    echo "  as the production ARCHIVER_REDIS_URL ($DEV_REDIS_ID, by normalized" >&2
    echo "  address; a different DB index is no boundary). Leave it unset to run" >&2
    echo "  bus-dormant, or use a local throwaway broker:" >&2
    echo "    docker run --rm -p 127.0.0.1:6380:6379 redis:7" >&2
    echo "    ARCHIVER_DEV_REDIS_URL=redis://127.0.0.1:6380/0" >&2
    exit 1
  fi
  # Positive, as the database name rule is (archiver#339): /etc/archiver/.env is
  # root's alone, so this shell rarely holds prod's URL for the comparison
  # above. A dev broker is a local one; the shared broker never is.
  case "$DEV_REDIS_ID" in
    127.0.0.1:* | unix:*) ;; # redis_identity folds every loopback spelling
    *)
      echo "dev_server: refusing — ARCHIVER_DEV_REDIS_URL ($DEV_REDIS_ID) is" >&2
      echo "  not a local broker. A dev server runs bus-dormant (leave it unset)" >&2
      echo "  or on a local throwaway, never the shared broker:" >&2
      echo "    docker run --rm -p 127.0.0.1:6380:6379 redis:7" >&2
      echo "    ARCHIVER_DEV_REDIS_URL=redis://127.0.0.1:6380/0" >&2
      exit 1
      ;;
  esac
  export ARCHIVER_REDIS_URL="$DEV_REDIS_URL"
  REDIS_REPORT="$ARCHIVER_REDIS_URL"
else
  # No explicit dev broker → run bus-dormant rather than inherit prod's URL.
  unset ARCHIVER_REDIS_URL
  REDIS_REPORT="(dormant)"
fi

# --- Liveness isolation (archiver#297) ---
# Only archiver.service sets the co-archiver-live monitor id and hands over the
# Status key. A dev server holding both would check in `ok` for production and
# mask a real outage, so it drops whatever it inherited and runs liveness off.
unset CO_ARCHIVER_LIVE_MONITOR_ID CREDENTIALS_DIRECTORY
LIVENESS_REPORT="${CO_ARCHIVER_LIVE_MONITOR_ID:-(off)}"

# --- Power Map credential isolation (archiver#304) ---
# /etc/archiver/.env carries the live service's ARCHIVER_POWER_MAP_API_KEY. The
# dev server never inherits it: it uses ARCHIVER_DEV_POWER_MAP_API_KEY (and
# ARCHIVER_DEV_POWER_MAP_BASE_URL, if set) or runs with Power Map dormant. No
# same-target refusal, unlike Redis: the key is read-only, so reading production
# Power Map from dev is the supported posture; only the inheritance is refused.
DEV_PM_KEY="${ARCHIVER_DEV_POWER_MAP_API_KEY:-}"
DEV_PM_URL="${ARCHIVER_DEV_POWER_MAP_BASE_URL:-}"
unset ARCHIVER_POWER_MAP_API_KEY ARCHIVER_POWER_MAP_BASE_URL
if [[ -n "$DEV_PM_KEY" ]]; then
  export ARCHIVER_POWER_MAP_API_KEY="$DEV_PM_KEY"
  if [[ -n "$DEV_PM_URL" ]]; then
    export ARCHIVER_POWER_MAP_BASE_URL="$DEV_PM_URL"
    POWER_MAP_REPORT="$DEV_PM_URL (dev key)"
  else
    POWER_MAP_REPORT="(default base URL, dev key)"
  fi
else
  POWER_MAP_REPORT="(dormant)"
fi

# --- Notifier credential isolation (archiver#368) ---
# Only archiver.service may notify the production tenant: it alone sets
# ARCHIVER_NOTIFIER_BASE_URL and ARCHIVER_NOTIFIER_ENABLED=1, and hands the key over
# as a credential (CREDENTIALS_DIRECTORY, already dropped above). A notification
# reaches real people and cannot be recalled (watcher#277/#278), so whatever this
# shell inherited is dropped, and the dev pair is mapped onto the gate's variables
# with the flag set only beside both. A dev URL on :9000, production Notifier, is
# refused outright, the ARCHIVER_DEV_REDIS_URL rule: the dev key gets 401 there,
# so a dev URL on :9000 means a production key was pasted in.
#
# notifier_port <url> — the port a Notifier URL reaches, or nothing when it is not
# a usable http(s) URL. src/core/notifier/gate.py's TARGET_PATTERN and
# target_port(), character for character; tests/scripts/test_db_guard_parity.py
# feeds both one corpus. LC_ALL=C: a bracket range is locale-dependent otherwise.
NOTIFIER_TARGET_RE='^([A-Za-z]+)://(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9._~%-]+)(:([0-9]*))?([/?#][!-~]*)?$'
notifier_port() {
  local LC_ALL=C url="$1" scheme port default
  [[ "$url" =~ $NOTIFIER_TARGET_RE ]] || return 0
  scheme="${BASH_REMATCH[1],,}"
  port="${BASH_REMATCH[4]}"
  case "$scheme" in
    http) default=80 ;;
    https) default=443 ;;
    *) return 0 ;;
  esac
  if [[ -z "$port" ]]; then
    echo "$default"
    return 0
  fi
  ((${#port} > 5)) && return 0 # bash arithmetic would overflow; the gate refuses too
  port=$((10#$port))
  ((port >= 1 && port <= 65535)) || return 0
  echo "$port"
}

DEV_NOTIFIER_URL="${ARCHIVER_DEV_NOTIFIER_BASE_URL:-}"
DEV_NOTIFIER_KEY="${ARCHIVER_DEV_NOTIFIER_API_KEY:-}"
unset ARCHIVER_NOTIFIER_BASE_URL ARCHIVER_NOTIFIER_API_KEY ARCHIVER_NOTIFIER_ENABLED
unset ARCHIVER_DEV_NOTIFIER_BASE_URL ARCHIVER_DEV_NOTIFIER_API_KEY
if [[ -n "$DEV_NOTIFIER_URL" ]]; then
  DEV_NOTIFIER_PORT="$(notifier_port "$DEV_NOTIFIER_URL")"
  if [[ -z "$DEV_NOTIFIER_PORT" ]]; then
    echo "dev_server: refusing — ARCHIVER_DEV_NOTIFIER_BASE_URL is not an" >&2
    echo "  http(s)://host[:port] URL. The dev Notifier is http://notifier:9001." >&2
    exit 1
  fi
  if [[ "$DEV_NOTIFIER_PORT" == "9000" ]]; then
    echo "dev_server: refusing — ARCHIVER_DEV_NOTIFIER_BASE_URL is on port 9000," >&2
    echo "  production Notifier. Only archiver.service notifies production, with its" >&2
    echo "  credential. The dev Notifier is http://notifier:9001, with the dev key." >&2
    exit 1
  fi
fi
if [[ -n "$DEV_NOTIFIER_URL" && -n "$DEV_NOTIFIER_KEY" ]]; then
  export ARCHIVER_NOTIFIER_BASE_URL="$DEV_NOTIFIER_URL"
  export ARCHIVER_NOTIFIER_API_KEY="$DEV_NOTIFIER_KEY"
  export ARCHIVER_NOTIFIER_ENABLED=1
elif [[ -n "$DEV_NOTIFIER_URL" || -n "$DEV_NOTIFIER_KEY" ]]; then
  echo "dev_server: Notifier dormant — set both ARCHIVER_DEV_NOTIFIER_BASE_URL and" >&2
  echo "  ARCHIVER_DEV_NOTIFIER_API_KEY, or neither." >&2
fi
unset DEV_NOTIFIER_KEY
# From what is exported, not from the inputs: the report shows what uvicorn gets.
if [[ "${ARCHIVER_NOTIFIER_ENABLED:-}" == "1" ]]; then
  NOTIFIER_REPORT="$ARCHIVER_NOTIFIER_BASE_URL (dev key)"
else
  NOTIFIER_REPORT="(dormant)"
fi

# pytest teardown drops the `information` schema from TEST_DATABASE_URL, so the
# dev database is frequently schema-less at launch. Migrating here keeps the
# safe path usable; an operator who finds it broken tends to reach for the old
# recipe that pointed at production.
#
# Decided once, so the dry-run report (which tests assert on) and the executed
# path cannot drift apart.
if [[ "${ARCHIVER_DEV_SKIP_MIGRATE:-}" == "1" ]]; then
  DO_MIGRATE=0
  MIGRATE_REPORT="(skipped)"
else
  DO_MIGRATE=1
  MIGRATE_REPORT="$ARCHIVER_DATABASE_URL"
fi

if [[ "${ARCHIVER_DEV_SERVER_DRY_RUN:-}" == "1" ]]; then
  echo "ARCHIVER_DATABASE_URL=$ARCHIVER_DATABASE_URL"
  echo "DATABASE_URL=(cleared)"
  echo "PORT=$PORT"
  echo "MIGRATE=$MIGRATE_REPORT"
  echo "REDIS=$REDIS_REPORT"
  echo "POWER_MAP=$POWER_MAP_REPORT"
  echo "NOTIFIER=$NOTIFIER_REPORT"
  echo "LIVENESS=$LIVENESS_REPORT"
  exit 0
fi

cd "$REPO_ROOT"

if [[ "$DO_MIGRATE" == "1" ]]; then
  echo "dev_server: alembic upgrade head → $ARCHIVER_DATABASE_URL"
  uv run alembic upgrade head
fi

echo "dev_server: port $PORT → $ARCHIVER_DATABASE_URL"
exec uv run uvicorn src.api.main:app --host 0.0.0.0 --port "$PORT" --reload \
  --log-config src/core/log_config.json
