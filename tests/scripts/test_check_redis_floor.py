"""Behaviour of scripts/check_redis_floor.sh — the Redis broker precondition guard.

Run as an `ExecStartPre` on archiver.service (archiver#109). Two assertions, with
deliberately different severities:

- **Version >= 7.0 — blocks.** A too-old *reachable* broker breaks the consumer
  path (`XAUTOCLAIM`), so the producer refuses to start.
- **`maxmemory` non-zero — warns only (archiver#128).** An uncapped broker makes
  `maxmemory-policy noeviction` inert, but the producer itself works fine against
  it; refusing to start the API over a broker tuning value would be a
  self-inflicted outage.

Otherwise soft by design: exit 0 (letting archiver start) when the bus is dormant
or the broker is unreachable. These tests drive it with a stub `redis-cli` on PATH
so no live Redis is required and each branch is exercised deterministically.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_redis_floor.sh"


def _stub_redis_cli(
    tmp_path: Path,
    *,
    version: str | None,
    tls: bool = True,
    sleep: float = 0,
    maxmemory: str | None = "536870912",
) -> Path:
    """Write a fake `redis-cli` to a bin dir; return the dir for PATH.

    `--help` output includes `--tls` iff `tls`. Any other invocation optionally
    sleeps `sleep` seconds (to simulate a hanging connection), then answers by
    subcommand: `INFO server` prints a `redis_version:` line iff `version` is
    given, and `CONFIG GET maxmemory` prints the two-line name/value reply iff
    `maxmemory` is given. `None` means "print nothing" — an unreachable or failed
    connection. `maxmemory` defaults to a capped broker so the tests that predate
    the cap check (archiver#128) exercise their own branch without tripping it.
    """
    binder = tmp_path / "bin"
    binder.mkdir()
    help_tls = "  --tls    Use TLS.\n" if tls else ""
    sleep_line = f"sleep {sleep}\n" if sleep else ""
    version_line = f'  echo "redis_version:{version}"' if version is not None else "  true"
    maxmemory_lines = (
        f'  echo "maxmemory"\n  echo "{maxmemory}"' if maxmemory is not None else "  true"
    )
    (binder / "redis-cli").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "--help" ]]; then\n'
        f'  printf "usage: redis-cli\\n{help_tls}"\n'
        "  exit 0\n"
        "fi\n"
        f"{sleep_line}"
        'case "$*" in\n'
        "  *'CONFIG GET maxmemory'*)\n"
        f"{maxmemory_lines}\n"
        "    ;;\n"
        "  *'INFO server'*)\n"
        f"{version_line}\n"
        "    ;;\n"
        "esac\n"
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


def test_uncapped_broker_warns_but_does_not_block(tmp_path: Path) -> None:
    """`maxmemory 0` makes noeviction inert — warn loudly, never block.

    archiver#128, CR finding 1. The file-level parity test
    (tests/deploy/test_installed_redis_dropin_matches_repo.py) compares the
    drop-in on disk against the repo; it cannot see a broker whose *running*
    config was changed by `CONFIG SET`, which is exactly how the cap was applied.
    This is the check that observes the live value.

    Warn-only, unlike the version floor: an uncapped broker does not break the
    producer, so refusing to start the API over it would turn a tuning drift into
    an outage.
    """
    bindir = _stub_redis_cli(tmp_path, version="7.0.15", maxmemory="0")
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://localhost:6379/0"})
    assert result.returncode == 0, result.stderr
    assert "maxmemory is 0" in result.stderr
    assert "noeviction" in result.stderr


def test_capped_broker_reports_the_cap(tmp_path: Path) -> None:
    bindir = _stub_redis_cli(tmp_path, version="7.0.15", maxmemory="536870912")
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://localhost:6379/0"})
    assert result.returncode == 0, result.stderr
    assert "maxmemory is 0" not in result.stderr
    assert "536870912" in result.stdout


def test_unreadable_maxmemory_is_soft(tmp_path: Path) -> None:
    """CONFIG GET returning nothing must not be mistaken for an uncapped broker.

    A restricted ACL or a killed probe yields an empty reply; warning "uncapped"
    there would train the operator to ignore the warning that matters.
    """
    bindir = _stub_redis_cli(tmp_path, version="7.0.15", maxmemory=None)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://localhost:6379/0"})
    assert result.returncode == 0, result.stderr
    assert "maxmemory is 0" not in result.stderr
    assert "could not read maxmemory" in result.stderr


def test_dormant_bus_does_not_probe_maxmemory(tmp_path: Path) -> None:
    """URL unset → no broker contact at all, cap check included."""
    bindir = _stub_redis_cli(tmp_path, version="7.0.15", maxmemory="0")
    result = _run(bindir, {})
    assert result.returncode == 0
    assert "maxmemory" not in result.stderr


@pytest.mark.parametrize("tool", ["bash", "sed", "tr"])
def test_required_tools_exist(tool: str) -> None:
    """Guard against the stub-PATH tests silently passing because a tool the
    script relies on is missing from the environment."""
    assert shutil.which(tool) is not None
