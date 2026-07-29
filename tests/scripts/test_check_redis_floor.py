"""Behaviour of scripts/check_redis_floor.sh — the Redis >=7.0 floor guard.

Run as an `ExecStartPre` on archiver.service (archiver#109). The guard is soft
by design: it blocks the producer only on a genuinely-too-old *reachable* broker,
and exits 0 (letting archiver start) when the bus is dormant or the broker is
unreachable. These tests drive it with a stub `redis-cli` on PATH so no live
Redis is required and each branch is exercised deterministically.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_redis_floor.sh"


def _stub_redis_cli(
    tmp_path: Path, *, version: str | None, tls: bool = True, sleep: float = 0
) -> Path:
    """Write a fake `redis-cli` to a bin dir; return the dir for PATH.

    `--help` output includes `--tls` iff `tls`. Any other invocation optionally
    sleeps `sleep` seconds (to simulate a hanging connection) then prints a
    `redis_version:` line iff `version` is given (else nothing, simulating an
    unreachable/failed connection).
    """
    binder = tmp_path / "bin"
    binder.mkdir()
    help_tls = "  --tls    Use TLS.\n" if tls else ""
    sleep_line = f"sleep {sleep}\n" if sleep else ""
    version_line = f'echo "redis_version:{version}"' if version is not None else "true"
    (binder / "redis-cli").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "--help" ]]; then\n'
        f'  printf "usage: redis-cli\\n{help_tls}"\n'
        "  exit 0\n"
        "fi\n"
        f"{sleep_line}"
        f"{version_line}\n"
    )
    (binder / "redis-cli").chmod(0o755)
    return binder


def _run(bindir: Path | None, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    path = f"{bindir}:/usr/bin:/bin" if bindir else "/usr/bin:/bin"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={"PATH": path, **env},
        text=True,
        capture_output=True,
    )


def test_unset_url_skips(tmp_path: Path) -> None:
    """Bus dormant (URL unset) → exit 0, no broker contact."""
    bindir = _stub_redis_cli(tmp_path, version="7.0.15")
    result = _run(bindir, {})
    assert result.returncode == 0
    assert "dormant" in result.stdout


def test_version_at_floor_passes(tmp_path: Path) -> None:
    bindir = _stub_redis_cli(tmp_path, version="7.0.15")
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://localhost:6379/0"})
    assert result.returncode == 0, result.stderr
    assert "meets the >=7.0 floor" in result.stdout


def test_version_above_floor_passes(tmp_path: Path) -> None:
    bindir = _stub_redis_cli(tmp_path, version="8.2.0")
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://localhost:6379/0"})
    assert result.returncode == 0, result.stderr


def test_version_below_floor_blocks(tmp_path: Path) -> None:
    bindir = _stub_redis_cli(tmp_path, version="6.2.14")
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://localhost:6379/0"})
    assert result.returncode == 1
    assert "below the >=7.0" in result.stderr


def test_unreachable_broker_is_soft(tmp_path: Path) -> None:
    """No version readable (connection failed) → soft-skip, exit 0."""
    bindir = _stub_redis_cli(tmp_path, version=None)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://localhost:6399/0"})
    assert result.returncode == 0
    assert "not blocking start" in result.stderr


def test_hanging_broker_is_bounded_by_timeout(tmp_path: Path) -> None:
    """A redis-cli that hangs must not stall the ExecStartPre: the timeout kills
    it and the check soft-skips. Regression for the rediss://-vs-plaintext hang."""
    bindir = _stub_redis_cli(tmp_path, version="7.0.15", sleep=30)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            "PATH": f"{bindir}:/usr/bin:/bin",
            "ARCHIVER_REDIS_URL": "redis://localhost:6379/0",
            "ARCHIVER_REDIS_FLOOR_TIMEOUT": "1",
        },
        text=True,
        capture_output=True,
        timeout=15,  # far above the 1s floor timeout; fails loud if it hangs
    )
    assert result.returncode == 0
    assert "not blocking start" in result.stderr


def test_rediss_url_without_tls_cli_warns(tmp_path: Path) -> None:
    """A rediss:// URL against a non-TLS redis-cli warns (the check would no-op)."""
    bindir = _stub_redis_cli(tmp_path, version=None, tls=False)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "rediss://localhost:6379/0"})
    assert result.returncode == 0  # still soft
    assert "lacks TLS support" in result.stderr


def test_rediss_url_with_tls_cli_does_not_warn(tmp_path: Path) -> None:
    bindir = _stub_redis_cli(tmp_path, version="7.0.15", tls=True)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "rediss://localhost:6379/0"})
    assert result.returncode == 0, result.stderr
    assert "lacks TLS support" not in result.stderr


def test_redis_cli_absent_is_soft() -> None:
    """No redis-cli on PATH at all → cannot verify, do not block."""
    # A PATH with only bash's own dir would still find /usr/bin tools; instead
    # point at an empty dir plus a minimal set that excludes redis-cli. bash,
    # sed, tr, grep live in /usr/bin — which also has redis-cli — so simulate
    # absence via a dedicated dir holding only the needed coreutils symlinks.
    with tempfile.TemporaryDirectory() as d:
        bindir = Path(d)
        for tool in ("bash", "sed", "tr", "grep", "env"):
            src = shutil.which(tool)
            if src:
                (bindir / tool).symlink_to(src)
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env={"PATH": str(bindir), "ARCHIVER_REDIS_URL": "redis://localhost:6379/0"},
            text=True,
            capture_output=True,
        )
    assert result.returncode == 0
    assert "redis-cli not found" in result.stderr


@pytest.mark.parametrize("tool", ["bash", "sed", "tr"])
def test_required_tools_exist(tool: str) -> None:
    """Guard against the stub-PATH tests silently passing because a tool the
    script relies on is missing from the environment."""
    assert shutil.which(tool) is not None
