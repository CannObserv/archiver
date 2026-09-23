#!/usr/bin/env bash
# Assert the Redis change-bus broker's start-time preconditions (archiver#109/#128).
#
# Run as an `ExecStartPre` on archiver.service. Two assertions, different severities:
#
# 1. **Server >= 7.0 — blocks.** The floor is a *consumer*-path requirement —
#    `XAUTOCLAIM`/`claim_stale_page` (co-core-aio bus consumer) needs the three-element
#    reply added in Redis server 7.0 — but Archiver, as the bus operator, asserts
#    it loud so a distro downgrade fails at producer start rather than silently
#    breaking the future consumer.
#
# 2. **`maxmemory` non-zero — warns.** `maxmemory-policy noeviction` with the
#    default `maxmemory 0` is inert: no ceiling means no write ever gets refused,
#    so the bounded degradation the drop-in documents never engages and an
#    untrimmed stream grows until the kernel OOM-kills redis-server. This is the
#    only check *this repo* has that reads the running value: the drop-in and its
#    file-parity test moved to CannObserv/broker with the broker (archiver#193
#    D6), and a file-parity test cannot see a broker reconfigured via `CONFIG
#    SET` anyway, which is how the cap is applied without a restart. It warns
#    rather than blocks because an uncapped broker does not break the producer;
#    refusing to start the API over a broker tuning value would turn tuning drift
#    into an outage. That repo's bus-health probe is where this becomes an alert,
#    every tick, from the broker's own node.
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
#   - scheme not redis(s)://    -> cannot probe, say so                   -> exit 0 (warn)
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

# --- Split the URL into flags; the password goes via the environment ---------
# NOT `redis-cli -u "${URL}"` (archiver#253). The URL carries the broker
# password, and an argument vector is world-readable (/proc/<pid>/cmdline, mode
# 444) where the environment is not (/proc/<pid>/environ, mode 400). redis-cli
# reads REDISCLI_AUTH and documents it as the safe path. The same holds for
# every process the password passes through - `timeout` included - so it is
# handed over as a prefix assignment, never as an `env VAR=...` argument.
#
# Two rules, and which one applies matters:
#
# READING the URL follows redis-py, so probe and service extract the same
# credential from the same string:
#   - userinfo ends at the LAST '@' (redis-py's rpartition; `-u` takes the first)
#   - userinfo is split at the first ':'; both halves are percent-decoded, and
#     an invalid escape is kept literally (redis-py's unquote; `-u` rejects it)
#
# SENDING AUTH follows `-u`, NOT redis-py - the probe judges the URL the way
# the #195 diagnostics below and deploy/README.md describe it. Two forms
# deliberately differ from what the service sends; do not "fix" either:
#   - `user:pass@` sends `--user user`, EVEN WHEN `user` IS EMPTY. `:pass@` is
#     archiver#195: redis-py sends `AUTH pass` and succeeds, this sends
#     `AUTH "" pass` and fails, and the diagnostics exist to say so (#253
#     requires it). Defaulting the user to `default` would pass the probe on a
#     URL its own messages call wrong.
#   - `pass@` (no ':') sends no --user: `-u`'s single-argument AUTH, where
#     redis-py would send `AUTH pass ""`.
#
# And: no port is 6379, no path is db 0 (no -n), rediss:// adds --tls.
# Never echo ${URL}: every message here lands in journald.
unset REDISCLI_AUTH  # the URL is the only credential source, as it is for -u

# Percent-decode $1 into DECODED. Only a valid %XX decodes; any other '%' is
# kept literally, as urllib.parse.unquote (redis-py) keeps it - so the probe
# and the service read the same password from the same URL. `printf -v`, not
# `$(...)`, which would strip a decoded trailing newline.
DECODED=""
url_decode() {
  local s="$1" hex c
  DECODED=""
  while [[ "${s}" == *%* ]]; do
    DECODED+="${s%%\%*}"
    s="${s#*\%}"
    hex="${s:0:2}"
    if [[ "${hex}" =~ ^[0-9A-Fa-f]{2}$ ]]; then
      printf -v c '%b' "\\x${hex}"
      DECODED+="${c}"
      s="${s:2}"
    else
      DECODED+="%"
    fi
  done
  DECODED+="${s}"
}

scheme="${URL%%://*}"
case "${scheme}" in
  redis|rediss) ;;
  *)
    # Name the scheme only when it provably is one: with no `://` the
    # "scheme" above is the whole URL, credential and all.
    if [[ "${URL}" == *://* && "${scheme}" =~ ^[A-Za-z][A-Za-z0-9+.-]*$ ]]; then
      echo "check_redis_floor: unsupported ARCHIVER_REDIS_URL scheme '${scheme}://' (want redis:// or" >&2
      echo "check_redis_floor: rediss://) — >=7.0 floor UNVERIFIED, not blocking start" >&2
    else
      echo "check_redis_floor: ARCHIVER_REDIS_URL is not a redis:// or rediss:// URL (value withheld:" >&2
      echo "check_redis_floor: it carries the credential) — >=7.0 floor UNVERIFIED, not blocking start" >&2
    fi
    exit 0
    ;;
esac

rest="${URL#*://}"
HAS_AUTH=0
REDIS_PASS=""
REDIS_USER_ARGS=()
if [[ "${rest}" == *@* ]]; then
  # The LAST '@' ends userinfo (see above): an unencoded '@' in the password survives.
  userinfo="${rest%@*}"
  rest="${rest##*@}"
  HAS_AUTH=1
  if [[ "${userinfo}" == *:* ]]; then
    url_decode "${userinfo%%:*}"
    REDIS_USER_ARGS=(--user "${DECODED}")
    url_decode "${userinfo#*:}"
  else
    url_decode "${userinfo}"
  fi
  REDIS_PASS="${DECODED}"
fi

hostport="${rest%%[/?]*}"
db="${rest#"${hostport}"}"
db="${db#/}"
db="${db%%\?*}"
if [[ "${hostport}" == \[* ]]; then
  host="${hostport#\[}"
  host="${host%%]*}"
  port="${hostport##*]}"
  port="${port#:}"
else
  host="${hostport%%:*}"
  port=""
  [[ "${hostport}" == *:* ]] && port="${hostport#*:}"
fi

REDIS_ARGS=(-h "${host:-127.0.0.1}" -p "${port:-6379}" "${REDIS_USER_ARGS[@]}")
[ -n "${db}" ] && REDIS_ARGS+=(-n "${db}")
[ "${scheme}" = rediss ] && REDIS_ARGS+=(--tls)

# Run "$@" with the password in its environment only. A prefix assignment
# applies to that one command and is inherited through `timeout` to redis-cli.
with_auth() {
  if [ "${HAS_AUTH}" = 1 ]; then
    REDISCLI_AUTH="${REDIS_PASS}" "$@"
  else
    "$@"
  fi
}

# Wrap every probe in `timeout` so this ExecStartPre can never hang archiver
# startup: redis-cli has no connect-timeout flag, and a rediss:// URL against a
# plaintext/unreachable endpoint blocks on the TLS handshake indefinitely. A
# timeout kill yields an empty reply → soft-skip. ARCHIVER_REDIS_FLOOR_TIMEOUT
# (seconds, default 5) bounds each call; tests lower it.
TIMEOUT_SECS="${ARCHIVER_REDIS_FLOOR_TIMEOUT:-5}"
TIMEOUT_BIN="$(command -v timeout || true)"

# Run one redis-cli command against the broker, bounded by the timeout when available.
# Stdout is the raw reply with CRs stripped. Stderr is CAPTURED into PROBE_ERR
# rather than discarded (archiver#195): an authentication rejection and an
# unreachable host both produce an empty reply, and stderr is the only thing
# that tells them apart. Failures still take the same soft path; the difference
# is only in what the operator is told.
# Results land in globals, NOT on stdout, and that is load-bearing: a
# `$(redis_probe ...)` call runs the function in a subshell, so anything it
# assigns - including the stderr this whole change exists to read - is
# discarded when the subshell exits. Callers invoke it as a statement and read
# PROBE_OUT.
ERR_FILE="$(mktemp)"
trap 'rm -f "${ERR_FILE}"' EXIT

PROBE_OUT=""
PROBE_ERR=""
redis_probe() {
  if [ -n "${TIMEOUT_BIN}" ]; then
    PROBE_OUT="$(with_auth "${TIMEOUT_BIN}" "${TIMEOUT_SECS}" redis-cli "${REDIS_ARGS[@]}" "$@" 2>"${ERR_FILE}" | tr -d '\r')"
  else
    PROBE_OUT="$(with_auth redis-cli "${REDIS_ARGS[@]}" "$@" 2>"${ERR_FILE}" | tr -d '\r')"
  fi
  # Unfiltered, deliberately (archiver#253). redis-cli's "password on the
  # command line may not be safe" advisory used to be dropped here because
  # `-u` triggered it on every call. With the password off argv it cannot
  # fire; if it ever does, the password is back on the command line, and that
  # is a regression for the operator to see.
  PROBE_ERR="$(tr -d '\r' < "${ERR_FILE}")"
}

# Quote PROBE_ERR to stderr under a label, prefixing EVERY line: redis-cli's
# stderr can be several lines, and an unprefixed continuation reaches journald
# unlabelled.
quote_probe_err() {
  local line
  while IFS= read -r line; do
    [ -n "${line}" ] && echo "check_redis_floor: $1: ${line}" >&2
  done <<< "${PROBE_ERR}"
}

# Pass on whatever redis-cli said on a probe that otherwise succeeded. Healthy
# probes are silent on stderr, so anything here is news - and discarding it
# would hide the advisory above on exactly the starts that go green.
relay_probe_err() {
  if [ -n "${PROBE_ERR}" ]; then
    quote_probe_err "redis-cli said"
  fi
}

# Classify an empty reply from its stderr. Three answers, because they want
# three different operator responses - and because the message that conflated
# them ran on every start of two services for days while describing the wrong
# system (archiver#195).
#
#   auth        reached the broker, it refused the credential
#   unreachable never got that far
#   unknown     no stderr to go on (a timeout kill leaves none) - say so
#               rather than guess; guessing is what misled last time
probe_failure_kind() {
  case "${PROBE_ERR}" in
    *WRONGPASS*|*NOAUTH*|*NOPERM*|*"invalid username-password"*|*"AUTH failed"*|*"Authentication required"*)
      echo auth ;;
    *"Could not connect"*|*"Connection refused"*|*"onnection timed out"*|\
    *"Name or service not known"*|*"No route to host"*|*"Temporary failure in name resolution"*|\
    *"onnection reset"*|*"Network is unreachable"*)
      echo unreachable ;;
    *)
      echo unknown ;;
  esac
}

# --- 1. Server version floor (blocking) ------------------------------------
# INFO server carries the `redis_version:MAJOR.MINOR.PATCH` line.
redis_probe INFO server
version="$(printf '%s\n' "${PROBE_OUT}" | sed -n 's/^redis_version:\(.*\)$/\1/p')"

if [ -z "${version}" ]; then
  # Whatever the cause, the >=7.0 floor was NOT checked. Say "unverified", never
  # nothing: a guard that is known to be off is a different situation from one
  # assumed to be on, and only the first gets looked at.
  case "$(probe_failure_kind)" in
    auth)
      echo "check_redis_floor: reached the broker but could not authenticate — >=7.0 floor UNVERIFIED" >&2
      quote_probe_err "broker said"
      echo "check_redis_floor: FIRST thing to check is the URL's username, not the password." >&2
      echo "check_redis_floor: 'redis://:PASSWORD@host' authenticates for redis-py and FAILS here —" >&2
      echo "check_redis_floor: redis-cli sends a two-argument AUTH \"\" PASSWORD against a user that" >&2
      echo "check_redis_floor: does not exist. Write 'redis://default:PASSWORD@host' (archiver#195)." >&2
      echo "check_redis_floor: not blocking start — this client and the service's disagree about" >&2
      echo "check_redis_floor: exactly this URL form, so a refusal here is not evidence about it" >&2
      ;;
    unreachable)
      echo "check_redis_floor: broker unreachable — >=7.0 floor UNVERIFIED, not blocking start" >&2
      quote_probe_err "broker said"
      echo "check_redis_floor: the outbox buffers through a broker outage; the publisher will retry" >&2
      ;;
    *)
      echo "check_redis_floor: could not reach or authenticate against the broker (probe timed out?)" >&2
      echo "check_redis_floor: — >=7.0 floor UNVERIFIED, not blocking start" >&2
      relay_probe_err
      ;;
  esac
  exit 0
fi
relay_probe_err

major="${version%%.*}"
if ! [ "${major}" -ge 7 ] 2>/dev/null; then
  echo "check_redis_floor: Redis ${version} is below the >=7.0 change-bus floor" >&2
  echo "check_redis_floor: the consumer path (XAUTOCLAIM/claim_stale_page) requires server >= 7.0" >&2
  exit 1
fi

echo "check_redis_floor: Redis ${version} meets the >=7.0 floor"

# --- 2. Live memory cap (warn only, archiver#128) --------------------------
# Sequencing is intentional: this runs only once the version check has passed, so
# a sub-7.0 broker exits above without the cap ever being read. That is harmless
# while the floor blocks — such a broker cannot serve the producer at all, and a
# cap warning about it would be noise. If the floor is ever relaxed to a warning,
# move this probe above it or the cap check becomes unreachable in that case.
# Read from INFO memory, never `CONFIG GET` (archiver#257): `+config|get` cannot
# be narrowed to one parameter on Redis 7.0, so the grant that serves
# `CONFIG GET maxmemory` also serves `CONFIG GET requirepass`, so broker can revoke
# it (CannObserv/broker#50). INFO needs only `+info`, which the version probe
# above already uses. Same value, same unit (bytes). Anchored on `maxmemory:`,
# so `maxmemory_human:` and `maxmemory_policy:` do not match; redis_probe has
# already stripped the CRs INFO ends its lines with, without which a `0` cap
# would read as `0\r` and the uncapped warning below would never fire.
redis_probe INFO memory
relay_probe_err  # a restricted ACL's NOPERM is the likeliest empty reply
maxmemory="$(printf '%s\n' "${PROBE_OUT}" | sed -n 's/^maxmemory:\(.*\)$/\1/p')"

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
  echo "check_redis_floor: redis-server instead of erroring. The cap is the maxmemory directive in" >&2
  echo "check_redis_floor: CannObserv/broker deploy/redis.conf.broker (authoritative); apply live" >&2
  echo "check_redis_floor: without a restart via: redis-cli CONFIG SET maxmemory <value from that" >&2
  echo "check_redis_floor: file> — CONFIG SET takes the same unit suffixes, so copy it verbatim" >&2
  exit 0
fi

echo "check_redis_floor: broker maxmemory is ${maxmemory} bytes (capped)"
exit 0
