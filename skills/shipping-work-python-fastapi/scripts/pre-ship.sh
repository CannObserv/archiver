#!/usr/bin/env bash
# pre-ship.sh — archiver-specific wrapper around the upstream
# shipping-work-python-fastapi/scripts/pre-ship.sh. Sources /etc/archiver/.env
# (system secrets) and $PROJECT_ROOT/.env (repo-local overrides) before
# delegating to the upstream variant.
set -euo pipefail
PROJECT_ROOT=$(git rev-parse --show-toplevel)

# Use `set -a; . <file>; set +a` instead of `export $(cat | xargs)` to handle
# values containing spaces, quotes, newlines, or `=` correctly. The guards
# prevent failure when either file is absent, or unreadable: /etc/archiver/.env
# is root's alone since archiver#339, so an agent shell skips it.
if [[ -r /etc/archiver/.env ]]; then
  set -a; . /etc/archiver/.env; set +a
fi
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a; . "$PROJECT_ROOT/.env"; set +a
fi

exec bash "$PROJECT_ROOT/skills-vendor/gregoryfoster-skills/skills/shipping-work-python-fastapi/scripts/pre-ship.sh" "$@"
