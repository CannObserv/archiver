#!/usr/bin/env bash
# Print one variable's value from an env file, read as data, never executed (#466).
#
#   scripts/env-value.sh NAME [FILE]
#
# FILE defaults to the checkout's .env, or from a linked worktree the primary
# checkout's (env_file): .env is git-ignored, so a worktree has none of its own.
#
# The parser is scripts/lib/env.sh's load_env_only over upstream's load_env, the
# one copy (#452, gregoryfoster/skills#517), so this reads what pre-ship.sh and
# dev_server.sh read. On top of it: NAME must be one name, not a glob, and each
# line's trailing CR is dropped before parsing, so quotes on a CRLF line are still
# stripped. Nothing is expanded; the last match wins.
# An inherited NAME is ignored: the file's value or nothing.
#
# Exit 0 printing the value (no newline); 1 printing nothing when the file or the
# name is absent; 2 on a bad NAME or a missing parser. Same interface as
# CannObserv/processor's scripts/env-value.sh (processor#115); retired when
# gregoryfoster/skills#334 ships its loader.
set -euo pipefail

name=${1-}
case $name in
  '' | [0-9]* | *[!A-Za-z0-9_]*)
    echo "usage: env-value.sh NAME [FILE] (one variable name, not a glob)" >&2
    exit 2
    ;;
esac

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=scripts/lib/env.sh
. "$root/scripts/lib/env.sh"

file=${2:-$(env_file "$root")}
[[ -f "$file" && -r "$file" ]] || exit 1

load_env_only "$name" <(sed 's/\r$//' "$file")
[[ " $ENV_NAMES " == *" $name "* ]] || exit 1
printf %s "${!name}"
