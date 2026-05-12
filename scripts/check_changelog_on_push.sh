#!/usr/bin/env bash
# Pre-push guard: require CHANGELOG.md when pushing feat/fix commits to main.
#
# Wired via .pre-commit-config.yaml (stages: [pre-push]). Git pipes one line per
# ref being pushed on stdin: "<local_ref> <local_sha> <remote_ref> <remote_sha>".
# Only refs targeting refs/heads/main are inspected. Commit subjects matching
# `[#<n> ]feat|fix[(scope)]:` require CHANGELOG.md to be touched in the same
# range. Bypass with `git push --no-verify` if genuinely trivial.
set -euo pipefail

ZERO=0000000000000000000000000000000000000000
# Accepts: feat:, fix:, feat(scope):, fix(scope):, feat!:, fix!:,
# feat(scope)!:, and the same with an optional `#<n> ` issue prefix.
PATTERN='^(#[0-9]+ )?(feat|fix)(\([^)]+\))?!?:'

while read -r local_ref local_sha remote_ref remote_sha; do
  [[ "$remote_ref" == "refs/heads/main" ]] || continue
  [[ "$local_sha"  == "$ZERO" ]] && continue          # branch delete
  if [[ "$remote_sha" == "$ZERO" ]]; then
    echo "new ref to refs/heads/main; skipping changelog check" >&2
    continue
  fi

  range="${remote_sha}..${local_sha}"

  msgs=$(git log --format=%s "$range" 2>/dev/null || true)
  [[ -n "$msgs" ]] || continue

  if echo "$msgs" | grep -Eq "$PATTERN"; then
    if ! git diff --name-only "$range" | grep -qx 'CHANGELOG.md'; then
      offenders=$(echo "$msgs" | grep -E "$PATTERN" | sed 's/^/  - /')
      cat >&2 <<EOF
ERROR: pushing feat/fix commit(s) to main without CHANGELOG.md update.
Range: $range
Offending commit subjects:
$offenders
Update CHANGELOG.md (or push with --no-verify if genuinely internal/test/docs only).
EOF
      exit 1
    fi
  fi
done

exit 0
