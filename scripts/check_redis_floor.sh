#!/usr/bin/env bash
# Assert the Redis change-bus broker's start-time preconditions (archiver#109/#128).
#
# Run as an `ExecStartPre` on archiver.service. Two assertions, different severities:
#
# 1. **Server >= 7.0 — blocks.** The floor is a *consumer*-path requirement —
#    `XAUTOCLAIM`/`claim_stale` (co-core-aio bus consumer) needs the three-element
#    reply added in Redis server 7.0 — but Archiver, as the bus operator, asserts
#    it loud so a distro downgrade fails at producer start rather than silently
#    breaking the future consumer.
#
# 2. **`maxmemory` non-zero — warns.** `maxmemory-policy noeviction` with the
#    default `maxmemory 0` is inert: no ceiling means no write ever gets refused,
#    so the bounded degradation the drop-in documents never engages and an
#    untrimmed stream grows until the kernel OOM-kills redis-server. This is the
#    only check that reads the *running* value — the file-parity test
#    (tests/deploy/test_installed_redis_dropin_matches_repo.py) compares the
#    drop-in on disk and cannot see a broker reconfigured via `CONFIG SET`, which
#    is how the cap is applied without a restart. It warns rather than blocks
#    because an uncapped broker does not break the producer; refusing to start the
#    API over a broker tuning value would turn tuning drift into an outage. #130's
#    periodic health check is where this becomes an alert.
#
# The name says "floor" for both — it is the set of minimum broker conditions
# archiver asserts at start. Renaming would mean re-pointing the ExecStartPre and
# re-deploying the unit for no behavioural gain.
#
# Soft by design, matching archiver.service's Wants=/After= (not Requires=):
#   - ARCHIVER_REDIS_URL unset  -> bus dormant, nothing to check          -> exit 0
#   - broker unreachable        -> outbox tolerates downtime, don't block -> exit 0 (warn)
#   - version read and < 7.0    -> a real downgrade, block the producer   -> exit 1
#   - version read and >= 7.0   -> ok, then probe the cap                 -> exit 0
#   - maxmemory 0               -> noeviction inert, warn loudly          -> exit 0
#   - maxmemory unreadable      -> don't cry wolf, stay quiet about it    -> exit 0 (warn)
#
# Only a genuinely-too-old *reachable* broker stops archiver from starting.
set -uo pipefail

URL="${ARCHIVER_REDIS_URL:-}"
if [ -z "${URL}" ]; then
  echo "check_redis_floor: ARCHIVER_REDIS_URL unset — bus dormant, skipping floor check"
  exit 0
fi

if ! command -v redis-cli >/dev/null 2>&1; then
  echo "check_redis_floor: redis-cli not found — cannot verify floor, not blocking start" >&2
  exit 0
fi

# A rediss:// URL needs a TLS-capable redis-cli; a build without `--tls` cannot
# connect, so INFO returns nothing and the check silently no-ops (soft-skips
# below). Warn so that gap is visible — relevant at a managed-provider migration,
# where the URL becomes rediss:// but the floor still matters.
case "${URL}" in
  rediss://*)
    if ! redis-cli --help 2>&1 | grep -q -- '--tls'; then
      echo "check_redis_floor: redis-cli lacks TLS support (no --tls) for a rediss:// URL —" >&2
      echo "check_redis_floor: the floor check will no-op; install a TLS-capable redis-cli" >&2
    fi
    ;;
esac

# `-u` accepts redis:// and rediss:// URLs (TLS + auth). Wrap every probe in
# `timeout` so this ExecStartPre can never hang archiver startup: redis-cli has no
# connect-timeout flag, and a rediss:// URL against a plaintext/unreachable
# endpoint blocks on the TLS handshake indefinitely. A timeout kill yields an
# empty reply → soft-skip. ARCHIVER_REDIS_FLOOR_TIMEOUT (seconds, default 5)
# bounds each call; tests lower it.
TIMEOUT_SECS="${ARCHIVER_REDIS_FLOOR_TIMEOUT:-5}"
TIMEOUT_BIN="$(command -v timeout || true)"

# Run one redis-cli command against ${URL}, bounded by the timeout when available.
# Stdout is the raw reply with CRs stripped; failures are swallowed to an empty
# reply so every caller takes the same soft path.
redis_probe() {
  if [ -n "${TIMEOUT_BIN}" ]; then
    "${TIMEOUT_BIN}" "${TIMEOUT_SECS}" redis-cli -u "${URL}" "$@" 2>/dev/null | tr -d '\r'
  else
    redis-cli -u "${URL}" "$@" 2>/dev/null | tr -d '\r'
  fi
}

# --- 1. Server version floor (blocking) ------------------------------------
# INFO server carries the `redis_version:MAJOR.MINOR.PATCH` line.
version="$(redis_probe INFO server | sed -n 's/^redis_version:\(.*\)$/\1/p')"

if [ -z "${version}" ]; then
  echo "check_redis_floor: could not read redis_version (broker unreachable?) — not blocking start" >&2
  exit 0
fi

major="${version%%.*}"
if ! [ "${major}" -ge 7 ] 2>/dev/null; then
  echo "check_redis_floor: Redis ${version} is below the >=7.0 change-bus floor" >&2
  echo "check_redis_floor: the consumer path (XAUTOCLAIM/claim_stale) requires server >= 7.0" >&2
  exit 1
fi

echo "check_redis_floor: Redis ${version} meets the >=7.0 floor"

# --- 2. Live memory cap (warn only, archiver#128) --------------------------
# `CONFIG GET maxmemory` replies with two lines: the name, then the value in
# bytes. Take the second line rather than grepping, so a value that happens to
# equal the name cannot confuse the parse.
maxmemory="$(redis_probe CONFIG GET maxmemory | sed -n '2p')"

if [ -z "${maxmemory}" ]; then
  # Distinct from "uncapped": a restricted ACL or a killed probe reads as empty,
  # and crying "uncapped" here would train the operator to ignore the real one.
  echo "check_redis_floor: could not read maxmemory (restricted ACL? probe timed out?) — not blocking start" >&2
  exit 0
fi

if [ "${maxmemory}" = "0" ]; then
  echo "check_redis_floor: WARNING — broker maxmemory is 0 (uncapped)" >&2
  echo "check_redis_floor: maxmemory-policy noeviction is INERT without a cap: no write is ever" >&2
  echo "check_redis_floor: refused, so an untrimmed stream grows until the kernel OOM-kills" >&2
  echo "check_redis_floor: redis-server instead of erroring. The cap belongs to the ExecStart in" >&2
  echo "check_redis_floor: deploy/redis-server.dropin.conf (the authoritative value); apply it live" >&2
  echo "check_redis_floor: without a restart via: redis-cli CONFIG SET maxmemory <bytes>" >&2
  exit 0
fi

echo "check_redis_floor: broker maxmemory is ${maxmemory} bytes (capped)"
exit 0
