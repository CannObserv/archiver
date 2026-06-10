#!/usr/bin/env bash
# Regenerate clients/watcher-python/src/watcher_client/generated/ from the
# Watcher service's OpenAPI schema. Idempotent — safe to run repeatedly.
#
# Requires: Watcher running on http://localhost:8000
# Env: WATCHER_API_KEY (used for authenticated endpoints; openapi.json is public)
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SDK_DIR="${REPO_ROOT}/clients/watcher-python"
GEN_DIR="${SDK_DIR}/src/watcher_client/generated"

cd "${REPO_ROOT}"
TMP_SPEC="$(mktemp -t watcher-openapi-XXXXXX.json)"
trap 'rm -f "${TMP_SPEC}"' EXIT

curl -sf http://localhost:8000/openapi.json -o "${TMP_SPEC}"

cd "${SDK_DIR}"
rm -rf "${GEN_DIR}"
uv run openapi-python-client generate \
    --path "${TMP_SPEC}" \
    --meta none \
    --output-path "${GEN_DIR}" \
    --overwrite

uv run ruff format "${GEN_DIR}" || true   # cosmetic; don't fail regen on format diffs
echo "Regenerated: ${GEN_DIR}"
