"""``clients/python/scripts/regen.sh`` writes the tree through the drift gate (#272).

regen.sh and ``scripts/check_client_drift.py`` once each ran their own
``openapi-python-client generate``. The commands matched but the output paths
did not, and the generator's import-fixing post-hook honours the SDK's
``lint.exclude`` (#242) only at the real ``generated/`` path. regen.sh therefore
wrote a tree the gate rejected. The fix keeps one code path: regen.sh dumps the
snapshot, then hands generation to ``check_client_drift.py --write``. These tests
pin that delegation so the two scripts cannot fork again.

Each test runs a copy of regen.sh in a throwaway git repo, with a stub ``uv`` on
``PATH`` that records its working directory and argv. No generator runs.
"""

import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_REGEN = _REPO / "clients" / "python" / "scripts" / "regen.sh"

_DUMPED_SPEC = '{"openapi": "3.1.0"}'

# Records "<cwd>|<argv>" per call; prints a spec for the dump; fails either step on demand.
_UV_STUB = f"""#!/usr/bin/env bash
echo "$PWD|$*" >> "$UV_LOG"
case "$*" in
  *dump_openapi.py*) echo '{_DUMPED_SPEC}'; exit "${{UV_DUMP_EXIT:-0}}" ;;
  *check_client_drift.py*) exit "${{UV_WRITE_EXIT:-0}}" ;;
esac
"""


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A git repo holding only a copy of regen.sh, plus a ``bin/uv`` stub."""
    repo = tmp_path / "repo"
    scripts = repo / "clients" / "python" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "regen.sh").write_text(_REGEN.read_text())
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    stub = tmp_path / "bin" / "uv"
    stub.parent.mkdir()
    stub.write_text(_UV_STUB)
    stub.chmod(0o755)
    return tmp_path


def _regen(sandbox: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the sandboxed regen.sh; return the result and the stub's call log."""
    log = sandbox / "uv.log"
    log.touch()
    result = subprocess.run(
        ["bash", "clients/python/scripts/regen.sh"],
        cwd=sandbox / "repo",
        env={"PATH": f"{sandbox / 'bin'}:/usr/bin:/bin", "UV_LOG": str(log), **env},
        capture_output=True,
        text=True,
    )
    return result, log.read_text().splitlines()


def test_regen_dumps_the_snapshot_then_delegates_the_write(sandbox: Path) -> None:
    result, calls = _regen(sandbox)
    assert result.returncode == 0, result.stderr
    root = (sandbox / "repo").resolve()
    assert calls == [
        f"{root}|run python scripts/dump_openapi.py",
        f"{root}|run python scripts/check_client_drift.py --write archiver",
    ]
    snapshot = root / "clients" / "python" / "archiver-openapi.json"
    assert snapshot.read_text().strip() == _DUMPED_SPEC


def test_regen_never_generates_or_formats_on_its_own(sandbox: Path) -> None:
    """A second generate/format path is the fork #272 removed."""
    _, calls = _regen(sandbox)
    assert not [call for call in calls if "openapi-python-client" in call or "ruff" in call]


def test_regen_fails_when_the_write_fails(sandbox: Path) -> None:
    result, _ = _regen(sandbox, UV_WRITE_EXIT="2")
    assert result.returncode == 2


def test_a_failed_dump_leaves_the_committed_snapshot_intact(sandbox: Path) -> None:
    """Redirecting straight into the snapshot would truncate it before the dump ran."""
    snapshot = sandbox / "repo" / "clients" / "python" / "archiver-openapi.json"
    snapshot.write_text("committed\n")
    result, calls = _regen(sandbox, UV_DUMP_EXIT="1")
    assert result.returncode == 1
    assert snapshot.read_text() == "committed\n"
    assert not [call for call in calls if "check_client_drift.py" in call]
