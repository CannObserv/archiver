#!/usr/bin/env bash
# Best-effort fast-forward of the deploy clone's CLEAN main checkout to
# origin/main (#70, CR round 3 finding 15).
#
# Run by the watcher-live-drift.service `ExecStartPre` BEFORE
# watcher_live_drift_pr.sh, so the live-drift wrapper never mutates the clone it
# is executing from (a ff that rewrote the long-running wrapper mid-read could
# feed bash stale offsets). Here the fast-forward is the LAST action and the
# script is short enough to be fully buffered, so a ff that rewrites this very
# file cannot corrupt the running shell.
#
# Purpose: keep the checkout current so the detector compares live Watcher
# against origin/main's snapshot, not a stale tree. Safe by construction —
# fast-forwards ONLY a clean checkout of main, never clobbers. Any non-clean /
# detached / non-ff / fetch-failure state just logs and exits 0 (skip); the
# wrapper's step-4 no-op guard still backstops a stale tree.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

log() { printf '[ff-deploy-clone] %s\n' "$*"; }

git fetch --quiet origin main || {
  log "fetch failed; leaving checkout as-is"
  exit 0
}

branch="$(git symbolic-ref --quiet --short HEAD || true)"
if [ "${branch}" != "main" ]; then
  log "not on main (${branch:-detached HEAD}); skipping fast-forward"
  exit 0
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  log "working tree not clean; skipping fast-forward"
  exit 0
fi

# Fast-forward LAST: nothing runs after this, so a self-rewrite is harmless.
# --ff-only never clobbers — a diverged/ahead main just fails and is skipped.
git merge --quiet --ff-only origin/main || log "main not fast-forwardable; leaving as-is"
