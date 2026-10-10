"""End-to-end tests for scripts/deploy.sh against a throwaway root (archiver#330).

Ported from CannObserv/status ``tests/deploy/test_deploy.py`` (status#9, #11,
#14, #18), whose script this one adapts. Real git, a temporary origin and
clone; stub ``uv``, ``sudo``, ``curl``, ``systemctl``, ``logger``, ``rm`` and
``stat`` on ``PATH`` that record every call. The stubs read ``FAKE_*``
variables to play a database that is behind or ahead, a failing migration, a
failing probe pass, or an API that never reports the new build.

What the script must hold (design note ``docs/plans/2026-10-09-330-deploy-releases-design.md``):

- **Only pushed main commits, and only once CI passed** (D6).
- **Immutable releases** (R2-R4): one per commit, built once, read-only and
  root's, ``REVISION`` written last, the venv copied (not hardlinked) from the
  uv cache on the system interpreter.
- **Private wheels at build time** (D10): the release's own
  ``sync_wheelhouse.py`` fetches them with the deploy-only credential; they
  are removed once the venv is built.
- **Every unit's entry point imports from the release** (D11) before
  ``REVISION`` marks it finished.
- **Order** (D2, D3): rehearse the migration on ``archiver_dev``, migrate
  ``archiver`` (skipped when ``ahead``), switch, install units, restart,
  verify, switch back on failure.
- **Units follow the release** (D12): only those that differ, a switch back
  puts the installed copies back, host configs are compared, never installed.
- **A first deploy that fails** puts back the checkout-backed units it
  replaced and restarts on them: the cutover's escape hatch.
"""

import contextlib
import fcntl
import grp
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "scripts" / "deploy.sh"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# FAKE_SCHEMA plays both databases, FAKE_DEV_SCHEMA the rehearsal's alone. An
# upgrade leaves a marker, so the schema reads current afterwards, unless
# FAKE_SCHEMA_STUCK (a migration that ran and changed nothing).
STUB_UV = r"""#!/usr/bin/env bash
echo "uv $PWD ALLOW=${ARCHIVER_ALLOW_PRODUCTION_DB:-} URL=${ARCHIVER_DATABASE_URL:-}" \
  "GAC=${GOOGLE_APPLICATION_CREDENTIALS:-} PYDL=${UV_PYTHON_DOWNLOADS:-} $*" >> "$FAKE_LOG"
state_dir="$(dirname "$FAKE_LOG")"
db="${ARCHIVER_DATABASE_URL##*/}"
case "$*" in
  *sync_wheelhouse*)
    [[ -n "${FAKE_WHEELS_FAIL:-}" ]] && { echo "gcs: 403" >&2; exit 1; }
    mkdir -p .wheelhouse && echo wheel > .wheelhouse/co_core-0.19.6-py3-none-any.whl ;;
  sync*)
    [[ -n "${FAKE_SYNC_FAIL:-}" ]] && exit 1
    # The entry points units run (archiver#339), as a real sync installs them.
    mkdir -p .venv/bin && printf '#!/bin/sh\n' | tee .venv/bin/python .venv/bin/uvicorn >/dev/null
    chmod 755 .venv/bin/python .venv/bin/uvicorn ;;
  *schema_state*)
    [[ -n "${FAKE_SCHEMA_CRASH:-}" ]] && exit "$FAKE_SCHEMA_CRASH"
    state="${FAKE_SCHEMA:-current}"
    [[ "$db" == *_dev ]] && state="${FAKE_DEV_SCHEMA:-$state}"
    [[ -e "$state_dir/migrated-$db" && -z "${FAKE_SCHEMA_STUCK:-}" ]] && state=current
    echo "$state database=x code=y"
    [[ "$state" == behind || "$state" == unmigrated ]] && exit 3
    exit 0 ;;
  *"alembic heads"*)
    for ((i = 0; i < ${FAKE_HEADS:-1}; i++)); do echo "head$i (head)"; done ;;
  *"alembic upgrade"*)
    rc="${FAKE_MIGRATE_RC:-0}"
    [[ "$db" == *_dev ]] && rc="${FAKE_DEV_MIGRATE_RC:-$rc}"
    [[ "$rc" == 0 ]] && touch "$state_dir/migrated-$db"
    exit "$rc" ;;
  *compileall*)
    [[ -n "${FAKE_COMPILE_FAIL:-}" ]] && { echo "SyntaxError" >&2; exit 1; } ;;
  *import_module*)
    if [[ -n "${FAKE_IMPORT_FAIL:-}" && " $* " == *" $FAKE_IMPORT_FAIL "* ]]; then
      echo "ModuleNotFoundError: No module named '$FAKE_IMPORT_FAIL'" >&2
      exit 1
    fi ;;
  *"python -c"*)
    [[ -n "${FAKE_BROKEN_VENV:-}" ]] && { echo "probe: no interpreter" >&2; exit 2; } ;;
esac
exit 0
"""

# Plays root (status#14). FAKE_ROOT_OWNED is the ledger of what root owns, one
# "D <dir>" (that directory) or "R <path>" (that tree) per line; the stat stub
# answers from it. What root owns is kept unwritable, and only a command run
# through here opens it, so a write under the deploy root without sudo fails.
STUB_SUDO = r"""#!/usr/bin/env bash
echo "sudo $*" >> "$FAKE_LOG"
[[ "$*" == "systemctl try-restart ${FAKE_TRY_RESTART_FAIL:-none}" ]] && exit 1
[[ "$1" == chown && -n "${FAKE_CHOWN_FAIL:-}" ]] && exit 1
as_root() {
  local kind path opened=() rc=0
  while read -r kind path; do
    [[ -d "$path" && ! -L "$path" ]] && chmod u+w "$path" && opened+=("$path")
  done <"$FAKE_ROOT_OWNED"
  if [[ "$1" == rm && "$2" == -rf ]]; then
    for path in "${@:3}"; do [[ -e "$path" ]] && chmod -R u+w "$path"; done
  fi
  "$@" || rc=$?
  for path in "${opened[@]}"; do [[ -d "$path" ]] && chmod a-w "$path"; done
  return $rc
}
ledger() { echo "$1 $2" >>"$FAKE_ROOT_OWNED"; }
case "$1" in
  install)
    [[ -n "${FAKE_INSTALL_FAIL:-}" && "${@: -1}" == */"$FAKE_INSTALL_FAIL" ]] && exit 1
    as_root "$@" || exit
    if [[ "$2" == -d* && " $* " != *" -o "* ]]; then
      ledger D "${@: -1}"
      chmod a-w "${@: -1}"
    fi
    exit 0 ;;
  chown)
    [[ "$2" == -R && "$3" == root:root ]] || { echo "stub sudo: chown $*?" >&2; exit 1; }
    ledger R "$4"
    exit 0 ;;
  rm)
    as_root "$@" || exit
    for path in "${@:2}"; do
      [[ -e "$path" || -L "$path" ]] ||
        sed -i "\\#^[DR] $path\\(/.*\\)\\{0,1\\}\$#d" "$FAKE_ROOT_OWNED"
    done
    exit 0 ;;
  ln | mv | chmod | touch | tee) as_root "$@"; exit ;;
  # Reads what only root can (archiver#339): the world keeps .env unreadable.
  cat)
    path="${@: -1}" rc=0
    [[ -f "$path" && ! -r "$path" ]] && chmod u+r "$path" && closed=1
    "$@" || rc=$?
    [[ -n "${closed:-}" ]] && chmod u-r "$path"
    exit $rc ;;
esac
# FAKE_PROBE_FAIL fails the forced bus-health pass, only while live runs
# FAKE_PROBE_FAIL_BUILD when that is set: a broken build, not a broken unit.
probe="systemctl start archiver-bus-health.service"
if [[ "$1 $2 $3" == "$probe" && -n "${FAKE_PROBE_FAIL:-}" ]]; then
  running="$(basename "$(readlink "$ARCHIVER_DEPLOY_ROOT/live" 2>/dev/null)")"
  [[ -z "${FAKE_PROBE_FAIL_BUILD:-}" || "$running" == "$FAKE_PROBE_FAIL_BUILD" ]] && exit 1
fi
exit 0
"""

# GitHub's Actions API answers from <tmp>/ci: runs-<n>.json in turn, the last
# repeating, and jobs-<id>.json. With none written, one green push run on main
# for whatever commit was asked about. FAKE_CI_ERROR is GitHub refusing.
#
# /health answers for whichever release `live` names, as the restarted API
# would: its REVISION, else null. With no `live` link the checkout-backed unit
# of before the cutover answers, with its git-describe stamp, unless
# FAKE_CHECKOUT_DOWN. FAKE_STALE plays an API that never reports the build
# being deployed (FAKE_NEW_BUILD), FAKE_STALE_ALWAYS one that reports none.
STUB_CURL = r"""#!/usr/bin/env bash
url="${@: -1}"
echo "curl $url" >> "$FAKE_LOG"
if [[ "$url" == https://api.github.com/* ]]; then
  ci="$(dirname "$FAKE_LOG")/ci"
  if [[ -n "${FAKE_CI_ERROR:-}" ]]; then
    [[ " $* " == *" --fail-with-body "* ]] && echo "{\"message\":\"$FAKE_CI_ERROR\"}"
    exit 22
  fi
  case "$url" in
    */jobs*)
      id="${url#*/actions/runs/}"
      id="${id%%/*}"
      cat "$ci/jobs-$id.json" 2>/dev/null || echo '{"jobs":[
        {"name":"lint","status":"completed","conclusion":"success"},
        {"name":"test","status":"completed","conclusion":"success"},
        {"name":"client-drift","status":"completed","conclusion":"success"},
        {"name":"changelog","status":"completed","conclusion":"success"}]}' ;;
    *)
      sha="${url#*head_sha=}"
      sha="${sha%%&*}"
      n="$(cat "$ci/polls")"
      echo $((n + 1)) > "$ci/polls"
      answers=("$ci"/runs-*.json)
      if [[ -e "${answers[0]}" ]]; then
        last=$((${#answers[@]} - 1))
        cat "$ci/runs-$((n < last ? n : last)).json"
      else
        echo "{\"workflow_runs\":[{\"id\":1,\"head_sha\":\"$sha\",\"event\":\"push\",
          \"head_branch\":\"main\",\"status\":\"completed\",\"conclusion\":\"success\",
          \"created_at\":\"2026-10-01T00:00:00Z\",\"html_url\":\"https://github.test/runs/1\"}]}"
      fi ;;
  esac
  exit 0
fi
[[ "$url" == http://127.0.0.1:8000/health ]] || exit 7
if [[ -L "$ARCHIVER_DEPLOY_ROOT/live" ]]; then
  served="$(cd "$ARCHIVER_DEPLOY_ROOT" && cd -P live 2>/dev/null && pwd)"
  rev="$(cat "$served/REVISION" 2>/dev/null)"
  build="${rev:+\"$rev\"}"
  build="${build:-null}"
else
  [[ -n "${FAKE_CHECKOUT_DOWN:-}" ]] && exit 7
  build='"abc1234"'
fi
new="\"$FAKE_NEW_BUILD\""
if [[ -n "${FAKE_STALE_ALWAYS:-}" || (-n "${FAKE_STALE:-}" && "$build" == "$new") ]]; then
  build='"stale"'
fi
echo "{\"status\":\"ok\",\"build_id\":$build}"
"""

# `systemctl show` needs no sudo. <tmp>/busy is how many polls report a probe
# pass still running (a timer pass that started on the old release).
STUB_SYSTEMCTL = r"""#!/usr/bin/env bash
echo "systemctl $*" >> "$FAKE_LOG"
busy_file="$(dirname "$FAKE_LOG")/busy"
left="$(cat "$busy_file")"
if [[ "$1" == show && "$left" -gt 0 ]]; then
  echo $((left - 1)) > "$busy_file"
  echo activating
elif [[ "$1" == show ]]; then
  echo inactive
fi
"""

STUB_RM = r"""#!/usr/bin/env bash
[[ -n "${FAKE_RM_FAIL:-}" && "$1" == -rf ]] && exit 1
exec /bin/rm "$@"
"""

# The host's users (archiver#339): FAKE_USERS, space-separated; no one else exists.
STUB_GETENT = r"""#!/usr/bin/env bash
[[ ("$1" == passwd || "$1" == group) && " ${FAKE_USERS:-} " == *" $2 "* ]] || exit 2
echo "$2:x:999:999::/nonexistent:/usr/sbin/nologin"
"""

STUB_LOGGER = r"""#!/usr/bin/env bash
echo "logger $*" >> "$FAKE_LOG"
"""

STUB_STAT = r"""#!/usr/bin/env bash
if [[ "$1" == -c && "$2" == %u ]]; then
  path="${@: -1}"
  while read -r kind owned; do
    if [[ "$path" == "$owned" || ("$kind" == R && "$path" == "$owned"/*) ]]; then
      echo 0
      exit 0
    fi
  done <"$FAKE_ROOT_OWNED"
fi
exec @STAT@ "$@"
"""

LIVE_URL = "postgresql+asyncpg://u:p@localhost:5432/archiver"
DEV_URL = "postgresql+asyncpg://u:p@localhost:5432/archiver_dev"
GAC = "/etc/archiver/co-pypi-reader.json"


def ci_run(
    run_id: int,
    sha: str,
    *,
    event: str = "push",
    branch: str = "main",
    status: str = "completed",
    conclusion: str = "success",
    created: str = "2026-10-01T00:00:00Z",
) -> dict:
    """One workflow run as GitHub's Actions API lists it."""
    return {
        "id": run_id,
        "head_sha": sha,
        "event": event,
        "head_branch": branch,
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "created_at": created,
        "html_url": f"https://github.test/runs/{run_id}",
    }


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(checkout: Path, label: str) -> str:
    (checkout / "version.txt").write_text(label)
    git(checkout, "add", "version.txt")
    git(checkout, "commit", "-q", "-m", label)
    return git(checkout, "rev-parse", "HEAD")


class World:
    """A temp origin, clone, deploy root, env dir, /etc and stubbed PATH."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        self.checkout = tmp / "checkout"
        self.root = tmp / "srv"
        self.etc = tmp / "etc"
        self.log = tmp / "calls.log"
        self.stubs = tmp / "stubs"
        self.ci = tmp / "ci"
        self.sysetc = tmp / "sysetc"
        self.units = self.sysetc / "systemd" / "system"
        self.owned = tmp / "root-owned"
        for d in (self.root, self.etc, self.stubs, self.ci):
            d.mkdir()
        self.units.mkdir(parents=True)
        self.log.touch()
        self.owned.write_text(f"D {self.root}\n")
        self.root.chmod(0o555)

        git(tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(tmp, "clone", "-q", str(self.origin), str(self.checkout))
        git(self.checkout, "config", "user.email", "t@example.com")
        git(self.checkout, "config", "user.name", "t")
        # As in production: the deploy logic is itself a commit on origin/main,
        # and the checkout runs that copy (CR 10).
        scripts = self.checkout / "scripts"
        scripts.mkdir()
        shutil.copy(DEPLOY, scripts / "deploy.sh")
        # And the code that names its release on /health: without it no commit
        # can pass verification, so none may be deployed (CR 14).
        (self.checkout / "src" / "core").mkdir(parents=True)
        (self.checkout / "src" / "core" / "build.py").write_text("# reads REVISION\n")
        git(self.checkout, "add", "scripts/deploy.sh", "src/core/build.py")
        self.main = [commit(self.checkout, f"main-{i}") for i in range(3)]
        git(self.checkout, "push", "-q", "origin", "main")
        git(self.checkout, "switch", "-q", "-c", "feature")
        self.feature = commit(self.checkout, "feature")
        git(self.checkout, "push", "-q", "origin", "feature")
        git(self.checkout, "switch", "-q", "main")
        self.unpushed = commit(self.checkout, "unpushed")

        (self.etc / ".env").write_text(f"ARCHIVER_DATABASE_URL={LIVE_URL}\n")
        (self.etc / "dev.env").write_text(f"ARCHIVER_DEV_DATABASE_URL={DEV_URL}\n")
        (self.etc / "deploy.env").write_text(f"GOOGLE_APPLICATION_CREDENTIALS={GAC}\n")
        # root:root 0600 on the host (archiver#339): only sudo reads it.
        (self.etc / ".env").chmod(0o000)

        for name, body in (
            ("uv", STUB_UV),
            ("sudo", STUB_SUDO),
            ("curl", STUB_CURL),
            ("logger", STUB_LOGGER),
            ("systemctl", STUB_SYSTEMCTL),
            ("rm", STUB_RM),
            ("getent", STUB_GETENT),
            ("stat", STUB_STAT.replace("@STAT@", shutil.which("stat") or "/usr/bin/stat")),
        ):
            stub = self.stubs / name
            stub.write_text(body)
            stub.chmod(0o755)

    def run(self, *args: str, **fake: str) -> subprocess.CompletedProcess:
        env = {
            "PATH": f"{self.stubs}:{os.environ['PATH']}",
            "HOME": str(self.tmp),
            "ARCHIVER_DEPLOY_ROOT": str(self.root),
            "ARCHIVER_DEPLOY_ENV_DIR": str(self.etc),
            "ARCHIVER_DEPLOY_ETC": str(self.sysetc),
            "ARCHIVER_DEPLOY_VERIFY_SECONDS": "2",
            "FAKE_LOG": str(self.log),
            "FAKE_ROOT_OWNED": str(self.owned),
            "FAKE_NEW_BUILD": self.build(self.main[-1]),
            **fake,
        }
        (self.tmp / "busy").write_text(fake.get("FAKE_PROBE_BUSY", "0"))
        (self.ci / "polls").write_text("0")
        for marker in self.tmp.glob("migrated-*"):
            marker.unlink()
        return subprocess.run(
            [str(self.checkout / "scripts" / "deploy.sh"), *args],
            cwd=self.tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def build(self, sha: str) -> str:
        return git(self.checkout, "rev-parse", "--short=12", sha)

    def release(self, sha: str) -> Path:
        return self.root / "releases" / self.build(sha)

    def push_deploy(self, files: dict[str, str | None], branch: str = "main") -> str:
        """Commit ``deploy/`` files (None deletes one) on origin's ``branch`` and push."""
        pusher = self.tmp / "pusher"
        if not pusher.exists():
            git(self.tmp, "clone", "-q", str(self.origin), str(pusher))
            git(pusher, "config", "user.email", "t@example.com")
            git(pusher, "config", "user.name", "t")
        git(pusher, "fetch", "-q", "origin")
        git(pusher, "switch", "-q", "-C", branch, f"origin/{branch}")
        for name, body in files.items():
            # Normalized: "../scripts/x" must not need deploy/ to exist first.
            path = Path(os.path.normpath(pusher / "deploy" / name))
            if body is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
            if name.endswith(".sh"):
                path.chmod(0o755)
        git(pusher, "add", "-A")
        git(pusher, "commit", "-q", "--allow-empty", "-m", f"deploy/ on {branch}")
        git(pusher, "push", "-q", "origin", branch)
        git(self.checkout, "fetch", "-q", "origin")
        sha = git(pusher, "rev-parse", "HEAD")
        if branch == "main":
            self.main.append(sha)
        return sha

    def installed(self, name: str) -> str | None:
        path = self.units / name
        return path.read_text() if path.exists() else None

    def live(self) -> str | None:
        link = self.root / "live"
        return os.readlink(link) if link.is_symlink() else None

    def ci_answers(self, *answers: list[dict] | str) -> None:
        for n, runs in enumerate(answers):
            body = runs if isinstance(runs, str) else json.dumps({"workflow_runs": runs})
            (self.ci / f"runs-{n}.json").write_text(body)

    def ci_jobs(self, run_id: int, **conclusions: str) -> None:
        """A run's jobs by conclusion (``client_drift`` for client-drift); absent ones green."""
        jobs = {"lint": "success", "test": "success", "client-drift": "success"}
        jobs["changelog"] = "success"
        jobs.update({k.replace("_", "-"): v for k, v in conclusions.items()})
        body = [
            {"name": name, "status": "completed", "conclusion": conclusion}
            for name, conclusion in jobs.items()
            if conclusion != "absent"
        ]
        (self.ci / f"jobs-{run_id}.json").write_text(json.dumps({"jobs": body}))

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()

    def root_owned(self, path: Path) -> bool:
        for line in self.owned.read_text().splitlines():
            kind, owned = line.split(" ", 1)
            if str(path) == owned or (kind == "R" and str(path).startswith(owned + "/")):
                return True
        return False

    def disown(self, path: Path) -> None:
        lines = self.owned.read_text().splitlines()
        self.owned.write_text("".join(f"{x}\n" for x in lines if x.split(" ", 1)[1] != str(path)))

    @contextlib.contextmanager
    def as_root(self) -> Iterator[None]:
        dirs = [Path(x.split(" ", 1)[1]) for x in self.owned.read_text().splitlines()]
        dirs = [d for d in dirs if d.is_dir() and not d.is_symlink()]
        for d in dirs:
            d.chmod(d.stat().st_mode | stat.S_IWUSR)
        try:
            yield
        finally:
            for d in dirs:
                if d.is_dir():
                    d.chmod(d.stat().st_mode & ~0o222)

    def github_calls(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("curl https://api.github.com/")]

    def reset_log(self) -> None:
        self.log.write_text("")


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    if w.root.exists():
        for path in [w.root, *w.root.rglob("*")]:
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | stat.S_IWUSR)


def assert_ok(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def index_of(calls: list[str], needle: str) -> int:
    return next(i for i, call in enumerate(calls) if needle in call)


def uv_calls(world: World, needle: str) -> list[str]:
    return [c for c in world.calls() if c.startswith("uv ") and needle in c]


def test_script_exists_and_is_executable():
    assert DEPLOY.is_file()
    assert DEPLOY.stat().st_mode & stat.S_IXUSR


class TestADeploy:
    def test_puts_origin_main_live(self, world):
        assert_ok(world.run())
        build = world.build(world.main[-1])
        assert world.live() == f"releases/{build}"
        assert (world.release(world.main[-1]) / "REVISION").read_text().strip() == build

    def test_the_release_is_the_commit_and_nothing_else(self, world):
        (world.checkout / "untracked.txt").write_text("x")
        assert_ok(world.run())
        release = world.release(world.main[-1])
        assert (release / "version.txt").read_text() == "main-2"
        assert not (release / ".git").exists()
        assert not (release / "untracked.txt").exists()

    def test_the_release_is_read_only(self, world):
        assert_ok(world.run())
        release = world.release(world.main[-1])
        for path in [release, *release.rglob("*")]:
            if not path.is_symlink():
                assert not path.stat().st_mode & 0o222, path

    def test_rehearse_on_dev_then_migrate_live_then_switch_then_restart(self, world):
        """D2, D3: archiver_dev rehearses every migration before archiver sees it."""
        assert_ok(world.run(FAKE_SCHEMA="behind"))
        calls = world.calls()
        upgrades = [i for i, c in enumerate(calls) if "alembic upgrade head" in c]
        assert len(upgrades) == 2
        assert "URL=" + DEV_URL + " " in calls[upgrades[0]]
        assert "URL=" + LIVE_URL + " " in calls[upgrades[1]]
        switched = index_of(calls, "logger -t archiver-deploy live -> ")
        restart = calls.index("sudo systemctl restart archiver")
        assert upgrades[1] < switched < restart

    def test_only_live_carries_the_production_opt_in(self, world):
        assert_ok(world.run(FAKE_SCHEMA="behind"))
        dev, live = uv_calls(world, "alembic upgrade head")
        assert "ALLOW= " in dev
        assert "ALLOW=1 " in live

    def test_the_build_is_synced_locked_without_dev_dependencies(self, world):
        assert_ok(world.run())
        (sync,) = uv_calls(world, " sync ")
        for flag in ("--locked", "--no-dev", "--compile-bytecode", "--link-mode copy"):
            assert flag in sync, flag

    def test_the_venv_is_built_on_the_system_interpreter(self, world):
        """processor point 2: no uv-managed Python under /home behind a release."""
        assert_ok(world.run())
        (sync,) = uv_calls(world, " sync ")
        assert "--python /usr/bin/python3.12" in sync
        assert "PYDL=never" in sync

    def test_every_run_in_the_release_neither_syncs_nor_relocks(self, world):
        assert_ok(world.run())
        runs = [c for c in world.calls() if c.startswith("uv ") and " run " in c]
        in_release = [c for c in runs if "sync_wheelhouse" not in c]
        assert in_release
        assert all(" run --frozen --no-sync " in c for c in in_release), in_release

    def test_the_deploy_is_recorded_in_the_journal(self, world):
        assert_ok(world.run())
        build = world.build(world.main[-1])
        logged = [c for c in world.calls() if c.startswith("logger -t archiver-deploy ")]
        assert any("live" in c and build in c for c in logged)


class TestWheels:
    """D10: private wheels are fetched into the release at build time."""

    def test_the_release_fetches_its_own_wheels_with_the_deploy_credential(self, world):
        assert_ok(world.run())
        (fetch,) = uv_calls(world, "sync_wheelhouse")
        release = world.release(world.main[-1])
        assert fetch.startswith(f"uv {release} ")
        assert f"GAC={GAC} " in fetch
        assert "python scripts/sync_wheelhouse.py" in fetch
        assert index_of(world.calls(), "sync_wheelhouse") < index_of(world.calls(), " sync --")

    def test_the_fetched_wheels_are_removed_once_the_venv_is_built(self, world):
        assert_ok(world.run())
        wheelhouse = world.release(world.main[-1]) / ".wheelhouse"
        assert not [p for p in wheelhouse.rglob("*") if p.is_file() and p.name != ".gitkeep"]

    def test_a_failed_fetch_switches_nothing(self, world):
        result = world.run(FAKE_WHEELS_FAIL="1")
        assert result.returncode == 1
        assert "wheel" in result.stderr and "nothing switched" in result.stderr
        assert world.live() is None
        assert not uv_calls(world, " sync --")

    def test_the_credential_is_never_taken_from_the_shell(self, world):
        (world.etc / "deploy.env").write_text("# forgotten\n")
        result = world.run(GOOGLE_APPLICATION_CREDENTIALS="/home/exedev/key.json")
        assert result.returncode == 1
        assert "GOOGLE_APPLICATION_CREDENTIALS" in result.stderr
        assert not uv_calls(world, "sync_wheelhouse")


UNITS_V1 = {
    "archiver.service": (
        "[Service]\nWorkingDirectory=/srv/archiver/live\n"
        "ExecStart=/usr/local/bin/uv run --frozen --no-sync uvicorn src.api.main:app --port 8000\n"
    ),
    "archiver-bus-health.service": (
        "[Service]\n"
        "ExecStart=/usr/local/bin/uv run --frozen --no-sync python -m src.core.bus_health\n"
    ),
    "archiver-bus-health.timer": "[Timer]\n# v1\n",
}


class TestBytecode:
    """CR 1: --compile-bytecode covers site-packages, not the editable src/."""

    def test_the_project_is_compiled_before_the_release_goes_read_only(self, world):
        assert_ok(world.run())
        release = world.release(world.main[-1])
        calls = world.calls()
        (compiled,) = uv_calls(world, "compileall")
        assert compiled.startswith(f"uv {release} ")
        assert "python -m compileall -q src scripts alembic" in compiled
        assert calls.index(compiled) < calls.index(f"sudo chown -R root:root {release}")

    def test_code_that_does_not_compile_switches_nothing(self, world):
        result = world.run(FAKE_COMPILE_FAIL="1")
        assert result.returncode == 1
        assert "compile" in result.stderr and "nothing switched" in result.stderr
        assert world.live() is None


class TestEntryPoints:
    """D11: the 2026-10-08 failure mode, caught before the release is finished."""

    def test_every_unit_entry_point_is_imported_from_the_release(self, world):
        world.push_deploy(UNITS_V1)
        assert_ok(world.run())
        (check,) = uv_calls(world, "import_module")
        assert " src.api.main " in check + " "
        assert " src.core.bus_health" in check

    def test_a_module_the_release_lacks_is_refused_before_revision(self, world):
        world.push_deploy(UNITS_V1)
        result = world.run(FAKE_IMPORT_FAIL="src.core.bus_health")
        assert result.returncode == 1
        assert "src.core.bus_health" in result.stderr and "nothing switched" in result.stderr
        assert not (world.release(world.main[-1]) / "REVISION").exists()
        assert world.live() is None


UNIT_WITH_SCRIPT = {
    "archiver.service": (
        "[Service]\n"
        "ExecStartPre=/srv/archiver/live/scripts/check_redis_floor.sh\n"
        "ExecStart=/usr/local/bin/uv run --frozen --no-sync uvicorn src.api.main:app\n"
    ),
}


class TestEntryPaths:
    """CR 7: D11 for the executables a unit names inside the release."""

    def test_a_script_a_unit_runs_from_the_release_must_be_in_it(self, world):
        world.push_deploy(UNIT_WITH_SCRIPT)
        result = world.run()
        assert result.returncode == 1
        assert "scripts/check_redis_floor.sh" in result.stderr
        assert "nothing switched" in result.stderr
        assert not (world.release(world.main[-1]) / "REVISION").exists()

    def test_a_script_that_is_there_and_executable_passes(self, world):
        world.push_deploy({**UNIT_WITH_SCRIPT, "../scripts/check_redis_floor.sh": "#!/bin/sh\n"})
        assert_ok(world.run())

    def test_paths_outside_the_release_are_not_its_business(self, world):
        world.push_deploy({"archiver.service": "[Service]\nExecStart=/usr/local/bin/uv run x\n"})
        assert_ok(world.run())


UNITS_AS_ARCHIVER = {
    "archiver.service": (
        "[Service]\nUser=archiver\nGroup=archiver\nWorkingDirectory=/srv/archiver/live\n"
        "ExecStart=/srv/archiver/live/.venv/bin/uvicorn src.api.main:app --port 8000\n"
    ),
}


class TestTheServiceUser:
    """archiver#339: the units run as ``archiver``, and only root reads ``.env``."""

    def test_the_production_url_is_read_through_sudo(self, world):
        assert_ok(world.run())
        calls = world.calls()
        assert f"sudo cat {world.etc}/.env" in calls
        assert any(f"URL={LIVE_URL} " in c and "alembic upgrade" in c for c in calls), calls

    def test_dev_and_deploy_env_are_read_without_sudo(self, world):
        """exedev keeps those two (root:exedev 0640): no sudo where none is needed."""
        assert_ok(world.run())
        for name in ("dev.env", "deploy.env"):
            assert not [c for c in world.calls() if c.startswith("sudo") and name in c], name

    def test_a_unit_user_the_host_lacks_is_refused_before_anything_switches(self, world):
        world.push_deploy(UNITS_AS_ARCHIVER)
        result = world.run()
        assert result.returncode == 1
        assert "archiver" in result.stderr and "useradd" in result.stderr
        assert "nothing switched" in result.stderr
        assert world.live() is None
        assert not world.github_calls(), "before CI is asked"
        assert not world.release(world.main[-1]).exists(), "before anything is built"

    def test_spaces_around_the_equals_sign_are_still_a_user(self, world):
        """systemd reads ``User = archiver`` as ``User=archiver``; so must the check."""
        world.push_deploy({"archiver.service": "[Service]\nUser = archiver\n"})
        result = world.run()
        assert result.returncode == 1
        assert "useradd" in result.stderr

    def test_a_unit_user_the_host_has_deploys(self, world):
        world.push_deploy(UNITS_AS_ARCHIVER)
        assert_ok(world.run(FAKE_USERS="archiver"))
        assert world.installed("archiver.service") == UNITS_AS_ARCHIVER["archiver.service"]

    def test_a_reused_release_is_checked_again(self, world):
        """The user is the host's, not the release's: removed since, it is missing now."""
        world.push_deploy(UNITS_AS_ARCHIVER)
        assert_ok(world.run(FAKE_USERS="archiver"))
        world.reset_log()
        result = world.run()
        assert result.returncode == 1
        assert "useradd" in result.stderr
        assert (world.release(world.main[-1]) / "REVISION").exists(), "the built release stays"


class TestTheDeployLogic:
    """CR 10: the script that deploys is reviewed code too.

    The commit it deploys must be on origin/main; so must the logic deploying
    it. A checkout on a branch, or with an uncommitted edit to deploy.sh, would
    otherwise decide how production deploys: #330's failure, one level up.
    """

    def test_an_edited_script_is_refused_before_anything_happens(self, world):
        script = world.checkout / "scripts" / "deploy.sh"
        script.write_text(script.read_text() + "# an uncommitted edit\n")
        result = world.run()
        assert result.returncode == 1
        assert "origin/main" in result.stderr and "git switch main" in result.stderr
        assert not world.github_calls()
        assert_nothing_happened(world)

    def test_a_script_main_has_since_changed_is_refused(self, world):
        """A stale checkout: main reviewed a newer deploy.sh than the one running."""
        world.push_deploy({"../scripts/deploy.sh": DEPLOY.read_text() + "# newer\n"})
        result = world.run()
        assert result.returncode == 1
        assert "git pull --ff-only" in result.stderr
        assert_nothing_happened(world)

    def test_main_without_the_script_is_refused(self, world):
        world.push_deploy({"../scripts/deploy.sh": None})
        result = world.run()
        assert result.returncode == 1
        assert "origin/main" in result.stderr
        assert_nothing_happened(world)

    def test_the_script_main_holds_deploys(self, world):
        assert_ok(world.run())


class TestWhatMayBeDeployed:
    def test_an_unpushed_commit_is_refused(self, world):
        result = world.run(world.unpushed)
        assert result.returncode != 0
        assert "origin/main" in result.stderr
        assert not (world.root / "releases").exists()

    def test_a_branch_commit_never_goes_live(self, world):
        result = world.run(world.feature)
        assert result.returncode != 0
        assert world.live() is None

    def test_an_older_main_commit_may_be_deployed(self, world):
        """How a rollback is spelled: deploy the previous build again."""
        assert_ok(world.run(world.main[0]))
        assert world.live() == f"releases/{world.build(world.main[0])}"

    def test_a_commit_whose_units_run_the_checkout_is_refused(self, world):
        """CR 14: a commit from before releases. Its units would put production on
        the checkout, and its /health could never name the build, so it would
        fail verification every time, after running whatever is checked out."""
        world.push_deploy(
            {"archiver.service": "[Service]\nWorkingDirectory=/home/exedev/archiver\n"}
        )
        result = world.run()
        assert result.returncode == 1
        assert "predates releases" in result.stderr
        assert not world.github_calls()
        assert_nothing_happened(world)

    def test_a_commit_that_cannot_name_its_release_is_refused(self, world):
        world.push_deploy({"../src/core/build.py": None})
        result = world.run("--skip-ci")
        assert result.returncode == 1
        assert "predates releases" in result.stderr
        assert_nothing_happened(world)

    def test_a_commit_whose_units_run_the_release_passes(self, world):
        world.push_deploy({"archiver.service": "[Service]\nWorkingDirectory=/srv/archiver/live\n"})
        assert_ok(world.run())

    def test_an_unknown_ref_is_refused(self, world):
        result = world.run("no-such-ref")
        assert result.returncode != 0
        assert "no-such-ref" in result.stderr

    def test_two_alembic_heads_are_refused_before_anything_switches(self, world):
        result = world.run(FAKE_HEADS="2")
        assert result.returncode != 0
        assert "head" in result.stderr
        assert world.live() is None
        assert not (world.release(world.main[-1]) / "REVISION").exists()


PROMPT_POLLS = {"ARCHIVER_DEPLOY_CI_WAIT_SECONDS": "60", "ARCHIVER_DEPLOY_CI_POLL_SECONDS": "0"}


def assert_nothing_happened(world: World) -> None:
    """Refused before the build: no release, no migration, no unit touched."""
    assert not (world.root / "releases").exists()
    assert world.live() is None
    calls = world.calls()
    assert not [c for c in calls if " sync" in c or "alembic" in c or c.startswith("sudo ")]


class TestTheCIGate:
    """D6, status#11: the newest push run of ci.yml on main for exactly this commit."""

    OTHER_RUNS = pytest.mark.parametrize(
        ("event", "branch"),
        [("workflow_dispatch", "main"), ("pull_request", "main"), ("push", "feature")],
        ids=["dispatch-on-main", "pr-run", "push-elsewhere"],
    )

    def test_a_deploy_asks_about_this_commit_as_pushed_to_main(self, world):
        assert_ok(world.run())
        runs, jobs = world.github_calls()
        assert "/repos/CannObserv/archiver/actions/workflows/ci.yml/runs?" in runs
        for param in (f"head_sha={world.main[-1]}", "event=push", "branch=main"):
            assert param in runs
        assert jobs.endswith("/repos/CannObserv/archiver/actions/runs/1/jobs?per_page=100")

    def test_a_pass_is_logged_with_its_run_before_anything_is_built(self, world):
        assert_ok(world.run())
        calls = world.calls()
        passed = index_of(calls, "CI passed")
        assert world.build(world.main[-1]) in calls[passed]
        assert "https://github.test/runs/1" in calls[passed]
        assert calls[passed].startswith("logger -t archiver-deploy ")
        assert passed < index_of(calls, "sync_wheelhouse")

    def test_a_failed_job_is_refused_by_name_before_anything_is_built(self, world):
        world.ci_answers([ci_run(7, world.main[-1])])
        world.ci_jobs(7, client_drift="failure")
        result = world.run()
        assert result.returncode == 1
        assert "client-drift (failure)" in result.stderr
        assert "lint (" not in result.stderr
        assert "https://github.test/runs/7" in result.stderr
        assert_nothing_happened(world)

    @pytest.mark.parametrize("conclusion", ["skipped", "cancelled", "absent"])
    def test_a_required_job_that_did_not_succeed_is_not_a_pass(self, world, conclusion):
        """A skipped job leaves the run's own conclusion 'success'."""
        world.ci_answers([ci_run(7, world.main[-1])])
        world.ci_jobs(7, changelog=conclusion)
        result = world.run()
        assert result.returncode == 1
        assert "changelog (" in result.stderr
        assert_nothing_happened(world)

    def test_a_failed_job_the_checkout_does_not_know_is_refused(self, world):
        world.ci_answers([ci_run(7, world.main[-1], conclusion="failure")])
        world.ci_jobs(7, e2e="failure")
        result = world.run()
        assert result.returncode == 1
        assert "e2e (failure)" in result.stderr
        assert_nothing_happened(world)

    def test_a_cancelled_run_says_how_to_recover(self, world):
        world.ci_answers([ci_run(7, world.main[-1], conclusion="cancelled")])
        world.ci_jobs(7, lint="absent", test="absent", client_drift="absent", changelog="absent")
        result = world.run()
        assert result.returncode == 1
        assert "run concluded cancelled" in result.stderr
        assert "re-run it" in result.stderr
        assert_nothing_happened(world)

    def test_a_run_still_going_when_the_wait_ends_is_refused(self, world):
        world.ci_answers([ci_run(7, world.main[-1], status="in_progress")])
        result = world.run(ARCHIVER_DEPLOY_CI_WAIT_SECONDS="0")
        assert result.returncode == 1
        assert "in_progress" in result.stderr
        assert_nothing_happened(world)

    def test_a_run_that_finishes_within_the_wait_is_deployed(self, world):
        sha = world.main[-1]
        world.ci_answers([ci_run(7, sha, status="in_progress")], [ci_run(7, sha)])
        started = time.monotonic()
        result = world.run(**PROMPT_POLLS)
        assert_ok(result)
        assert time.monotonic() - started < 15
        assert "waiting for CI" in result.stderr

    def test_the_tip_just_pushed_waits_for_its_run_to_appear(self, world):
        world.ci_answers([], [ci_run(7, world.main[-1])])
        assert_ok(world.run(**PROMPT_POLLS))

    def test_a_commit_behind_the_tip_with_no_run_is_refused_at_once(self, world):
        world.ci_answers([])
        result = world.run(world.main[0])
        assert result.returncode == 1
        assert "newest commit of each push" in result.stderr
        assert len(world.github_calls()) == 1
        assert_nothing_happened(world)

    @OTHER_RUNS
    def test_only_the_push_run_on_main_decides(self, world, event, branch):
        sha = world.main[-1]
        other = ci_run(8, sha, event=event, branch=branch, created="2026-10-01T02:00:00Z")
        world.ci_answers([other, ci_run(7, sha, created="2026-10-01T01:00:00Z")])
        world.ci_jobs(8, test="failure")
        world.ci_jobs(7)
        assert_ok(world.run())
        assert world.github_calls()[-1].endswith("/actions/runs/7/jobs?per_page=100")

    def test_github_refusing_refuses_the_deploy_with_its_message(self, world):
        result = world.run(FAKE_CI_ERROR="API rate limit exceeded for 192.0.2.1.")
        assert result.returncode == 1
        assert "API rate limit exceeded for 192.0.2.1." in result.stderr
        assert "--skip-ci" in result.stderr
        assert_nothing_happened(world)

    @pytest.mark.parametrize("body", ["<html>unicorn</html>", '{"total_count":0}', "", " \n"])
    def test_an_answer_that_is_not_what_was_expected_refuses_the_deploy(self, world, body):
        world.ci_answers(body)
        result = world.run(ARCHIVER_DEPLOY_CI_WAIT_SECONDS="0")
        assert result.returncode == 1
        assert "not the JSON expected" in result.stderr
        assert_nothing_happened(world)

    def test_skip_ci_deploys_without_asking_and_logs_it_first(self, world):
        world.ci_answers([ci_run(7, world.main[-1])])
        world.ci_jobs(7, test="failure")
        assert_ok(world.run("--skip-ci"))
        assert not world.github_calls()
        calls = world.calls()
        skipped = index_of(calls, "--skip-ci")
        assert calls[skipped].startswith("logger -t archiver-deploy ")
        assert skipped < index_of(calls, "sync_wheelhouse")

    def test_the_jobs_the_gate_requires_are_ones_ci_yml_runs_on_a_push_to_main(self):
        required = re.search(r"^CI_JOBS=\((.*)\)$", DEPLOY.read_text(), re.M)
        assert required, "deploy.sh names its jobs in CI_JOBS=(...)"
        workflow = yaml.safe_load(CI_WORKFLOW.read_text())
        jobs = {job.get("name", key): job for key, job in workflow["jobs"].items()}
        assert set(required.group(1).split()) == {"lint", "test", "client-drift", "changelog"}
        assert set(required.group(1).split()) <= set(jobs)
        for name in required.group(1).split():
            assert "strategy" not in jobs[name] and "uses" not in jobs[name], name
        assert "main" in workflow.get(True, workflow.get("on"))["push"]["branches"]


class TestReleases:
    def test_a_built_release_is_reused(self, world):
        assert_ok(world.run(world.main[0]))
        assert_ok(world.run(world.main[-1]))
        world.reset_log()
        assert_ok(world.run(world.main[0]))
        assert not uv_calls(world, " sync")

    def test_an_unlinked_release_whose_venv_no_longer_runs_is_rebuilt(self, world):
        assert_ok(world.run(world.main[0]))
        assert_ok(world.run(world.main[1]))
        world.reset_log()
        result = world.run(world.main[0], FAKE_BROKEN_VENV="1")
        assert_ok(result)
        assert uv_calls(world, " sync --")
        assert "probe: no interpreter" in result.stderr

    def test_the_linked_release_is_never_rebuilt_in_place(self, world):
        """Live runs from it: a rebuild pulls the code out from under the API."""
        assert_ok(world.run(world.main[0]))
        release = world.release(world.main[0])
        world.reset_log()
        result = world.run(world.main[0], FAKE_BROKEN_VENV="1")
        assert result.returncode != 0
        assert (release / "REVISION").exists()
        assert not uv_calls(world, " sync --")
        assert "live" in result.stderr

    def test_an_interrupted_build_is_rebuilt(self, world):
        partial = world.release(world.main[-1])
        with world.as_root():
            partial.parent.mkdir()
        world.owned.write_text(world.owned.read_text() + f"D {partial.parent}\n")
        with world.as_root():
            partial.mkdir()
        (partial / "half-written").write_text("x")
        assert_ok(world.run())
        assert not (partial / "half-written").exists()
        assert (partial / "REVISION").exists()

    def test_a_failed_sync_switches_nothing(self, world):
        result = world.run(FAKE_SYNC_FAIL="1")
        assert result.returncode != 0
        assert world.live() is None

    def test_old_releases_are_pruned_but_never_the_linked_one(self, world):
        assert_ok(world.run(world.main[0]))
        assert_ok(world.run(world.main[1]))
        assert_ok(world.run(world.main[2], ARCHIVER_DEPLOY_KEEP="1"))
        kept = {p.name for p in (world.root / "releases").iterdir()}
        assert kept == {world.build(world.main[2])}

    def test_a_failed_prune_does_not_fail_a_deploy_that_succeeded(self, world):
        assert_ok(world.run(world.main[0]))
        assert_ok(world.run(world.main[1]))
        result = world.run(world.main[2], ARCHIVER_DEPLOY_KEEP="1", FAKE_RM_FAIL="1")
        assert_ok(result)
        assert "prune" in result.stderr
        half = world.release(world.main[0])
        assert half.exists() and not (half / "REVISION").exists()

    def test_a_release_root_does_not_own_is_rebuilt(self, world):
        assert_ok(world.run(world.main[0]))
        assert_ok(world.run(world.main[1]))
        release = world.release(world.main[0])
        world.disown(release)
        world.reset_log()
        result = world.run(world.main[0])
        assert_ok(result)
        assert uv_calls(world, " sync --")
        assert "not root's" in result.stderr
        assert world.root_owned(release)

    def test_the_reuse_probe_imports_the_dependencies_not_just_python(self, world):
        assert_ok(world.run(world.main[0]))
        world.reset_log()
        assert_ok(world.run(world.main[0]))
        (probe,) = [c for c in uv_calls(world, "python -c") if "import_module" not in c]
        assert "import fastapi" in probe and "co_core" in probe


class TestOwnership:
    """status#14: root owns the deploy root, releases/ and every finished release."""

    def test_a_built_release_is_roots_throughout(self, world):
        assert_ok(world.run())
        release = world.release(world.main[-1])
        assert world.root_owned(world.root / "releases")
        assert world.root_owned(release)
        assert world.root_owned(release / ".venv")

    def test_root_takes_the_release_before_revision_marks_it_finished(self, world):
        assert_ok(world.run())
        release = world.release(world.main[-1])
        calls = world.calls()
        chown = calls.index(f"sudo chown -R root:root {release}")
        assert chown < calls.index(f"sudo tee {release}/REVISION")
        assert f"sudo chmod 444 {release}/REVISION" in calls

    def test_the_release_is_built_where_it_runs_by_the_deploying_user(self, world):
        assert_ok(world.run())
        release = world.release(world.main[-1])
        me, group = pwd.getpwuid(os.getuid()).pw_name, grp.getgrgid(os.getgid()).gr_name
        calls = world.calls()
        made = calls.index(f"sudo install -d -m 755 -o {me} -g {group} {release}")
        chown = calls.index(f"sudo chown -R root:root {release}")
        assert made < index_of(calls, " sync --") < chown

    def test_a_failed_chown_switches_nothing_and_leaves_no_revision(self, world):
        result = world.run(FAKE_CHOWN_FAIL="1")
        assert result.returncode == 1
        assert world.live() is None
        assert not (world.release(world.main[-1]) / "REVISION").exists()

    def test_a_deploy_root_root_does_not_own_is_refused_with_the_fix(self, world):
        world.disown(world.root)
        result = world.run()
        assert result.returncode == 1
        assert f"sudo chown root:root {world.root}" in result.stderr
        assert not [c for c in world.calls() if c.startswith("sudo ")]

    def test_a_group_writable_deploy_root_is_refused(self, world):
        world.root.chmod(0o575)
        result = world.run()
        assert result.returncode == 1
        assert f"sudo chmod 755 {world.root}" in result.stderr

    def test_a_deploy_root_that_is_a_link_is_refused_as_one(self, world):
        real = world.tmp / "real-srv"
        world.root.rename(real)
        world.root.symlink_to(real)
        result = world.run()
        assert result.returncode == 1
        assert "a link" in result.stderr and "writable" not in result.stderr

    def test_the_link_is_replaced_by_root(self, world):
        assert_ok(world.run())
        assert f"sudo mv -Tf {world.root}/live.new {world.root}/live" in world.calls()

    def test_the_prune_is_done_by_root_revision_first(self, world):
        assert_ok(world.run(world.main[0]))
        assert_ok(world.run(world.main[1]))
        world.reset_log()
        assert_ok(world.run(world.main[2], ARCHIVER_DEPLOY_KEEP="1"))
        old = world.release(world.main[0])
        assert not old.exists()
        calls = world.calls()
        assert calls.index(f"sudo rm -f {old}/REVISION") < calls.index(f"sudo rm -rf {old}")


class TestMigrations:
    def test_a_database_ahead_of_the_release_is_not_migrated(self, world):
        """A rollback: the older Alembic cannot resolve the newer revision."""
        result = world.run(FAKE_SCHEMA="ahead")
        assert_ok(result)
        assert not uv_calls(world, "alembic upgrade")
        assert "ahead" in result.stderr

    def test_a_dev_database_ahead_names_both_causes(self, world):
        """dev_server.sh from a worktree migrates archiver_dev to a branch head; a
        rollback finds it where the newer build's rehearsal left it (CR 16). Only
        the first wants a downgrade, so the message must not prescribe it alone."""
        result = world.run(FAKE_DEV_SCHEMA="ahead", FAKE_SCHEMA="behind")
        assert_ok(result)
        (upgrade,) = uv_calls(world, "alembic upgrade")
        assert "URL=" + LIVE_URL + " " in upgrade
        assert "rollback" in result.stderr and "nothing to do" in result.stderr
        assert "branch" in result.stderr and "downgrade" in result.stderr

    @pytest.mark.parametrize("state", ["behind", "unmigrated"])
    def test_a_database_behind_is_migrated(self, world, state):
        assert_ok(world.run(FAKE_SCHEMA=state))
        assert len(uv_calls(world, "alembic upgrade")) == 2

    @pytest.mark.parametrize("rc", ["1", "2"], ids=["crash", "unreadable"])
    def test_an_unreadable_schema_state_is_never_migrated(self, world, rc):
        result = world.run(FAKE_SCHEMA_CRASH=rc)
        assert result.returncode != 0
        assert not uv_calls(world, "alembic upgrade")
        assert world.live() is None

    def test_a_failed_rehearsal_never_reaches_production(self, world):
        result = world.run(FAKE_SCHEMA="behind", FAKE_DEV_MIGRATE_RC="1")
        assert result.returncode == 1
        assert "rehearsal" in result.stderr
        assert not [c for c in uv_calls(world, "alembic upgrade") if "URL=" + LIVE_URL + " " in c]
        assert world.live() is None

    def test_a_failed_migration_switches_nothing(self, world):
        result = world.run(FAKE_SCHEMA="behind", FAKE_MIGRATE_RC="1")
        assert result.returncode != 0
        assert world.live() is None
        switched = ("sudo ln ", "sudo mv ", "sudo systemctl ", "sudo install -m 644 ")
        assert not [c for c in world.calls() if c.startswith(switched)]


class TestVerification:
    def test_a_live_api_on_the_wrong_build_is_switched_back(self, world):
        assert_ok(world.run(world.main[0]))
        previous = world.live()
        world.reset_log()
        result = world.run(FAKE_STALE="1")
        assert result.returncode == 1, result.stderr
        assert world.live() == previous
        assert world.calls().count("sudo systemctl restart archiver") == 2
        old = world.build(world.main[0])
        assert f"switched back to {old}, which is answering" in result.stderr

    def test_verification_asks_health_for_the_build_and_the_schema(self, world):
        assert_ok(world.run())
        calls = world.calls()
        restart = calls.index("sudo systemctl restart archiver")
        assert "curl http://127.0.0.1:8000/health" in calls[restart:]
        after = [c for c in calls[restart:] if "schema_state" in c]
        assert after and "URL=" + LIVE_URL + " " in after[0]

    def test_a_schema_still_behind_after_the_switch_fails_verification(self, world):
        assert_ok(world.run(world.main[0]))
        result = world.run(FAKE_SCHEMA="behind", FAKE_SCHEMA_STUCK="1")
        assert result.returncode == 1, result.stderr
        assert "behind" in result.stderr

    def test_the_rollback_clears_the_start_limit_and_proves_the_old_build(self, world):
        assert_ok(world.run(world.main[0]))
        world.reset_log()
        assert world.run(FAKE_STALE="1").returncode == 1
        calls = world.calls()
        resets = [i for i, c in enumerate(calls) if c == "sudo systemctl reset-failed archiver"]
        restarts = [i for i, c in enumerate(calls) if c == "sudo systemctl restart archiver"]
        assert resets[0] < restarts[0] < resets[1] < restarts[1]

    def test_a_rollback_that_does_not_come_back_says_so(self, world):
        assert_ok(world.run(world.main[0]))
        result = world.run(FAKE_STALE_ALWAYS="1")
        assert result.returncode == 4
        assert "NOT answering" in result.stderr
        logged = [c for c in world.calls() if c.startswith("logger ")]
        assert not [c for c in logged if "rolled back to" in c]

    def test_a_failing_probe_pass_is_switched_back(self, world):
        """D4: the forced bus-health pass proves the timer path on the new release."""
        assert_ok(world.run(world.main[0]))
        previous = world.live()
        result = world.run(FAKE_PROBE_FAIL="1", FAKE_PROBE_FAIL_BUILD=world.build(world.main[-1]))
        assert result.returncode == 1, result.stderr
        assert world.live() == previous
        assert "archiver-bus-health" in result.stderr
        assert "which is answering" in result.stderr

    def test_the_follower_is_never_forced(self, world):
        """D4: it writes production and calls Power Map; the import check covers it."""
        assert_ok(world.run())
        assert not [c for c in world.calls() if "pm-org-refresh.service" in c and " start " in c]

    def test_the_forced_pass_waits_out_one_already_running(self, world):
        """status CR 2: `systemctl start` on a oneshot mid-pass merges into that pass."""
        assert_ok(world.run(FAKE_PROBE_BUSY="2"))
        calls = world.calls()
        start = calls.index("sudo systemctl start archiver-bus-health.service")
        polls = [i for i, c in enumerate(calls) if c.startswith("systemctl show")]
        assert len(polls) == 3
        assert max(polls) < start

    def test_a_pass_that_never_ends_fails_and_switches_back(self, world):
        assert_ok(world.run(world.main[0]))
        previous = world.live()
        world.reset_log()
        result = world.run(FAKE_PROBE_BUSY="1", ARCHIVER_DEPLOY_PROBE_WAIT_SECONDS="0")
        assert result.returncode == 1, result.stderr
        assert "has been running" in result.stderr
        assert world.live() == previous

    def test_redeploying_the_running_build_has_nothing_to_switch_back_to(self, world):
        assert_ok(world.run())
        world.reset_log()
        result = world.run(FAKE_STALE_ALWAYS="1")
        assert result.returncode == 4
        assert "already" in result.stderr
        assert "switched back" not in result.stderr


CHECKOUT_UNITS = {
    "archiver.service": "[Service]\nWorkingDirectory=/home/exedev/archiver\n",
    "archiver-bus-health.service": "[Service]\nWorkingDirectory=/home/exedev/archiver\n",
    "archiver-bus-health.timer": "[Timer]\n# v1\n",
}


class TestTheFirstDeploy:
    """The cutover: the units it replaces run the checkout, and are its escape hatch."""

    def install_checkout_units(self, world):
        for name, body in CHECKOUT_UNITS.items():
            (world.units / name).write_text(body)

    def test_a_first_deploy_installs_the_release_units_and_verifies(self, world):
        self.install_checkout_units(world)
        world.push_deploy(UNITS_V1)
        assert_ok(world.run())
        assert world.installed("archiver.service") == UNITS_V1["archiver.service"]

    def test_a_failed_first_deploy_puts_the_checkout_units_back_and_restarts_on_them(self, world):
        self.install_checkout_units(world)
        world.push_deploy(UNITS_V1)
        result = world.run(FAKE_STALE="1")
        assert result.returncode == 1, result.stderr
        assert world.installed("archiver.service") == CHECKOUT_UNITS["archiver.service"]
        assert world.live() is None, "nothing runs the release: no link to mislead"
        assert "the units it replaced are back, and archiver is answering on them" in result.stderr
        assert "which is answering" not in result.stderr, "CR 5: said once, plainly"
        assert world.calls().count("sudo systemctl restart archiver") == 2

    def test_a_failed_first_deploy_whose_old_units_do_not_answer_either_is_dead(self, world):
        self.install_checkout_units(world)
        world.push_deploy(UNITS_V1)
        result = world.run(FAKE_STALE="1", FAKE_CHECKOUT_DOWN="1")
        assert result.returncode == 4
        assert "NOT answering" in result.stderr

    def test_a_failed_first_deploy_that_replaced_nothing_has_nothing_to_return_to(self, world):
        result = world.run(FAKE_STALE="1")
        assert result.returncode == 4
        assert "nothing to switch back to" in result.stderr


class TestOperation:
    def test_a_concurrent_deploy_is_refused_before_asking_ci(self, world):
        held = os.open(world.root, os.O_RDONLY)
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = world.run()
        finally:
            os.close(held)
        assert result.returncode != 0
        assert "another deploy" in result.stderr
        assert not world.github_calls()

    def test_the_lock_leaves_nothing_behind(self, world):
        assert_ok(world.run())
        assert sorted(p.name for p in world.root.iterdir()) == ["live", "releases"]

    def test_a_missing_root_says_how_to_create_it(self, world):
        world.root.rmdir()
        result = world.run()
        assert result.returncode != 0
        assert f"sudo install -d -m 755 {world.root}" in result.stderr

    @pytest.mark.parametrize("name", [".env", "dev.env", "deploy.env"])
    def test_a_missing_env_file_is_refused(self, world, name):
        (world.etc / name).unlink()
        result = world.run()
        assert result.returncode != 0
        assert name in result.stderr
        assert not world.github_calls()

    def test_a_url_missing_from_its_env_file_is_not_taken_from_the_shell(self, world):
        """The unit reads only the file, so the deploy must too."""
        (world.etc / "dev.env").write_text("# ARCHIVER_DEV_DATABASE_URL forgotten\n")
        result = world.run(
            ARCHIVER_DEV_DATABASE_URL="postgresql+asyncpg://u@h/from_the_shell_dev",
            ARCHIVER_DATABASE_URL="postgresql+asyncpg://u@h/from_the_shell",
        )
        assert result.returncode != 0
        assert not [c for c in world.calls() if "from_the_shell" in c]
        assert "no database URL for the rehearsal" in result.stderr

    def test_run_from_outside_a_checkout_says_where_to_run_it(self, world):
        release_scripts = world.tmp / "release" / "scripts"
        release_scripts.mkdir(parents=True)
        shutil.copy(DEPLOY, release_scripts / "deploy.sh")
        result = subprocess.run(
            [str(release_scripts / "deploy.sh")],
            env={
                "PATH": f"{world.stubs}:{os.environ['PATH']}",
                "ARCHIVER_DEPLOY_ROOT": str(world.root),
                "ARCHIVER_DEPLOY_ENV_DIR": str(world.etc),
                "FAKE_LOG": str(world.log),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0
        assert "from a checkout" in result.stderr

    def test_an_unknown_flag_is_refused(self, world):
        assert world.run("--dev").returncode != 0

    def test_help_names_skip_ci(self, world):
        result = world.run("--help")
        assert_ok(result)
        assert "--skip-ci" in result.stdout

    def test_root_is_refused(self):
        assert '"$(id -u)" -eq 0' in DEPLOY.read_text()


def installs(calls: list[str]) -> list[str]:
    """The unit names `sudo install -m 644` wrote, in order."""
    return [Path(c.split()[-1]).name for c in calls if c.startswith("sudo install -m 644 ")]


class TestUnits:
    """D12, status#18: units reach /etc/systemd/system with the release they run."""

    def test_the_release_units_are_installed(self, world):
        world.push_deploy(UNITS_V1)
        assert_ok(world.run())
        for name, body in UNITS_V1.items():
            assert world.installed(name) == body, name

    def test_units_switch_with_the_link_before_the_restart(self, world):
        world.push_deploy(UNITS_V1)
        assert_ok(world.run())
        calls = world.calls()
        switched = index_of(calls, "logger -t archiver-deploy live -> ")
        installed = index_of(calls, "/archiver.service")
        reload = next(i for i, c in enumerate(calls) if i > installed and "daemon-reload" in c)
        assert switched < installed < reload < calls.index("sudo systemctl restart archiver")

    def test_unchanged_units_need_neither_sudo_nor_a_reload(self, world):
        world.push_deploy(UNITS_V1)
        assert_ok(world.run())
        world.push_deploy({})
        world.reset_log()
        assert_ok(world.run())
        assert not installs(world.calls())
        assert not [c for c in world.calls() if "daemon-reload" in c]

    def test_a_changed_timer_is_restarted_so_it_rearms(self, world):
        world.push_deploy(UNITS_V1)
        assert_ok(world.run())
        world.push_deploy({"archiver-bus-health.timer": "[Timer]\n# v2\n"})
        world.reset_log()
        assert_ok(world.run())
        assert [c for c in world.calls() if "try-restart" in c] == [
            "sudo systemctl try-restart archiver-bus-health.timer"
        ]

    def test_a_new_unit_is_installed_and_named_with_how_to_enable_it(self, world):
        world.push_deploy(UNITS_V1)
        assert_ok(world.run())
        world.push_deploy({"archiver-drift.timer": "[Timer]\n"})
        result = world.run()
        assert_ok(result)
        assert world.installed("archiver-drift.timer") == "[Timer]\n"
        assert "sudo systemctl enable --now archiver-drift.timer" in result.stderr
        assert not [c for c in world.calls() if " enable " in c]

    def test_an_installed_unit_the_release_lacks_is_named_never_removed(self, world):
        """archiver#338, processor#35 CR 7: after a rollback past the drift check its
        timer keeps running a build with no ``src.core.drift``, and co-archiver-drift
        goes missing. Retiring a unit is the operator's: a note, never a removal."""
        world.push_deploy({**UNITS_V1, "archiver-drift.timer": "[Timer]\n"})
        assert_ok(world.run())
        world.push_deploy({"archiver-drift.timer": None})
        world.reset_log()
        result = world.run()
        assert_ok(result)
        assert world.installed("archiver-drift.timer") == "[Timer]\n"
        assert (
            "archiver-drift.timer is installed but not in this release's deploy/; it keeps "
            "running. If it should not: sudo systemctl disable --now archiver-drift.timer"
        ) in result.stderr
        assert not [c for c in world.calls() if "disable" in c or "archiver-drift" in c]

    def test_a_unit_that_is_not_archivers_is_not_its_business(self, world):
        world.push_deploy(UNITS_V1)
        (world.units / "postgresql.service").write_text("[Service]\n")
        result = world.run()
        assert_ok(result)
        assert "postgresql.service" not in result.stderr

    def test_a_failed_verify_puts_back_exactly_the_units_it_replaced(self, world):
        world.push_deploy(UNITS_V1)
        assert_ok(world.run())
        (world.units / "archiver.service").write_text("edited by hand\n")
        world.push_deploy({"archiver.service": "v2\n", "archiver-drift.timer": "[Timer]\n"})
        result = world.run(FAKE_STALE="1")
        assert result.returncode == 1, result.stderr
        assert world.installed("archiver.service") == "edited by hand\n"
        assert world.installed("archiver-drift.timer") is None

    def test_a_failed_install_switches_back(self, world):
        world.push_deploy(UNITS_V1)
        assert_ok(world.run())
        previous = world.live()
        world.push_deploy({"archiver.service": "v2\n", "archiver-bus-health.service": "v2\n"})
        result = world.run(FAKE_INSTALL_FAIL="archiver.service")
        assert result.returncode == 1, result.stderr
        assert world.live() == previous
        probe = "archiver-bus-health.service"
        assert world.installed(probe) == UNITS_V1[probe]

    def test_a_host_config_is_never_installed_as_a_unit(self, world):
        world.push_deploy({"system.slice.d/10-memory-protection.conf": "slice v1\n"})
        result = world.run()
        assert_ok(result)
        assert not installs(world.calls())
        assert "deploy/system.slice.d/10-memory-protection.conf" in result.stderr
        assert "not installed" in result.stderr

    def test_a_differing_host_config_is_a_warning_naming_both_paths(self, world):
        installed = world.sysetc / "sysctl.d" / "99-archiver-memory.conf"
        installed.parent.mkdir(parents=True)
        installed.write_text("older\n")
        world.push_deploy({"99-archiver-memory.conf": "newer\n"})
        result = world.run()
        assert_ok(result)
        assert "deploy/99-archiver-memory.conf" in result.stderr and str(installed) in result.stderr
        assert installed.read_text() == "older\n"


def host_configs() -> dict[str, str]:
    body = re.search(r"^HOST_CONFIGS=\((.*?)^\)", DEPLOY.read_text(), re.M | re.S)
    assert body, "HOST_CONFIGS=( ... ) in deploy.sh"
    return dict(re.findall(r'"([^"=]+)=([^"]+)"', body.group(1)))


class TestTheRepoUnits:
    """The repo's own deploy/ keeps to what deploy.sh assumes (design D1, D12)."""

    REPO_DEPLOY = REPO_ROOT / "deploy"

    def units(self) -> list[Path]:
        return sorted([*self.REPO_DEPLOY.glob("*.service"), *self.REPO_DEPLOY.glob("*.timer")])

    def test_every_service_runs_the_live_release(self):
        services = sorted(self.REPO_DEPLOY.glob("*.service"))
        assert services
        for unit in services:
            lines = unit.read_text().splitlines()
            assert "WorkingDirectory=/srv/archiver/live" in lines, unit.name

    def test_no_unit_names_the_checkout(self):
        for unit in self.units():
            text = "\n".join(
                ln for ln in unit.read_text().splitlines() if not ln.lstrip().startswith("#")
            )
            assert "/home/exedev" not in text, unit.name

    def test_no_unit_syncs(self):
        """R5: syncing is a build step, never a start side effect."""
        for unit in self.units():
            for line in unit.read_text().splitlines():
                if line.startswith("Exec") and " uv " in f" {line} ".replace("/uv ", " uv "):
                    assert "--frozen --no-sync" in line or " sync" not in line, (unit.name, line)
                    assert " run " not in line or "--no-sync" in line, (unit.name, line)
                assert "sync_wheelhouse" not in line or line.lstrip().startswith("#"), unit.name

    def test_no_unit_reads_a_repo_env_or_stamps_a_build(self):
        for unit in self.units():
            for line in unit.read_text().splitlines():
                if line.startswith("EnvironmentFile="):
                    assert line.split("=", 1)[1].lstrip("-").startswith("/etc/archiver/"), line
                assert not (line.startswith("ExecStartPre") and "git " in line), unit.name

    def release_paths(self) -> list[tuple[str, str]]:
        """``(unit, release-relative path)`` for each ``Exec*=`` run from the release."""
        found = []
        for unit in sorted(self.REPO_DEPLOY.glob("*.service")):
            for line in unit.read_text().splitlines():
                if not re.match(r"Exec[A-Za-z]*=", line):
                    continue
                exe = line.split("=", 1)[1].lstrip("-+@!:").split()[0]
                if exe.startswith("/srv/archiver/live/"):
                    found.append((unit.name, exe.removeprefix("/srv/archiver/live/")))
        return found

    def test_every_release_path_a_unit_runs_is_an_executable_in_the_repo(self):
        """CR 7, at the source: what deploy.sh refuses a release for. ``.venv/`` is
        not the repo's: the deploy builds it (the next test)."""
        for unit, rel in self.release_paths():
            if rel.startswith(".venv/"):
                continue
            path = REPO_ROOT / rel
            assert path.is_file() and os.access(path, os.X_OK), (unit, rel)

    def test_the_only_built_path_a_unit_runs_is_the_release_interpreter(self):
        """#338 CR 2: the drift check runs ``.venv/bin/python``, which no checkout
        tracks. deploy.sh builds it on ``$PYTHON`` and refuses a release that lacks
        it, after ``uv sync``; anything else under ``.venv/`` is unchecked here."""
        built = {rel for _, rel in self.release_paths() if rel.startswith(".venv/")}
        assert built <= {".venv/bin/python", ".venv/bin/uvicorn"}, built

    def test_every_service_runs_as_the_service_user(self):
        """archiver#339: never exedev, the account agents and humans use."""
        for unit in sorted(self.REPO_DEPLOY.glob("*.service")):
            lines = unit.read_text().splitlines()
            assert "User=archiver" in lines and "Group=archiver" in lines, unit.name

    def test_no_unit_runs_uv(self):
        """uv wants a cache under $HOME, and the service user has none (archiver#339):
        every unit runs the release venv's own entry points."""
        for unit in sorted(self.REPO_DEPLOY.glob("*.service")):
            for line in unit.read_text().splitlines():
                if re.match(r"Exec[A-Za-z]*=", line):
                    assert "/uv " not in line and " uv " not in line, (unit.name, line)

    @pytest.mark.parametrize(
        "directive",
        ["NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=strict", "ProtectHome=yes"],
    )
    def test_every_service_is_sandboxed(self, directive):
        """ProtectHome= keeps the service user out of ~exedev (its PATs), as processor."""
        for unit in sorted(self.REPO_DEPLOY.glob("*.service")):
            assert directive in unit.read_text().splitlines(), (unit.name, directive)

    def test_each_timer_triggers_a_service_in_deploy(self):
        for timer in sorted(self.REPO_DEPLOY.glob("*.timer")):
            assert (self.REPO_DEPLOY / f"{timer.stem}.service").is_file(), timer.name

    def test_every_file_under_deploy_is_a_unit_a_host_config_or_the_readme(self):
        configs = host_configs()
        for path in sorted(p for p in self.REPO_DEPLOY.rglob("*") if p.is_file()):
            rel = path.relative_to(self.REPO_DEPLOY).as_posix()
            if rel == "README.md":
                continue
            is_unit = "/" not in rel and path.suffix in (".service", ".timer")
            assert is_unit != (rel in configs), rel
        for rel in configs:
            assert (self.REPO_DEPLOY / rel).is_file(), f"HOST_CONFIGS names {rel}, not in deploy/"

    def test_the_readme_installs_each_host_config_where_deploy_compares_it(self):
        readme = (self.REPO_DEPLOY / "README.md").read_text()
        drop_in_loop = '-t "/etc/systemd/system/$d/"' in readme
        for rel, dest in host_configs().items():
            if dest == f"systemd/system/{rel}":
                assert drop_in_loop and rel.split("/")[0] in readme, dest
            else:
                assert f"/etc/{Path(dest).parent}/" in readme, dest
