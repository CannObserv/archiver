#!/usr/bin/env bash
# Remediate watcher_client snapshot drift vs LIVE Watcher by opening a PR (Layer C, #70).
#
# Runs ON THE VM (systemd timer, deploy/watcher-live-drift.{service,timer}) — NOT a
# GitHub runner — so it can reach Watcher at http://localhost:8000 with no public
# URL / hairpin-NAT / runner-uptime coupling (see CannObserv/archiver#70).
#
# Flow:
#   1. scripts/check_watcher_live_drift.py detects whether the committed snapshot
#      (clients/watcher-python/watcher-openapi.json) is stale vs live Watcher.
#   2. No drift (exit 0) or Watcher unreachable (exit 3) -> log + exit 0 (non-blocking).
#   3. Drift (exit 1) -> regenerate snapshot + tree via regen.sh in an isolated git
#      worktree off origin/main, and open a PR. The PR runs the hermetic #68 gate
#      (a no-op post-regen) + the test suite, so real upstream drift becomes a
#      reviewable PR instead of a prod incident (the #66 failure mode).
#
# De-dup: the branch is keyed on the live spec's SHA-256, so re-runs while a PR is
# open are no-ops (one PR per distinct upstream shape).
#
# A watcher_client regen touches only clients/watcher-python/** — outside the
# changelog CI trigger (clients/python/ only) — so the PR needs no CHANGELOG entry.
#
# Usage: watcher_live_drift_pr.sh [--dry-run]   (--dry-run: prepare commit, no push/PR)
# Requires on the VM: uv, git, gh (GH_TOKEN), and Watcher live on localhost:8000.
set -euo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

# Load env (GH_TOKEN for gh; any git credential helpers). Later file overrides earlier.
set -a
# shellcheck disable=SC1091
[ -f /etc/archiver/.env ] && . /etc/archiver/.env
# shellcheck disable=SC1091
[ -f "${REPO_ROOT}/.env" ] && . "${REPO_ROOT}/.env"
set +a

log() { printf '[watcher-live-drift] %s\n' "$*"; }

# Single EXIT trap cleans up everything created below, on every exit path.
err_file="$(mktemp -t watcher-live-drift-err-XXXXXX)"
worktree_base=""
cleanup() {
  [ -n "${worktree_base}" ] && {
    git worktree remove --force "${worktree_base}/wt" 2>/dev/null || true
    rm -rf "${worktree_base}"
  }
  rm -f "${err_file}"
}
trap cleanup EXIT

# 1. Detect (stdlib-only; --no-project skips the root sync). Toggle set +e only
#    around the capture so a non-zero (drift) exit doesn't abort before we read rc.
set +e
detector_out="$(uv run --no-project python scripts/check_watcher_live_drift.py 2>"${err_file}")"
rc=$?
set -e
cat "${err_file}" >&2 || true

case "${rc}" in
  0) log "no drift; committed snapshot matches live Watcher"; exit 0 ;;
  3) log "Watcher unreachable / non-JSON; skipping run (non-blocking)"; exit 0 ;;
  1) : ;;  # drift -> remediate below
  2) log "detector internal error (exit 2; see stderr above); aborting"; exit 1 ;;
  *) log "detector failed unexpectedly (exit ${rc}); aborting"; exit 1 ;;
esac

sha="$(printf '%s\n' "${detector_out}" | sed -n 's/^SPEC_SHA256=//p')"
[ -n "${sha}" ] || { log "drift reported but no SPEC_SHA256 in detector output; aborting"; exit 1; }
branch="chore/watcher-openapi-drift-${sha:0:12}"
log "drift detected; live spec sha ${sha:0:12}; target branch ${branch}"

# 2. De-dup: one PR per distinct upstream shape. Capture on its own line so a
#    failed gh call aborts (set -e) instead of being read as "no open PR".
existing_pr="$(gh pr list --head "${branch}" --state open --json number --jq '.[].number')"
if [ -n "${existing_pr}" ]; then
  log "open PR already exists for ${branch} (#$(printf '%s' "${existing_pr}" | head -1)); nothing to do"
  exit 0
fi

# 3. Regenerate in an isolated worktree off the latest origin/main so the deploy
#    clone's working tree is never disturbed. --detach (not -b): a named branch
#    survives `worktree remove`, so re-runs would collide / leak refs; we create
#    the remote branch only at push time (HEAD:refs/heads/<branch>).
git fetch --quiet origin main
worktree_base="$(mktemp -d -t watcher-live-drift-XXXXXX)"
worktree="${worktree_base}/wt"
git worktree add --quiet --detach "${worktree}" origin/main

# regen.sh re-fetches localhost:8000 and writes snapshot + generated tree in lockstep.
( cd "${worktree}" && bash clients/watcher-python/scripts/regen.sh )

# 4. Stage only the watcher_client artifacts; bail if the regen was a no-op.
git -C "${worktree}" add \
  clients/watcher-python/watcher-openapi.json \
  clients/watcher-python/src/watcher_client/generated
if git -C "${worktree}" diff --cached --quiet; then
  log "regen produced no committable change; skipping"
  exit 0
fi

git -C "${worktree}" commit --quiet \
  -m "#70 chore: refresh watcher_client from live Watcher OpenAPI (drift)" \
  -m "Live Watcher /openapi.json drifted from the committed watcher-openapi.json snapshot. Regenerated snapshot + generated tree via regen.sh (automated by scripts/watcher_live_drift_pr.sh). Merging re-syncs the vendored client and closes the #66 staleness gap."

if [ "${DRY_RUN}" = "1" ]; then
  log "dry-run: prepared commit on ${branch}; NOT pushing / opening PR"
  git -C "${worktree}" --no-pager show --stat HEAD
  exit 0
fi

# Push detached HEAD straight to a new remote branch — no local branch ref to leak.
git -C "${worktree}" push --quiet origin "HEAD:refs/heads/${branch}"
gh pr create --base main --head "${branch}" \
  --title "chore: refresh watcher_client from live Watcher OpenAPI drift" \
  --body "$(cat <<'BODY'
Automated by the Layer C live-drift timer (`scripts/watcher_live_drift_pr.sh`, #70).

Live Watcher `/openapi.json` drifted from the committed
`clients/watcher-python/watcher-openapi.json` snapshot — the #66 failure mode the
hermetic #68 gate cannot see. `regen.sh` refreshed the snapshot + generated tree
in lockstep.

**Review:** confirm the OpenAPI diff is an intended Watcher change, then merge to
re-sync the vendored `watcher_client`. The `client-drift` gate is a no-op
post-regen; the test suite covers shape-breaking changes. No CHANGELOG entry
required (watcher_client is outside the changelog trigger).
BODY
)"
log "opened PR for ${branch}"
