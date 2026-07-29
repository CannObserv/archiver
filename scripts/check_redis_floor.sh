#!/usr/bin/env bash
# Assert the Redis change-bus broker meets the >=7.0 server floor (archiver#109).
#
# Run as an `ExecStartPre` on archiver.service. The floor is a *consumer*-path
# requirement — `XAUTOCLAIM`/`claim_stale` (co-core-aio bus consumer) needs the
# three-element reply added in Redis server 7.0 — but Archiver, as the bus
# operator, asserts it loud so a distro downgrade fails at producer start rather
# than silently breaking the future consumer.
#
# Soft by design, matching archiver.service's Wants=/After= (not Requires=):
#   - ARCHIVER_REDIS_URL unset  -> bus dormant, nothing to check          -> exit 0
#   - broker unreachable        -> outbox tolerates downtime, don't block -> exit 0 (warn)
#   - version read and < 7.0    -> a real downgrade, block the producer   -> exit 1
#   - version read and >= 7.0   -> ok                                     -> exit 0
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

# `-u` accepts redis:// and rediss:// URLs (TLS + auth). INFO server carries the
# `redis_version:MAJOR.MINOR.PATCH` line. Wrap in `timeout` so this ExecStartPre
# can never hang archiver startup: redis-cli has no connect-timeout flag, and a
# rediss:// URL against a plaintext/unreachable endpoint blocks on the TLS
# handshake indefinitely. A timeout kill yields an empty version → soft-skip.
# ARCHIVER_REDIS_FLOOR_TIMEOUT (seconds, default 5) bounds the call; tests lower it.
TIMEOUT_SECS="${ARCHIVER_REDIS_FLOOR_TIMEOUT:-5}"
TIMEOUT_BIN="$(command -v timeout || true)"
if [ -n "${TIMEOUT_BIN}" ]; then
  version="$("${TIMEOUT_BIN}" "${TIMEOUT_SECS}" redis-cli -u "${URL}" INFO server 2>/dev/null | tr -d '\r' | sed -n 's/^redis_version:\(.*\)$/\1/p')"
else
  version="$(redis-cli -u "${URL}" INFO server 2>/dev/null | tr -d '\r' | sed -n 's/^redis_version:\(.*\)$/\1/p')"
fi

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
exit 0
