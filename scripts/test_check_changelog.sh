#!/usr/bin/env bash
# Unit tests for changelog_trigger_paths_changed() in check_changelog_lib.sh.
# Run: bash scripts/test_check_changelog.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/check_changelog_lib.sh"

pass=0
fail=0

assert_triggers() {
    local desc="$1" files="$2"
    if changelog_trigger_paths_changed "$files"; then
        echo "PASS (triggers):     $desc"
        pass=$((pass + 1))
    else
        echo "FAIL (expected trigger, got none): $desc"
        fail=$((fail + 1))
    fi
}

assert_no_trigger() {
    local desc="$1" files="$2"
    if ! changelog_trigger_paths_changed "$files"; then
        echo "PASS (no trigger):   $desc"
        pass=$((pass + 1))
    else
        echo "FAIL (unexpected trigger): $desc"
        fail=$((fail + 1))
    fi
}

# ── Should NOT trigger ────────────────────────────────────────────────────────

assert_no_trigger "dashboard JS fix" \
    "src/dashboard/static/dashboard.js
src/dashboard/templates/base.html"

assert_no_trigger "dashboard route" \
    "src/dashboard/routes/info_items.py"

assert_no_trigger "test-only" \
    "tests/test_info_item.py
tests/api/test_info_items.py"

assert_no_trigger "docs-only" \
    "docs/SKILLS.md
README.md"

assert_no_trigger "CI config" \
    ".github/workflows/ci.yml"

assert_no_trigger "core internals (non-contract)" \
    "src/core/simhash.py
src/core/extractors/html.py"

assert_no_trigger "scripts only" \
    "scripts/dump_openapi.py"

assert_no_trigger "conftest / pyproject root" \
    "conftest.py
pyproject.toml"

# ── Should trigger ────────────────────────────────────────────────────────────

assert_triggers "new alembic migration" \
    "alembic/versions/abc123_add_col.py"

assert_triggers "existing alembic migration edited" \
    "alembic/versions/0001_baseline.py"

assert_triggers "api route change" \
    "src/api/routes/info_items.py"

assert_triggers "new api route file" \
    "src/api/routes/rep_specs.py"

assert_triggers "sdk source change" \
    "clients/python/src/archiver_client/api/info_items.py"

assert_triggers "sdk pyproject.toml bump" \
    "clients/python/pyproject.toml"

assert_triggers "mixed: api route + dashboard" \
    "src/api/routes/info_items.py
src/dashboard/static/dashboard.js"

assert_triggers "alembic + CHANGELOG already present" \
    "alembic/versions/abc123.py
CHANGELOG.md"

assert_triggers "api schema change" \
    "src/api/schemas/info_item.py"

assert_triggers "api schema — new file" \
    "src/api/schemas/rep_spec.py"

assert_triggers "mixed: schema + dashboard (schema wins)" \
    "src/api/schemas/source_revision.py
src/dashboard/static/dashboard.js"

# Prefix guard: src/api_something should NOT match src/api/routes/ or src/api/schemas/
assert_no_trigger "path prefix false-positive guard" \
    "src/api_integration_tests/helper.py"

# Alembic root files (env.py, script.py.mako) are NOT in versions/ and must NOT trigger
assert_no_trigger "alembic/env.py (not a migration)" \
    "alembic/env.py"

assert_no_trigger "alembic/script.py.mako (not a migration)" \
    "alembic/script.py.mako"

# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "Results: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
