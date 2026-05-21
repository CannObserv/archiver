#!/usr/bin/env bash
# Pre-push guard: require CHANGELOG.md when pushing to main touches a
# contract-visible path (alembic migrations, API routes, SDK).
#
# Wired via .pre-commit-config.yaml (stages: [pre-push]). Git pipes one line
# per ref being pushed on stdin: "<local_ref> <local_sha> <remote_ref>
# <remote_sha>". Only refs targeting refs/heads/main are inspected.
# Bypass with `git push --no-verify` if the push is genuinely internal-only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/check_changelog_lib.sh"

ZERO=0000000000000000000000000000000000000000

while read -r local_ref local_sha remote_ref remote_sha; do
  [[ "$remote_ref" == "refs/heads/main" ]] || continue
  [[ "$local_sha"  == "$ZERO" ]] && continue          # branch delete

  if [[ "$remote_sha" == "$ZERO" ]]; then
    echo "new ref to refs/heads/main; skipping changelog check" >&2
    continue
  fi

  range="${remote_sha}..${local_sha}"
  changed_files=$(git diff --name-only "$range" 2>/dev/null || true)
  [[ -n "$changed_files" ]] || continue

  if changelog_trigger_paths_changed "$changed_files"; then
    if ! printf '%s\n' "$changed_files" | grep -qx 'CHANGELOG.md'; then
      cat >&2 <<EOF
ERROR: pushing to main a change that touches a contract-visible path
       without a CHANGELOG.md entry.
Range: $range
Trigger paths matched (alembic/versions/, src/api/routes/, clients/python/):
$(printf '%s\n' "$changed_files" | grep -E "$_CHANGELOG_TRIGGER_RE" | sed 's/^/  /')

Update CHANGELOG.md, or push with --no-verify if this is genuinely internal.
EOF
      exit 1
    fi
  fi
done

exit 0
