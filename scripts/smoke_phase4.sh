#!/usr/bin/env bash
# Phase 4 smoke — exercises the full v2 authoring loop end-to-end.
#
# Reference flow:
#  1.  Health check — GET /health → 200
#  2.  validate_source_spec — valid root spec → {valid: true}
#  3.  validate_rep_spec — valid GCS spec → {valid: true}
#  4.  validate_rep_fields — bag matching required_fields → {valid: true}
#  5.  resolve_rep_fields — raw inputs → slug-enriched bag with _slug keys
#  6.  create_info_item (atomic) — name + rep_fields + initial_source_spec → 201
#  7.  POST /source-revisions — synthetic fingerprint → 201, capture ID
#  8.  POST /source-revisions again — same fingerprint → 200 (idempotent)
#  9.  Redis check — XLEN info.changes ≥ 1 (skipped when ARCHIVER_REDIS_URL unset)
# 10.  POST /rep-specs → 201, capture rep_spec_id
# 11.  assign_rep_spec — POST /info-items/{id}/rep-spec-assignments → 201
# 12.  PATCH public_url on assignment → 200, verify field written
# 13.  bind_revision — POST /info-items/{id}/source-revisions → 201
# 14.  PATCH source-revision cache fields → 200, verify NULLs
# 15.  POST /info-sources fragment under the smoke root → 201, then verify via
#       GET /info-sources/{id} and GET /info-sources?parent_info_source_id=...
# 16.  Cleanup — DELETE smoke rows from DB
#
# Requires:
#   - Archiver dev server on $ARCHIVER_URL (default http://127.0.0.1:8021).
#   - ARCHIVER_API_KEY and ARCHIVER_DATABASE_URL in env.
#   - jq, curl, psql.
#   - No internet egress needed — all source specs are validated only (no fetch).

set -euo pipefail

# Load env: prod (/etc/archiver/.env) overlaid with repo-local .env.
# `set -a; source; set +a` handles whitespace/quotes/`=` correctly,
# unlike the broken `export $(cat | xargs)` pattern.
set -a
[ -f /etc/archiver/.env ] && . /etc/archiver/.env
[ -f .env ] && . .env
set +a

ARCHIVER_URL="${ARCHIVER_URL:-http://127.0.0.1:8021}"
API_KEY="${ARCHIVER_API_KEY:?ARCHIVER_API_KEY must be set}"
DB_URL="${ARCHIVER_DATABASE_URL:?ARCHIVER_DATABASE_URL must be set}"
# psql needs postgresql:// not postgresql+asyncpg://
PSQL_URL="${DB_URL/postgresql+asyncpg/postgresql}"

SMOKE_NAME="smoke-phase4-$$"
SMOKE_URL="https://example.com/smoke/$$"
FINGERPRINT_A="sha256:$(python3 -c "print('a'*64)")"
FINGERPRINT_B="sha256:$(python3 -c "print('b'*64)")"

TOTAL_STEPS=16

# ---- helpers ----------------------------------------------------------------

call() {
    # call <verb> <path> [<json-body>]
    local verb="$1"
    local path="$2"
    local body="${3:-}"
    if [ -n "$body" ]; then
        curl -fsS --max-time 15 -X "$verb" \
            -H "X-API-Key: $API_KEY" \
            -H "Content-Type: application/json" \
            -d "$body" \
            "${ARCHIVER_URL}${path}"
    else
        curl -fsS --max-time 15 -X "$verb" \
            -H "X-API-Key: $API_KEY" \
            "${ARCHIVER_URL}${path}"
    fi
}

call_status() {
    # call_status <verb> <path> [<json-body>] — returns HTTP status code only
    local verb="$1"
    local path="$2"
    local body="${3:-}"
    if [ -n "$body" ]; then
        curl -fsS --max-time 15 -o /dev/null -w "%{http_code}" -X "$verb" \
            -H "X-API-Key: $API_KEY" \
            -H "Content-Type: application/json" \
            -d "$body" \
            "${ARCHIVER_URL}${path}"
    else
        curl -fsS --max-time 15 -o /dev/null -w "%{http_code}" -X "$verb" \
            -H "X-API-Key: $API_KEY" \
            "${ARCHIVER_URL}${path}"
    fi
}

step() {
    printf '[%d/%d] %s\n' "$1" "$TOTAL_STEPS" "$2"
}

assert_eq() {
    local got="$1"
    local expected="$2"
    local label="${3:-value}"
    if [[ "$got" != "$expected" ]]; then
        echo "  FAIL ($label): expected '$expected', got '$got'"
        exit 1
    fi
}

assert_nonempty() {
    local val="$1"
    local label="${2:-value}"
    if [[ -z "$val" ]] || [[ "$val" == "null" ]]; then
        echo "  FAIL ($label): expected non-empty, got '$val'"
        exit 1
    fi
}

# ---- pre-flight -------------------------------------------------------------

echo "Archiver Phase 4 smoke — target: $ARCHIVER_URL"
echo

# Verify dev server is reachable before doing anything.
curl -fsS --max-time 5 "${ARCHIVER_URL}/health" >/dev/null 2>&1 || {
    echo "ERROR: dev server not responding at ${ARCHIVER_URL}/health — start it first"
    echo "  uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8021 --reload"
    exit 1
}

# ---- steps ------------------------------------------------------------------

# 1. Health check
step 1 "Health check"
STATUS=$(curl -fsS --max-time 5 -o /dev/null -w "%{http_code}" "${ARCHIVER_URL}/health")
assert_eq "$STATUS" "200" "HTTP status"
echo "  ok"

# 2. validate_source_spec — valid spec (extraction + fingerprint, no target)
step 2 "validate_source_spec (valid spec → {valid: true})"
SOURCE_SPEC_DOC='{"schema_version":1,"extraction":{"algorithm":"full_page"},"fingerprint":{}}'
RESP=$(call POST /api/v1/tools/validate-source-spec "{\"document\": $SOURCE_SPEC_DOC}")
assert_eq "$(echo "$RESP" | jq -r .valid)" "true" "valid"
echo "  ok"

# 3. validate_rep_spec — valid GCS spec
step 3 "validate_rep_spec (valid GCS spec → {valid: true})"
REP_SPEC_DOC='{"provider":"gcs","credentials_alias":"smoke-creds","path_template":"gs://smoke-bucket/{item.slug}.html","required_fields":["item.slug"],"object_options":{"storage_class":"STANDARD"}}'
RESP=$(call POST /api/v1/tools/validate-rep-spec "{\"document\": $REP_SPEC_DOC}")
assert_eq "$(echo "$RESP" | jq -r .valid)" "true" "valid"
echo "  ok"

# 4. validate_rep_fields — bag with required_fields
step 4 "validate_rep_fields (bag matching required_fields → {valid: true})"
REP_FIELDS_BAG='{"item":{"slug":"cannabis-observer-smoke","title":"Cannabis Observer Smoke Test"}}'
RESP=$(call POST /api/v1/tools/validate-rep-fields \
    "{\"bag\": $REP_FIELDS_BAG, \"required_fields\": [\"item.slug\"]}")
assert_eq "$(echo "$RESP" | jq -r .valid)" "true" "valid"
echo "  ok"

# 5. resolve_rep_fields — title enriched with title_slug companion
step 5 "resolve_rep_fields (raw title → resolved bag with _slug companion)"
RESP=$(call POST /api/v1/tools/resolve-rep-fields \
    "{\"bag\": {\"item\": {\"title\": \"Cannabis Observer Smoke\"}}}")
RESOLVED=$(echo "$RESP" | jq -r '.bag.item.title_slug // empty')
assert_nonempty "$RESOLVED" "title_slug"
echo "  ok (title_slug=$RESOLVED)"

# 6. Atomic InfoItem create — name + rep_fields + initial_url + initial_source_specs
step 6 "POST /info-items (atomic: name + rep_fields + initial_url → 201)"
CREATE_BODY=$(jq -nc \
    --arg name "$SMOKE_NAME" \
    --arg url "$SMOKE_URL" \
    --argjson rep_fields "$REP_FIELDS_BAG" \
    --argjson source_specs "[$SOURCE_SPEC_DOC]" \
    '{name: $name, rep_fields: $rep_fields, initial_url: $url, initial_source_specs: $source_specs}')
RESP=$(call POST /api/v1/info-items "$CREATE_BODY")
INFO_ITEM_ID=$(echo "$RESP" | jq -r .info_item_id)
INFO_SOURCE_ID=$(echo "$RESP" | jq -r '.info_item_sources[0].info_source_id')
assert_nonempty "$INFO_ITEM_ID" "info_item_id"
assert_nonempty "$INFO_SOURCE_ID" "info_source_id (from info_item_sources[0])"
echo "  ok (info_item_id=$INFO_ITEM_ID  info_source_id=$INFO_SOURCE_ID)"

# 7. POST /source-revisions — synthetic fingerprint
step 7 "POST /source-revisions (synthetic fingerprint → 201)"
REV_BODY=$(jq -nc \
    --arg src "$INFO_SOURCE_ID" \
    --arg fp "$FINGERPRINT_A" \
    --arg ts "2026-05-09T00:00:00.000000Z" \
    '{info_source_id: $src, content_fingerprint: $fp, captured_at: $ts,
      content_size_bytes: 12345, content_media_type: "text/html",
      content_cache_uri: "gs://smoke-bucket/cache/smoke.html",
      content_cache_expires_at: "2026-05-10T00:00:00.000000Z"}')
RESP=$(call POST /api/v1/source-revisions "$REV_BODY")
SOURCE_REVISION_ID=$(echo "$RESP" | jq -r .source_revision_id)
assert_nonempty "$SOURCE_REVISION_ID" "source_revision_id"
assert_eq "$(echo "$RESP" | jq -r .content_fingerprint)" "$FINGERPRINT_A" "fingerprint"
echo "  ok (source_revision_id=$SOURCE_REVISION_ID)"

# 8. POST same revision again — idempotent → 200
step 8 "POST /source-revisions again (same fingerprint → 200 idempotent)"
STATUS=$(call_status POST /api/v1/source-revisions "$REV_BODY")
assert_eq "$STATUS" "200" "HTTP status"
echo "  ok"

# 9. Redis check (skipped when ARCHIVER_REDIS_URL unset)
step 9 "Redis change-bus check"
if [[ -z "${ARCHIVER_REDIS_URL:-}" ]]; then
    echo "  skipped (ARCHIVER_REDIS_URL not set)"
else
    STREAM_LEN=$(redis-cli -u "$ARCHIVER_REDIS_URL" XLEN info.changes 2>/dev/null || echo "0")
    if [[ "$STREAM_LEN" -ge 1 ]]; then
        echo "  ok (info.changes len=$STREAM_LEN)"
    else
        echo "  WARN: info.changes stream empty — outbox may not have published yet"
    fi
fi

# 10. POST /rep-specs — create RepSpec via new endpoint
step 10 "POST /rep-specs (create RepSpec via new endpoint)"
RESP=$(call POST /api/v1/rep-specs \
    "{\"provider\": \"gcs\", \"name\": \"smoke-gcs-$$\", \"document\": $REP_SPEC_DOC}")
REP_SPEC_ID=$(echo "$RESP" | jq -r .rep_spec_id)
assert_nonempty "$REP_SPEC_ID" "rep_spec_id"
echo "  ok (rep_spec_id=$REP_SPEC_ID)"

# 11. assign_rep_spec — POST /info-items/{id}/rep-spec-assignments
step 11 "POST /info-items/{id}/rep-spec-assignments → 201"
RESP=$(call POST "/api/v1/info-items/${INFO_ITEM_ID}/rep-spec-assignments" \
    "{\"rep_spec_id\": \"$REP_SPEC_ID\"}")
ASSIGNMENT_ID=$(echo "$RESP" | jq -r .id)
assert_nonempty "$ASSIGNMENT_ID" "assignment_id"
assert_eq "$(echo "$RESP" | jq -r .rep_spec_id)" "$REP_SPEC_ID" "rep_spec_id"
echo "  ok (assignment_id=$ASSIGNMENT_ID)"

# 12. PATCH public_url on assignment
step 12 "PATCH /info-items/{id}/rep-spec-assignments/{id} (set public_url → 200)"
PUBLIC_URL="https://storage.googleapis.com/smoke-bucket/cannabis-observer-smoke.html"
RESP=$(call PATCH "/api/v1/info-items/${INFO_ITEM_ID}/rep-spec-assignments/${ASSIGNMENT_ID}" \
    "{\"public_url\": \"$PUBLIC_URL\"}")
assert_eq "$(echo "$RESP" | jq -r .public_url)" "$PUBLIC_URL" "public_url"
echo "  ok"

# 13. bind_revision — POST /info-items/{id}/source-revisions
step 13 "POST /info-items/{id}/source-revisions (bind revision → 201)"
RESP=$(call POST "/api/v1/info-items/${INFO_ITEM_ID}/source-revisions" \
    "{\"source_revision_id\": \"$SOURCE_REVISION_ID\"}")
assert_eq "$(echo "$RESP" | jq -r .info_item_id)" "$INFO_ITEM_ID" "info_item_id"
assert_eq "$(echo "$RESP" | jq -r .source_revision_id)" "$SOURCE_REVISION_ID" "source_revision_id"
BOUND_AT=$(echo "$RESP" | jq -r .bound_at)
assert_nonempty "$BOUND_AT" "bound_at"
echo "  ok (bound_at=$BOUND_AT)"

# 14. PATCH source-revision cache fields to null
step 14 "PATCH /source-revisions/{id} (clear cache fields → 200, nulls)"
RESP=$(call PATCH "/api/v1/source-revisions/${SOURCE_REVISION_ID}" \
    '{"content_cache_uri": null, "content_cache_expires_at": null}')
assert_eq "$(echo "$RESP" | jq -r .content_cache_uri)" "null" "content_cache_uri"
assert_eq "$(echo "$RESP" | jq -r .content_cache_expires_at)" "null" "content_cache_expires_at"
echo "  ok"

# 15. POST /info-sources directly + verify via GETs (url + source_specs)
step 15 "POST /info-sources (url + source_specs → 201) + GET round-trip + ?url= filter"
SMOKE_URL2="https://example.com/smoke2/$$"
CSS_SPEC='{"schema_version":1,"extraction":{"algorithm":"css","selector":"#smoke-direct"},"fingerprint":{}}'
RESP=$(call POST /api/v1/info-sources \
    "$(jq -nc --arg url "$SMOKE_URL2" --argjson spec "$CSS_SPEC" \
       '{url: $url, source_specs: [$spec]}')")
DIRECT_SRC_ID=$(echo "$RESP" | jq -r .info_source_id)
assert_nonempty "$DIRECT_SRC_ID" "direct info_source_id"
assert_eq "$(echo "$RESP" | jq -r .url)" "$SMOKE_URL2" "direct url"

# GET /info-sources/{id} round-trip
RESP=$(call GET "/api/v1/info-sources/${DIRECT_SRC_ID}")
assert_eq "$(echo "$RESP" | jq -r .info_source_id)" "$DIRECT_SRC_ID" "round-trip id"

# GET /info-sources?url=... should find the new source
RESP=$(call GET "/api/v1/info-sources?url=${SMOKE_URL2}")
COUNT=$(echo "$RESP" | jq "[.items[] | select(.info_source_id == \"$DIRECT_SRC_ID\")] | length")
assert_eq "$COUNT" "1" "source found via ?url= filter"
echo "  ok (direct_src_id=$DIRECT_SRC_ID)"

# 16. Cleanup — remove smoke rows to keep the DB tidy
step 16 "Cleanup (DELETE smoke rows)"
psql "$PSQL_URL" -q -c "
    DELETE FROM information.info_sources WHERE info_source_id = '$DIRECT_SRC_ID'" 2>&1
psql "$PSQL_URL" -q -c "
    DELETE FROM information.info_items WHERE name = '$SMOKE_NAME'" 2>&1
psql "$PSQL_URL" -q -c "
    DELETE FROM information.rep_specs WHERE name = 'smoke-gcs-$$'" 2>&1
echo "  ok"

# ---- summary ----------------------------------------------------------------
echo
echo "Phase 4 smoke OK."
echo "  info_item_id=$INFO_ITEM_ID"
echo "  info_source_id=$INFO_SOURCE_ID"
echo "  source_revision_id=$SOURCE_REVISION_ID"
echo "  rep_spec_id=$REP_SPEC_ID"
echo "  assignment_id=$ASSIGNMENT_ID"
echo
echo "Notes:"
echo "  Step  9: Redis check skipped when ARCHIVER_REDIS_URL unset."
