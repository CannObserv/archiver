#!/usr/bin/env bash
# Pre-push guard: require CHANGELOG.md when a push touches a contract-visible
# path (alembic migrations, API routes, API schemas, SDK).
#
# Two invocation paths, because the hook has two callers:
#
#   1. pre-commit (how it actually runs, via .pre-commit-config.yaml
#      stages: [pre-push]) — pre-commit consumes git's stdin itself and hands
#      the range to the hook as PRE_COMMIT_FROM_REF / PRE_COMMIT_TO_REF. A
#      stdin-only reader sees EOF immediately and exits 0 unconditionally; the
#      guard was inert this way until archiver#82 CR round 8, which is how a
#      migration reached CI without a CHANGELOG entry.
#   2. git directly (`.git/hooks/pre-push`, or a manual pipe) — one line per
#      ref on stdin: "<local_ref> <local_sha> <remote_ref> <remote_sha>".
#
# The env range wins when present: pre-commit is the authoritative caller, and
# it is the path that runs on a real `git push`. Both paths are filtered to
# main — the env path via PRE_COMMIT_REMOTE_BRANCH, the stdin path via the
# remote ref field.
#
# Bypass with `git push --no-verify` if the push is genuinely internal-only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/check_changelog_lib.sh"

ZERO=0000000000000000000000000000000000000000

# check_range <base_sha> <head_sha> — exits 1 with a diagnostic if the range
# touches a contract-visible path without also touching CHANGELOG.md.
check_range() {
  local base="$1" head="$2"
  local range="${base}..${head}"
  local changed_files
  changed_files=$(git diff --name-only "$range" 2>/dev/null || true)
  [[ -n "$changed_files" ]] || return 0

  # Explicit `if` rather than a `&& return` chain specifically because this
  # branch emits the diagnostic: a premature exit here would fail the push with
  # no explanation of why. The one-line `[[ … ]] && exit` / `|| continue` guards
  # elsewhere in this file are fine — they only skip, never print.
  if changelog_trigger_paths_changed "$changed_files" &&
     ! printf '%s\n' "$changed_files" | grep -qx 'CHANGELOG.md'; then
    cat >&2 <<EOF
ERROR: pushing a change that touches a contract-visible path
       without a CHANGELOG.md entry.
Range: $range
Trigger paths matched (alembic/versions/, src/api/routes/, src/api/schemas/, clients/python/):
$(printf '%s\n' "$changed_files" | grep -E "$CHANGELOG_TRIGGER_RE" | sed 's/^/  /')

Update CHANGELOG.md, or push with --no-verify if this is genuinely internal.
EOF
    exit 1
  fi
}

# Path 1 — pre-commit supplies the range via env, plus PRE_COMMIT_REMOTE_BRANCH
# naming the ref being pushed. Filter on main so this path matches the stdin
# path's contract: a feature branch carrying a migration is not gated, because
# forcing --no-verify on routine WIP pushes is how a guard becomes habitually
# bypassed. If the remote-branch signal is absent, check anyway — this guard
# already failed silent once (archiver#82 CR round 8), so the safe default when
# a signal is missing is to check, not to skip.
if [[ -n "${PRE_COMMIT_FROM_REF:-}" && -n "${PRE_COMMIT_TO_REF:-}" ]]; then
  if [[ -n "${PRE_COMMIT_REMOTE_BRANCH:-}" &&
        "$PRE_COMMIT_REMOTE_BRANCH" != "refs/heads/main" &&
        "$PRE_COMMIT_REMOTE_BRANCH" != "main" ]]; then
    exit 0
  fi
  [[ "$PRE_COMMIT_TO_REF" == "$ZERO" ]] && exit 0      # branch delete
  if [[ "$PRE_COMMIT_FROM_REF" == "$ZERO" ]]; then
    echo "new ref; skipping changelog check" >&2
    exit 0
  fi
  check_range "$PRE_COMMIT_FROM_REF" "$PRE_COMMIT_TO_REF"
  exit 0
fi

# Path 2 — git's native pre-push stdin protocol. Only main is inspected here,
# since the ref name is available.
while read -r _local_ref local_sha remote_ref remote_sha; do
  [[ "$remote_ref" == "refs/heads/main" ]] || continue
  [[ "$local_sha"  == "$ZERO" ]] && continue           # branch delete

  if [[ "$remote_sha" == "$ZERO" ]]; then
    echo "new ref to refs/heads/main; skipping changelog check" >&2
    continue
  fi

  check_range "$remote_sha" "$local_sha"
done

exit 0
