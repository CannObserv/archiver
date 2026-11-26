#!/usr/bin/env bash
# install_browser.sh - the Chromium the browser test tier runs (archiver#546).
#
# The build is the lock's, not this script's: `playwright` in pyproject's
# `browser` group pins a Playwright release, and each release names exactly one
# chromium-headless-shell build. Headless shell only - the tier never runs a
# headed browser - plus the ffmpeg build Playwright pairs with it.
#
# One install per host, at Playwright's default (~/.cache/ms-playwright, or
# PLAYWRIGHT_BROWSERS_PATH), shared by every worktree. Idempotent: Playwright
# skips a build that is already complete, so a rerun downloads nothing.
#
# Stale builds: Playwright registers each venv that installs (the cache's
# .links/) and, on every install, deletes the builds no live venv still links
# to. A bump therefore retires the old build at the next run of this script, once
# no worktree venv on the old version remains. --no-remove skips that sweep.
#
# Usage: bash scripts/install_browser.sh [--with-deps] [--no-remove]
#   --with-deps   also apt-install the browser's system libraries (a CI runner;
#                 this host already has them)
#   --no-remove   keep builds no venv links to (skip Playwright's sweep)
set -euo pipefail

usage() {
  echo "usage: bash scripts/install_browser.sh [--with-deps] [--no-remove]" >&2
}

FLAGS=()
for arg in "$@"; do
  case "$arg" in
    --with-deps | --no-remove) FLAGS+=("$arg") ;;
    -h | --help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv run --group browser playwright install --only-shell --no-progress "${FLAGS[@]}" chromium
# The record: which build this lock installs, and where it lives.
uv run --group browser playwright install --dry-run --only-shell chromium |
  grep -E 'chromium-headless-shell v|Install location' | head -2
