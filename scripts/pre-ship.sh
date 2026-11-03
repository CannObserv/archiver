#!/usr/bin/env bash
# pre-ship.sh - archiver's wrapper around the vendored ship gate (#457).
#
# shipping-work's Step 1 resolves each script on its own, so this file replaces
# only skills/shipping-work/scripts/pre-ship.sh (gregoryfoster/skills#301). It is
# upstream's recipe from that script's header, with two departures (#457 D2):
#
#   - No /etc/archiver/.env. It is root's alone (#339), so an agent shell skips
#     it; under sudo it would hand the test run production's database URL.
#   - From the repo .env, only ALLOW is exported. The file holds PATs and API
#     tokens no pytest subprocess needs (#452); the parser is upstream's, only
#     the export is filtered. PRE_SHIP_ENV_NAMES lists the names, never the
#     values, for the gate's stamp key.
#
# Usage: bash scripts/pre-ship.sh [--help]
set -euo pipefail
PROJECT_ROOT=$(git rev-parse --show-toplevel); cd "$PROJECT_ROOT"
DELEGATE="skills/shipping-work/scripts/pre-ship.sh"
[[ -f "$DELEGATE" ]] || {
  echo "ERROR: vendored gate missing at $DELEGATE" >&2
  echo "       fix: git submodule update --init --recursive" >&2
  exit 2
}
ALLOW=" TEST_DATABASE_URL "
load_env() {                                  # parse, never source
  local line key val
  [ -r "$1" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line#"${line%%[![:space:]]*}"}       # drop leading blanks
    case $line in ''|\#*) continue ;; esac       # blank or comment
    line=${line#export }                        # tolerate `export K=v`
    case $line in *=*) ;; *) continue ;; esac
    key=${line%%=*} val=${line#*=}
    key=${key%"${key##*[![:space:]]}"}
    case $key in ''|[0-9]*|*[!A-Za-z0-9_]*) continue ;; esac
    case $ALLOW in *" $key "*) ;; *) continue ;; esac
    case $val in                                # strip matched quotes
      \"*\") val=${val#\"} val=${val%\"} ;;
      \'*\') val=${val#\'} val=${val%\'} ;;
    esac
    export "$key=$val"
    PRE_SHIP_ENV_NAMES="${PRE_SHIP_ENV_NAMES:+$PRE_SHIP_ENV_NAMES }$key"
  done < "$1"
}
export PRE_SHIP_ENV_NAMES=""                  # names only: the stamp's key
LOCAL_ENV="$PROJECT_ROOT/.env"
ENV_FILE=$LOCAL_ENV                           # a linked worktree has none,
[ -r "$ENV_FILE" ] ||                         # so use the primary checkout's
  ENV_FILE="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/.env"
[ -r "$ENV_FILE" ] || {                       # neither: say so, loudly
  [ "$ENV_FILE" = "$LOCAL_ENV" ] || LOCAL_ENV="$LOCAL_ENV or $ENV_FILE"
  echo "WARN: no env file at $LOCAL_ENV;" >&2
  echo "      the suite needs TEST_DATABASE_URL, and no stamp is written" >&2
}
load_env "$ENV_FILE"
exec bash "$DELEGATE" "$@"
