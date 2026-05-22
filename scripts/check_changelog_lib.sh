#!/usr/bin/env bash
# Shared changelog-trigger logic.
# Sourced by check_changelog_on_push.sh and test_check_changelog.sh.
#
# A CHANGELOG.md entry is required when any changed file falls under a path
# that represents an externally-observable contract:
#   alembic/versions/   – deployed DB migrations
#   src/api/routes/     – HTTP API surface
#   src/api/schemas/    – Pydantic request/response contract models
#   clients/python/     – archiver-client SDK

# Public — safe to reference from sourcing scripts.
CHANGELOG_TRIGGER_RE='^(alembic/versions/|src/api/routes/|src/api/schemas/|clients/python/)'

# changelog_trigger_paths_changed <newline-separated file list>
# Returns 0 if any file matches the trigger pattern, 1 otherwise.
changelog_trigger_paths_changed() {
    printf '%s\n' "$1" | grep -Eq "$CHANGELOG_TRIGGER_RE"
}
