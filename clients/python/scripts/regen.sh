#!/usr/bin/env bash
# Regenerate the archiver_client SDK from the Archiver service's OpenAPI.
#
# Writes BOTH artifacts in lockstep so the CI drift gate
# (scripts/check_client_drift.py) is a no-op afterward:
#   1. clients/python/archiver-openapi.json  — committed contract-of-record
#      snapshot (canonical dump via scripts/dump_openapi.py: pretty-printed,
#      sorted keys — deterministic across runs).
#   2. clients/python/src/archiver_client/generated/  — regenerated FROM the
#      snapshot (not the raw dump), so the snapshot is authoritative.
#
# The tree is written by the drift gate itself (`--write`), never generated
# here: one code path, so the check and the write cannot disagree (#272).
# A second in-place generate once diverged from the gate over 121 files, because
# the generator's import-fixing hook honours the SDK's lint.exclude (#242) only
# at the real generated/ path. tests/scripts/test_client_regen.py pins this.
#
# Use this when the Archiver legitimately changes shape. Idempotent — safe to
# re-run. Offline: the spec comes from the FastAPI app object, not a server.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SNAPSHOT="${REPO_ROOT}/clients/python/archiver-openapi.json"

# Dump the canonical spec into the committed snapshot.
# dump_openapi.py already canonicalizes (json.dumps indent=2, sort_keys=True);
# no second normalization pass needed. sort_keys is safe here (unlike the
# watcher regen, which preserves upstream order): the snapshot has ALWAYS been
# sorted for this SDK, so the generated tree's model-field order is already
# derived from the sorted spec.
#
# Dumped to a temp file and copied in only on success: redirecting straight
# into the snapshot would truncate the committed contract before a failing dump
# (a broken app import) had written a byte. Copied, not moved, so the
# snapshot keeps its own mode rather than mktemp's 600.
cd "${REPO_ROOT}"
DUMP="$(mktemp)"
trap 'rm -f "${DUMP}"' EXIT
uv run python scripts/dump_openapi.py > "${DUMP}"
cat "${DUMP}" > "${SNAPSHOT}"
echo "Regenerated: ${SNAPSHOT}"

uv run python scripts/check_client_drift.py --write archiver
