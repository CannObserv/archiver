#!/usr/bin/env bash
# Regenerate the watcher_client SDK from the Watcher service's live OpenAPI.
#
# Writes BOTH artifacts in lockstep so the CI drift gate
# (scripts/check_client_drift.py) is a no-op afterward:
#   1. clients/watcher-python/watcher-openapi.json  — committed contract-of-record
#      snapshot (pretty-printed, order-preserving).
#   2. clients/watcher-python/src/watcher_client/generated/  — regenerated FROM
#      the snapshot (not the raw live bytes), so the snapshot is authoritative.
#
# Use this when Watcher legitimately changes shape. Idempotent — safe to re-run.
#
# Requires: Watcher running on http://localhost:8000
# Env: WATCHER_API_KEY (used for authenticated endpoints; openapi.json is public)
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SDK_DIR="${REPO_ROOT}/clients/watcher-python"
GEN_DIR="${SDK_DIR}/src/watcher_client/generated"
SNAPSHOT="${SDK_DIR}/watcher-openapi.json"

cd "${REPO_ROOT}"
TMP_SPEC="$(mktemp -t watcher-openapi-XXXXXX.json)"
trap 'rm -f "${TMP_SPEC}"' EXIT

curl -sf http://localhost:8000/openapi.json -o "${TMP_SPEC}"

# Canonicalize into the committed snapshot: pretty-print, order-preserving.
# NOT sort_keys — openapi-python-client emits model fields in spec property
# order, so sorting would reshape (not just reformat) the generated tree.
uv run --no-project python -c "import json,sys; d=json.load(open(sys.argv[1])); open(sys.argv[2],'w').write(json.dumps(d, indent=2)+'\n')" \
    "${TMP_SPEC}" "${SNAPSHOT}"

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
