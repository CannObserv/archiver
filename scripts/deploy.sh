#!/usr/bin/env bash
# Deploy archiver: build a release from a pushed main commit, rehearse its
# migration, migrate, switch, verify (archiver#330;
# docs/plans/2026-10-09-330-deploy-releases-design.md, D1-D12).
#
#   scripts/deploy.sh [<ref>]            <ref> on origin/main, once its CI passed
#   scripts/deploy.sh --skip-ci [<ref>]  without asking CI: an emergency, logged
#
# <ref> defaults to origin/main. A rollback is a deploy of the previous build.
#
# Ported from CannObserv/status's scripts/deploy.sh (R1-R13, #11, #14, #18),
# with processor's corrections (a copied venv on the system interpreter) and
# archiver's deltas: one target, `live`, with archiver_dev as the migration's
# rehearsal (D2); private wheels fetched into the release (D10); every unit's
# entry point imported before the release is finished (D11); verification by
# /health's build_id, the schema check and a forced bus-health pass (D3, D4);
# and a failed first deploy puts back the checkout-backed units it replaced.
#
# On 2026-10-08 a feature branch checked out in /home/exedev/archiver failed
# the follower timer twice: every unit ran that checkout. Now each runs
# /srv/archiver/live, a symlink into releases/<build>: a read-only `git
# archive` of one pushed commit, with its own venv. Nothing done in a checkout
# reaches a unit until this script puts it there.
#
# In order: CI gate; build (or reuse) the release; rehearse the migration on
# archiver_dev; migrate archiver (skipped when the database is ahead: a
# rollback, D3); switch `live` (rename(2), atomic); install the units that
# differ; restart archiver; force one bus-health pass; verify /health names
# the build and the schema can serve. On failure, switch back, units too,
# restart, and prove the old build. The migration stays (expand-only).
#
# Runs as exedev, the units' user, and builds as exedev. Root owns the deploy
# root, releases/ and every finished release, so the link too (status#14):
# sudo for every write under the root, for systemctl, and for unit files.
# Exits 0 when live verified, 4 when live is left on a build that did not
# answer, 1 otherwise.
set -euo pipefail

ROOT="${ARCHIVER_DEPLOY_ROOT:-/srv/archiver}"
ENV_DIR="${ARCHIVER_DEPLOY_ENV_DIR:-/etc/archiver}"
KEEP="${ARCHIVER_DEPLOY_KEEP:-5}"
# archiver.service's default TimeoutStopSec (90 s) plus a start (processor point 8).
VERIFY_SECONDS="${ARCHIVER_DEPLOY_VERIFY_SECONDS:-120}"
# Past archiver-bus-health.service's TimeoutStartSec=60: a pass still running is stuck.
PROBE_WAIT_SECONDS="${ARCHIVER_DEPLOY_PROBE_WAIT_SECONDS:-90}"
CI_WAIT_SECONDS="${ARCHIVER_DEPLOY_CI_WAIT_SECONDS:-600}"
CI_POLL_SECONDS="${ARCHIVER_DEPLOY_CI_POLL_SECONDS:-30}"
# The interpreter every release venv is built on: never a uv-managed one under
# /home (processor point 2).
PYTHON="${ARCHIVER_DEPLOY_PYTHON:-/usr/bin/python3.12}"
# The jobs a run must have; tests/deploy holds ci.yml to them. Every job a run
# lists must pass too, named here or not (status CR 6).
CI_JOBS=(lint test client-drift changelog)
GITHUB_API="https://api.github.com/repos/CannObserv/archiver"
ETC="${ARCHIVER_DEPLOY_ETC:-/etc}"
UNIT_DIR="$ETC/systemd/system"
API=archiver
PROBE=archiver-bus-health.service
HEALTH_URL="http://127.0.0.1:8000/health"
# Where every unit runs from: the link, never a checkout.
UNIT_ROOT=/srv/archiver/live
# deploy/<file>=<path under /etc>, as deploy/README.md installs each. Compared
# after a deploy, never installed: installing one means sysctl --system, a slice
# reload or a Postgres restart, by hand.
HOST_CONFIGS=(
  "99-archiver-memory.conf=sysctl.d/99-archiver-memory.conf"
  "needrestart.conf.d/archiver.conf=needrestart/conf.d/archiver.conf"
  "postgresql/16/main/environment=postgresql/16/main/environment"
  "postgresql@16-main.service.d/10-memory.conf=systemd/system/postgresql@16-main.service.d/10-memory.conf"
  "system-postgresql.slice.d/10-memory-protection.conf=systemd/system/system-postgresql.slice.d/10-memory-protection.conf"
  "system.slice.d/10-memory-protection.conf=systemd/system/system.slice.d/10-memory-protection.conf"
  "tailscaled.service.d/10-oom.conf=systemd/system/tailscaled.service.d/10-oom.conf"
)
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

note() { echo "deploy: $*" >&2; }
die() {
  note "$*"
  exit 1
}
dead() {
  note "$*"
  exit 4
}
journal() { logger -t archiver-deploy "$*" || true; }

usage() { sed -n '6,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

skip_ci=0
ref=""
while (($#)); do
  case "$1" in
    --skip-ci) skip_ci=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    -*) die "unknown flag $1 (see --help)" ;;
    *)
      [[ -z "$ref" ]] || die "one ref at a time"
      ref="$1"
      ;;
  esac
  shift
done
ref="${ref:-origin/main}"

# Only the env files decide which database and which credential: a shell that
# sourced /etc/archiver/.env or the repo .env must change nothing (status CR 5).
unset ARCHIVER_DATABASE_URL DATABASE_URL ARCHIVER_DEV_DATABASE_URL \
  ARCHIVER_ALLOW_PRODUCTION_DB GOOGLE_APPLICATION_CREDENTIALS

[[ "$(id -u)" -eq 0 ]] && die "run as exedev, not root; the script sudoes where it needs to"

git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1 ||
  die "run from a checkout (/home/exedev/archiver/scripts/deploy.sh); $SRC is not one"

[[ -d "$ROOT" ]] || die "$ROOT does not exist. Once: sudo install -d -m 755 $ROOT"

roots_alone() { # <dir>
  [[ ! -L "$1" ]] || die "$1 is a link; it must be the directory itself (status#14)"
  [[ "$(stat -c %u -- "$1")" == 0 ]] ||
    die "$1 is not root's, so exedev can change what the units run (status#14)." \
      "Once: sudo chown root:root $1 (docs/DEPLOYMENT.md § Releases)"
  [[ -z "$(find "$1" -maxdepth 0 -perm /022)" ]] ||
    die "$1 is writable by more than root (status#14). Once: sudo chmod 755 $1"
}
roots_alone "$ROOT"
[[ ! -e "$ROOT/releases" && ! -L "$ROOT/releases" ]] || roots_alone "$ROOT/releases"

exec 9<"$ROOT"
flock -n 9 || die "another deploy is running (it holds the lock on $ROOT)"

backup="$(mktemp -d "${TMPDIR:-/tmp}/archiver-deploy.XXXXXX")"
trap 'rm -rf "$backup" || :' EXIT

# .env is what the units read; dev.env names the rehearsal database (D2);
# deploy.env holds the wheelhouse credential no unit needs (D10).
for name in .env dev.env deploy.env; do
  [[ -r "$ENV_DIR/$name" ]] || die "$ENV_DIR/$name is missing or unreadable (docs/DEPLOYMENT.md § Releases)"
done

# One variable from one env file, or nothing: never the caller's shell, which
# may have sourced another file (status CR 5).
env_value() { # <file> <name>
  (
    unset "$2"
    set -a
    # shellcheck disable=SC1090
    . "$ENV_DIR/$1"
    printf '%s' "${!2:-}"
  )
}

# --- which commit ----------------------------------------------------------

git -C "$SRC" fetch --quiet --prune origin

# The deploy logic is reviewed code too (CR 10). What goes live must be on
# origin/main, and so must the script deciding how it goes live: run from a
# branch, or with an uncommitted edit, it would put unreviewed logic between
# production and every check below. Byte-for-byte, so nothing slips past.
git -C "$SRC" cat-file -e origin/main:scripts/deploy.sh 2>/dev/null ||
  die "origin/main has no scripts/deploy.sh, so this copy is not reviewed logic; nothing was built"
cmp -s <(git -C "$SRC" show origin/main:scripts/deploy.sh) "${BASH_SOURCE[0]}" ||
  die "${BASH_SOURCE[0]} differs from origin/main's scripts/deploy.sh: only merged deploy logic" \
    "deploys. From the checkout: git switch main && git pull --ff-only, then run it again."
sha="$(git -C "$SRC" rev-parse --verify --quiet "${ref}^{commit}")" || die "cannot resolve $ref"
git -C "$SRC" merge-base --is-ancestor "$sha" origin/main ||
  die "$ref ($sha) is not on origin/main; only a pushed main commit goes live"
build="$(git -C "$SRC" rev-parse --short=12 "$sha")"
release="$ROOT/releases/$build"

# A commit from before releases cannot run as one (CR 14): its units run the
# checkout, and its /health cannot name a release. Deployed, it would put
# production on whatever the checkout holds until verification failed, as it
# always would. Both marks are needed for any deploy to verify.
predates_releases() {
  local unit
  git -C "$SRC" cat-file -e "$sha:src/core/build.py" 2>/dev/null || return 0
  while read -r unit; do
    [[ "$unit" == *.service ]] || continue
    # awk reads to the end: no SIGPIPE for pipefail to mistake for an answer.
    git -C "$SRC" show "$sha:$unit" | awk -v want="WorkingDirectory=$UNIT_ROOT" \
      '/^WorkingDirectory=/ && $0 != want { bad = 1 } END { exit !bad }' && return 0
  done < <(git -C "$SRC" ls-tree --name-only "$sha" deploy/)
  return 1
}
! predates_releases ||
  die "$build predates releases (archiver#330): its units run the checkout and its /health cannot" \
    "name a release, so it would fail verification after running the checkout. Nothing was built." \
    "For older code, revert it on main and deploy that."

# --- CI (status#11) --------------------------------------------------------

# Unauthenticated: the repo is public, and 60 requests an hour per address
# covers a deploy's 2 (22 waiting the full 600 s).
github() { # <path>
  local out
  if out="$(curl -sS --fail-with-body --max-time 10 \
    -H 'Accept: application/vnd.github+json' "$GITHUB_API/$1")"; then
    jq -e 'type == "object"' <<<"$out" >/dev/null 2>&1 ||
      die "GitHub's answer about $build's CI is not the JSON expected; nothing was built." \
        "Deploy again later, or pass --skip-ci."
    printf '%s\n' "$out"
    return
  fi
  out="$(jq -r '.message // empty' <<<"$out" 2>/dev/null)" || out=""
  die "GitHub did not answer about $build's CI.${out:+ GitHub says: $out}" \
    "Nothing was built; deploy again later, or pass --skip-ci."
}

push_run() {
  jq -c --arg sha "$sha" '[.workflow_runs[]
    | select(.head_sha == $sha and .event == "push" and .head_branch == "main")]
    | max_by(.created_at) // empty' ||
    die "GitHub's answer about $build's CI runs is not the JSON expected; nothing was built." \
      "Deploy again later, or pass --skip-ci."
}

finished_run() {
  local deadline=$((SECONDS + CI_WAIT_SECONDS)) tip run state url left
  tip="$(git -C "$SRC" rev-parse origin/main)"
  while :; do
    run="$(github "actions/workflows/ci.yml/runs?head_sha=$sha&event=push&branch=main&per_page=100" | push_run)" ||
      exit 1
    left=$((deadline - SECONDS))
    if [[ -z "$run" && "$sha" != "$tip" ]]; then
      die "no CI run for $build as a push to main. GitHub runs CI on the newest commit of each push" \
        "only: deploy that one, or pass --skip-ci. Pushed in the last minute, with another push" \
        "after it? Its run may not be listed yet: deploy again shortly. Nothing was built."
    elif [[ -z "$run" ]]; then
      state="not queued yet" url=""
      ((left > 0)) ||
        die "no CI run for $build after ${CI_WAIT_SECONDS}s ([skip ci]?). Pass --skip-ci to deploy it" \
          "anyway. Nothing was built."
    else
      state="$(jq -r .status <<<"$run")"
      url="$(jq -r .html_url <<<"$run")"
      [[ "$state" == completed ]] && {
        printf '%s\n' "$run"
        return
      }
      ((left > 0)) ||
        die "CI for $build is still $state after ${CI_WAIT_SECONDS}s. Nothing was built; deploy again" \
          "when it finishes. Run: $url"
    fi
    note "waiting for CI on $build ($state)${url:+: $url}"
    sleep $((left < CI_POLL_SECONDS ? left : CI_POLL_SECONDS))
  done
}

ci_gate() {
  local run url conclusion jobs problems
  run="$(finished_run)" || exit 1
  url="$(jq -r .html_url <<<"$run")"
  conclusion="$(jq -r '.conclusion // "nothing"' <<<"$run")"
  jobs="$(github "actions/runs/$(jq -r .id <<<"$run")/jobs?per_page=100")" || exit 1
  problems="$(jq -r --arg required "${CI_JOBS[*]}" '[
      (.jobs[] | select(.conclusion != "success") | "\(.name) (\(.conclusion // .status))"),
      (($required | split(" "))[] as $name | select(any(.jobs[]; .name == $name) | not)
        | "\($name) (not in the run)")
    ] | join(", ")' <<<"$jobs")" ||
    die "GitHub's answer about $build's CI jobs is not the JSON expected; nothing was built." \
      "Deploy again later, or pass --skip-ci."
  [[ "$conclusion" == success ]] || problems="run concluded $conclusion${problems:+; $problems}"
  local remedy="fix it on main"
  [[ "$conclusion" == cancelled ]] && remedy="re-run it from its page (a re-run counts), or deploy a newer commit"
  [[ -z "$problems" ]] || die "CI did not pass for $build: $problems. Nothing was built; $remedy. Run: $url"
  note "CI passed for $build: $url"
  journal "live: CI passed for $build ($url)"
}

if ((skip_ci)); then
  note "live: not asking CI about $build (--skip-ci)"
  journal "live: CI not checked for $build (--skip-ci)"
else
  ci_gate
fi

# --- the release -----------------------------------------------------------

# Commands inside the release run exactly what was built (R5).
in_release() { (cd "$release" && uv run --frozen --no-sync "$@"); }

# The modules each unit's ExecStart runs: `python -m <mod>` or `uvicorn <mod>:<app>`.
entry_modules() {
  local unit
  for unit in "$release"/deploy/*.service; do
    [[ -f "$unit" ]] || continue
    grep -h '^ExecStart=' "$unit" | grep -oE '(-m |uvicorn )[A-Za-z_][A-Za-z0-9_.]*' |
      sed -E 's/^(-m |uvicorn )//' || true
  done | sort -u
}

# The executables each unit runs from inside the release, as release-relative
# paths: units name the production path, $UNIT_ROOT/... (CR 7).
entry_paths() {
  local unit
  for unit in "$release"/deploy/*.service; do
    [[ -f "$unit" ]] || continue
    grep -hE '^Exec[A-Za-z]*=' "$unit" | sed -E 's/^Exec[A-Za-z]*=[-+@!:]*//' | awk '{print $1}' |
      grep "^$UNIT_ROOT/" | sed "s|^$UNIT_ROOT/||" || true
  done | sort -u
}

build_release() {
  local creds modules heads path
  [[ ! -e "$release" ]] || sudo rm -rf "$release"
  note "building $build"
  [[ -d "$ROOT/releases" ]] || sudo install -d -m 755 "$ROOT/releases" ||
    die "cannot make $ROOT/releases; nothing switched"
  # Built where it runs: a uv venv embeds its absolute path in its scripts.
  sudo install -d -m 755 -o "$(id -un)" -g "$(id -gn)" "$release" ||
    die "cannot make releases/$build for $(id -un) to build in; nothing switched"
  git -C "$SRC" archive "$sha" | tar -x -C "$release"
  # D10: the release's own sync_wheelhouse.py fetches the private wheels into
  # its .wheelhouse, with the credential from deploy.env alone. Not the
  # checkout's .wheelhouse: find-links locks by filename, without a hash.
  creds="$(env_value deploy.env GOOGLE_APPLICATION_CREDENTIALS)"
  [[ -n "$creds" ]] || die "no GOOGLE_APPLICATION_CREDENTIALS in $ENV_DIR/deploy.env; nothing switched"
  (cd "$release" && GOOGLE_APPLICATION_CREDENTIALS="$creds" \
    uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py) ||
    die "fetching the private wheels failed for $build; nothing switched"
  # Copied, not hardlinked to the uv cache: the chown below would reach the
  # cache's inodes (processor CR 11, status#14).
  (cd "$release" && UV_PYTHON_DOWNLOADS=never uv sync --locked --no-dev --compile-bytecode \
    --link-mode copy --python "$PYTHON" --quiet) ||
    die "uv sync failed for $build; nothing switched"
  # The venv holds what it needs; the wheels would cost ~70 MB a release.
  [[ ! -d "$release/.wheelhouse" ]] ||
    find "$release/.wheelhouse" -type f ! -name .gitkeep -delete
  heads="$(in_release alembic heads | grep -c .)" || true
  [[ "$heads" == 1 ]] || die "$build has $heads Alembic heads, not 1; nothing switched"
  # D11: a unit naming a module this release lacks fails at its next start,
  # which for a timer is minutes away (2026-10-08). Find out now.
  mapfile -t modules < <(entry_modules)
  if ((${#modules[@]})); then
    in_release python -c 'import importlib, sys; [importlib.import_module(m) for m in sys.argv[1:]]' \
      "${modules[@]}" ||
      die "a unit's entry point does not import from $build (${modules[*]}); nothing switched"
  fi
  while read -r path; do
    [[ -z "$path" || -x "$release/$path" ]] ||
      die "a unit runs $UNIT_ROOT/$path, which $build lacks or cannot execute; nothing switched"
  done < <(entry_paths)
  # --compile-bytecode covers site-packages only; src/ is the editable project.
  # Compiled now, while it can be written: a read-only release would recompile
  # it in memory on every start (CR 1).
  in_release python -m compileall -q src scripts alembic >/dev/null ||
    die "compileall failed for $build; nothing switched"
  chmod -R a-w "$release" || die "cannot make $build read-only; nothing switched"
  sudo chown -R root:root "$release" || die "cannot hand $build to root; nothing switched"
  # REVISION last, by root: a release without one is an interrupted build (R4).
  { echo "$build" | sudo tee "$release/REVISION" >/dev/null && sudo chmod 444 "$release/REVISION"; } ||
    die "cannot write $build's REVISION; nothing switched"
}

release_of() { # <link>: the build it names, by its last component (status CR 28)
  local link
  link="$(readlink "$ROOT/$1" 2>/dev/null)" || return 0
  basename "$link"
}

unusable() {
  local out
  if [[ ! -e "$release" ]]; then
    echo "not built"
  elif [[ ! -f "$release/REVISION" ]]; then
    echo "an interrupted build"
  elif [[ "$(stat -c %u -- "$release")" != 0 ]]; then
    echo "not root's (status#14)"
  elif ! out="$(in_release python -c 'import fastapi, sqlalchemy, alembic, co_core' 2>&1)"; then
    echo "a venv that no longer runs (${out:-no output})"
  fi
}

# The release live runs is never rebuilt in place: that pulls the code out
# from under the running API, unverified (status CR 15, CR 27, CR 32).
why="$(unusable)"
if [[ -z "$why" ]]; then
  note "reusing release $build"
else
  [[ "$(release_of live)" != "$build" || "$why" == "not built" ]] ||
    die "release $build is $why, and live runs it. Deploy another build first; this one is then rebuilt."
  [[ "$why" == "not built" ]] || note "release $build is $why; rebuilding"
  build_release
fi
sudo touch "$release" # prune by last deploy, not first build

# --- the databases ---------------------------------------------------------

# Runs in the release against one database. Only live carries the production
# opt-in (src/core/db_safety.py); the rehearsal never inherits it.
against() { # <live|rehearsal> <command...>
  local target="$1" url
  shift
  if [[ "$target" == live ]]; then
    url="$(env_value .env ARCHIVER_DATABASE_URL)"
  else
    url="$(env_value dev.env ARCHIVER_DEV_DATABASE_URL)"
  fi
  [[ -n "$url" ]] || die "no database URL for the $target in $ENV_DIR; nothing switched"
  (
    unset DATABASE_URL ARCHIVER_ALLOW_PRODUCTION_DB
    export ARCHIVER_DATABASE_URL="$url"
    [[ "$target" != live ]] || export ARCHIVER_ALLOW_PRODUCTION_DB=1
    in_release "$@"
  )
}

migrate() { # <live|rehearsal>
  local target="$1" out state rc=0
  out="$(against "$target" python -m src.core.schema_state)" || rc=$?
  state="${out%% *}"
  # Only a state the check printed: a refusal or a crash says nothing about
  # the schema and must never become an upgrade (status CR 1).
  case "$rc:$state" in
    0:current | 3:behind | 3:unmigrated) ;;
    0:ahead)
      if [[ "$target" == live ]]; then
        note "live: database is ahead of $build; not migrating. Expected for a rollback."
      else
        # Two causes, one remedy each (CR 16): a newer build's rehearsal left it
        # there, or a worktree's dev_server.sh migrated it to a branch head.
        note "rehearsal: archiver_dev is ahead of $build, so it rehearses nothing. In a rollback" \
          "that is the newer build's migration: nothing to do. Otherwise it holds a branch" \
          "migration that never merged (dev_server.sh from a worktree): downgrade it."
      fi
      return
      ;;
    *) die "$target: cannot read the schema state (exit $rc); nothing switched" ;;
  esac
  against "$target" alembic upgrade head || die "$target: migration failed; nothing switched"
}

# --- units (status#18) -----------------------------------------------------

units_of_release() {
  local path
  for path in "$release"/deploy/*.service "$release"/deploy/*.timer; do
    [[ -f "$path" ]] && basename "$path"
  done
  return 0
}

install_units() {
  local name unit changed=() added=() timers=()
  { mkdir -p "$backup/units" && : >"$backup/added"; } ||
    { note "cannot keep the installed units aside in $backup"; return 1; }
  while read -r name; do
    unit="$UNIT_DIR/$name"
    cmp -s "$release/deploy/$name" "$unit" && continue
    if [[ -e "$unit" ]]; then
      cp "$unit" "$backup/units/$name" ||
        { note "cannot keep $unit aside; not installing it"; return 1; }
      changed+=("$name")
    else
      echo "$name" >>"$backup/added"
      added+=("$name")
    fi
    [[ "$name" != *.timer ]] || timers+=("$name")
    sudo install -m 644 "$release/deploy/$name" "$unit" ||
      { note "installing $name in $UNIT_DIR failed"; return 1; }
  done < <(units_of_release)
  ((${#changed[@]} + ${#added[@]})) || return 0
  sudo systemctl daemon-reload || { note "systemctl daemon-reload failed"; return 1; }
  for name in "${timers[@]}"; do
    sudo systemctl try-restart "$name" ||
      { note "systemctl try-restart $name failed: systemctl status $name"; return 1; }
  done
  local list="${changed[*]}"
  for name in "${added[@]}"; do list+=" $name (new)"; done
  note "units installed from $build: ${list# }"
  journal "live units from $build: ${list# }"
  for name in "${added[@]}"; do
    note "$name is new here and not enabled. If it should run: sudo systemctl enable --now $name"
  done
}

units_replaced() {
  compgen -G "$backup/units/*" >/dev/null || [[ -s "$backup/added" ]]
}

restore_units() {
  local path name timers=() any=0
  for path in "$backup/units"/*; do
    [[ -f "$path" ]] || continue
    name="$(basename "$path")"
    sudo install -m 644 "$path" "$UNIT_DIR/$name" || note "restoring $name failed: $path"
    [[ "$name" != *.timer ]] || timers+=("$name")
    any=1
  done
  if [[ -f "$backup/added" ]]; then
    while read -r name; do
      sudo rm -f "$UNIT_DIR/$name" || note "removing $UNIT_DIR/$name failed"
      any=1
    done <"$backup/added"
  fi
  ((any)) || return 0
  sudo systemctl daemon-reload || note "systemctl daemon-reload failed"
  for name in "${timers[@]}"; do
    sudo systemctl try-restart "$name" || note "systemctl try-restart $name failed"
  done
  journal "live units restored"
}

# A unit installed here that this release's deploy/ lacks: deploy.sh never
# removes one, so it keeps running. After a rollback past archiver#338 the
# drift timer runs a build with no src.core.drift, and co-archiver-drift goes
# missing (processor#35 CR 7). A note, never a removal: retiring a unit is the
# operator's. Only archiver's own units: the host's others are not its business.
note_units_not_in_release() {
  local path name
  for path in "$UNIT_DIR"/archiver.service "$UNIT_DIR"/archiver-*.service "$UNIT_DIR"/archiver-*.timer; do
    [[ -f "$path" ]] || continue
    name="$(basename "$path")"
    [[ -f "$release/deploy/$name" ]] && continue
    note "$name is installed but not in this release's deploy/; it keeps running." \
      "If it should not: sudo systemctl disable --now $name (docs/DEPLOYMENT.md § The drift check)"
  done
  return 0
}

compare_host_configs() {
  local entry rel dest
  for entry in "${HOST_CONFIGS[@]}"; do
    rel="${entry%%=*}" dest="$ETC/${entry#*=}"
    [[ -f "$release/deploy/$rel" ]] || continue
    if [[ ! -e "$dest" ]]; then
      note "host config deploy/$rel is not installed at $dest; install it by hand (deploy/README.md)"
    elif ! cmp -s "$release/deploy/$rel" "$dest"; then
      note "host config deploy/$rel differs from $dest; install it by hand (deploy/README.md)"
    fi
  done
  return 0
}

# --- switch and verify -----------------------------------------------------

swap() { # <target path>: rename(2) over the old link, so there is never no link
  sudo ln -sfn "$1" "$ROOT/live.new"
  sudo mv -Tf "$ROOT/live.new" "$ROOT/live"
}

# What a link's tree reports as build_id: its REVISION, else null, as
# src/core/build.py does once the units stamp nothing.
served_build() { # <link target>
  local dir rev
  dir="$(cd "$ROOT" && cd -P "$1" 2>/dev/null && pwd)" || { echo null; return 0; }
  rev="$(cat "$dir/REVISION" 2>/dev/null)" || rev=""
  [[ -n "$rev" ]] && echo "\"$rev\"" || echo null
}

verify_health() { # <want>: a JSON value, or * for any answer
  local want="$1" health="" deadline=$((SECONDS + VERIFY_SECONDS))
  while ((SECONDS < deadline)); do
    if health="$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null)" &&
      [[ "$want" == "*" || "$health" == *"\"build_id\":$want"* ]]; then
      return 0
    fi
    sleep 1
  done
  note "archiver did not report build_id $want within ${VERIFY_SECONDS}s (last /health: ${health:-none})"
  return 1
}

# `systemctl start` on a oneshot mid-pass merges into that pass, which started
# on the old release. Wait it out (status CR 2).
wait_for_idle_probe() {
  local deadline=$((SECONDS + PROBE_WAIT_SECONDS))
  while [[ "$(systemctl show -p ActiveState --value "$PROBE")" == activating ]]; do
    ((SECONDS < deadline)) || { note "$PROBE has been running for ${PROBE_WAIT_SECONDS}s"; return 1; }
    sleep 1
  done
}

schema_serves() {
  local out rc=0
  out="$(against live python -m src.core.schema_state)" || rc=$?
  ((rc == 0)) || { note "live: the schema cannot serve $build: ${out:-exit $rc}"; return 1; }
}

restart_and_verify() { # <want>
  sudo systemctl reset-failed "$API" || true
  sudo systemctl restart "$API" || { note "systemctl restart $API failed"; return 1; }
  wait_for_idle_probe || return 1
  sudo systemctl start "$PROBE" ||
    { note "the $PROBE pass failed on $build: journalctl -u ${PROBE%.service} -n 50"; return 1; }
  verify_health "$1" && schema_serves
}

# A failed first deploy: nothing to switch back to but the units it replaced,
# which run the checkout. Put them back, drop the link nothing runs, and prove
# the API answers on them.
first_deploy_failed() {
  units_replaced || dead "live failed on $build, and there is nothing to switch back to"
  restore_units
  sudo rm -f "$ROOT/live" || note "removing $ROOT/live failed"
  sudo systemctl reset-failed "$API" || true
  sudo systemctl restart "$API" || true
  if verify_health "*"; then
    journal "live failed on $build; the units it replaced are back, answering"
    die "live failed on $build; the units it replaced are back, and archiver is answering on them"
  fi
  journal "live failed on $build; the units it replaced are back, NOT answering"
  dead "live failed on $build; the units it replaced are back, and archiver is NOT answering:" \
    "journalctl -u $API -n 50"
}

previous_link="$(readlink "$ROOT/live" 2>/dev/null || true)"
previous="$(release_of live)"

migrate rehearsal || die "rehearsal on archiver_dev failed; nothing switched"
migrate live
swap "releases/$build"
journal "live -> $build (was ${previous_link:-nothing})"
units_ok=1
install_units || units_ok=0

if ((units_ok)) && restart_and_verify "\"$build\""; then
  note "live is on $build"
else
  [[ -n "$previous" ]] || first_deploy_failed
  if [[ "$previous" == "$build" ]]; then
    units_replaced ||
      dead "live failed on $build, which it was already running; there is nothing to switch back to"
    old="\"$build\"" back="put back the units it replaced, on $build"
  else
    old="$(served_build "$previous_link")" back="switched back to $previous"
    swap "$previous_link"
  fi
  restore_units
  sudo systemctl reset-failed "$API" || true
  sudo systemctl restart "$API" || true
  if wait_for_idle_probe && sudo systemctl start "$PROBE" && verify_health "$old"; then
    journal "live rolled back to $previous after $build failed ($back)"
    die "live failed on $build; $back, which is answering"
  fi
  journal "live failed on $build; $back, which is NOT answering"
  dead "live failed on $build; $back, which is NOT answering: journalctl -u $API -u ${PROBE%.service} -n 50"
fi
compare_host_configs
note_units_not_in_release

# --- prune -----------------------------------------------------------------

linked=" $(release_of live) "
# shellcheck disable=SC2012 # names are 12 hex characters
ls -1t "$ROOT/releases" | tail -n +$((KEEP + 1)) | while read -r old; do
  [[ "$linked" == *" $old "* ]] && continue
  note "pruning release $old"
  { sudo rm -f "$ROOT/releases/$old/REVISION" && sudo rm -rf "${ROOT:?}/releases/$old"; } ||
    note "prune failed for $old; remove it by hand: sudo rm -rf $ROOT/releases/$old"
done
