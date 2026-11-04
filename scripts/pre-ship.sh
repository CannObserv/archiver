#!/usr/bin/env bash
# pre-ship.sh - archiver's wrapper around the vendored ship gate (#457).
#
# shipping-work's Step 1 resolves each script on its own, so this file replaces
# only skills/shipping-work/scripts/pre-ship.sh (gregoryfoster/skills#301). It is
# upstream's recipe from that script's header, with two departures (#457 D2):
#
#   - No /etc/archiver/.env. It is root's alone (#339), so an agent shell skips
#     it; under sudo it would hand the test run production's database URL.
#   - From the repo .env, only TEST_DATABASE_URL is exported. The file holds
#     PATs and API tokens no pytest subprocess needs (#452). The parser is
#     upstream's, lifted by scripts/lib/env.sh, which dev_server.sh shares;
#     only the export is filtered. PRE_SHIP_ENV_NAMES lists the names, never
#     the values, for the gate's stamp key.
#
# Usage: bash scripts/pre-ship.sh [--help]
set -euo pipefail
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "ERROR: not inside a git repository" >&2
  exit 2
}
cd "$PROJECT_ROOT"
DELEGATE="skills/shipping-work/scripts/pre-ship.sh"
[[ -f "$DELEGATE" ]] || {
  echo "ERROR: vendored gate missing at $DELEGATE" >&2
  echo "       fix: git submodule update --init --recursive" >&2
  exit 2
}
# shellcheck source=lib/env.sh
. scripts/lib/env.sh                          # load_env_only, env_file (#452)
ENV_FILE=$(env_file "$PROJECT_ROOT")          # a linked worktree has none,
LOCAL_ENV="$PROJECT_ROOT/.env"                # so it is the primary checkout's
[ -r "$ENV_FILE" ] || {                       # neither: say so, loudly
  [ "$ENV_FILE" = "$LOCAL_ENV" ] || LOCAL_ENV="$LOCAL_ENV or $ENV_FILE"
  echo "WARN: no env file at $LOCAL_ENV;" >&2
  echo "      the suite needs TEST_DATABASE_URL, and no stamp is written" >&2
}
load_env_only "TEST_DATABASE_URL" "$ENV_FILE"
export PRE_SHIP_ENV_NAMES="$ENV_NAMES"        # names only: the stamp's key
exec bash "$DELEGATE" "$@"
