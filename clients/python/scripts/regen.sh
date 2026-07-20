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
# Use this when the Archiver legitimately changes shape. Idempotent — safe to
# re-run. Offline: the spec comes from the FastAPI app object, not a server.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SDK_DIR="${REPO_ROOT}/clients/python"
GEN_DIR="${SDK_DIR}/src/archiver_client/generated"
SNAPSHOT="${SDK_DIR}/archiver-openapi.json"

# Dump the canonical spec straight into the committed snapshot.
# dump_openapi.py already canonicalizes (json.dumps indent=2, sort_keys=True);
# no second normalization pass needed. sort_keys is safe here (unlike the
# watcher regen, which preserves upstream order): the snapshot has ALWAYS been
# sorted for this SDK, so the generated tree's model-field order is already
# derived from the sorted spec.
cd "${REPO_ROOT}"
uv run python scripts/dump_openapi.py > "${SNAPSHOT}"

cd "${SDK_DIR}"
rm -rf "${GEN_DIR}"
uv run openapi-python-client generate \
    --path "${SNAPSHOT}" \
    --meta none \
    --output-path "${GEN_DIR}" \
    --overwrite

uv run ruff format "${GEN_DIR}" || true   # cosmetic; don't fail regen on format diffs
echo "Regenerated: ${SNAPSHOT}"
echo "Regenerated: ${GEN_DIR}"
