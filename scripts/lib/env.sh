# env.sh - parse-never-source env loading for archiver's scripts (#452).
#
# Sourced, not run, by scripts/pre-ship.sh and scripts/dev_server.sh. Sourcing
# an env file runs it as shell code and exports every name in it; the repo
# .env holds PATs and API tokens neither script's children need. So each
# parses the file and exports only its own names.
#
# The parser is not copied here. load_env is lifted from the recipe in the
# vendored gate's header, the one copy (gregoryfoster/skills#517), with the
# eval line upstream's AGENTS.md template uses. On top of it:
#
#   env_file <root>              the checkout's .env, or from a linked worktree
#                                the primary checkout's (the recipe's ENV_FILE
#                                lines; a gitignored .env lives only there)
#   load_env_only <names> <file> export from <file> only the names matching one
#                                of <names>, space-separated globs. ENV_NAMES
#                                lists what it exported: names, never values.
#
# shellcheck shell=bash
_ENV_RECIPE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/skills/shipping-work/scripts/pre-ship.sh"
[[ -r "$_ENV_RECIPE" ]] || {
  echo "ERROR: load_env recipe missing at $_ENV_RECIPE" >&2
  echo "       fix: git submodule update --init --recursive" >&2
  exit 2
}
eval "$(sed -n 's/^#   //; /^load_env() [{]/,/^[}]/p' "$_ENV_RECIPE")"
unset _ENV_RECIPE

env_file() { # <root>
  local common
  if [[ ! -r "$1/.env" ]] && common="$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; then
    echo "$(dirname "$common")/.env"
  else
    echo "$1/.env"
  fi
}

# Upstream's load_env exports every name, so it runs in a subshell: nothing it
# exports escapes. The subshell first drops the matching names it inherited, so
# what it hands back is the file's alone, as printf %q lines for this shell.
load_env_only() { # <names> <file>
  local -a patterns
  local out
  read -ra patterns <<<"$1" # read, not $1 unquoted: a glob must not expand
  out="$(
    _env_matches() {
      local pattern
      for pattern in "${patterns[@]}"; do
        # shellcheck disable=SC2053 # the pattern is a glob on purpose
        [[ $1 == $pattern ]] && return 0
      done
      return 1
    }
    for name in $(compgen -e); do _env_matches "$name" && unset "$name"; done
    load_env "$2"
    for name in $(compgen -e); do
      _env_matches "$name" && printf 'export %s=%q\nENV_NAMES+="${ENV_NAMES:+ }%s"\n' "$name" "${!name}" "$name"
    done
    true
  )"
  ENV_NAMES=""
  eval "$out"
}
