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
    stderr: str = "",
    exit_code: int = 0,
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
    fail_lines = (
        # %b, not %s: a multi-line `stderr` arrives here as a repr with an
        # escaped newline, and only %b expands it back into two lines.
        f'  printf "%b\\n" {stderr!r} >&2\n  exit {exit_code}\n' if stderr or exit_code else ""
    )
    (binder / "redis-cli").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "--help" ]]; then\n'
        f'  printf "usage: redis-cli\\n{help_tls}"\n'
        "  exit 0\n"
        "fi\n"
        f"{sleep_line}"
        f"{fail_lines}"
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
        for tool in ("bash", "sed", "tr", "grep", "env", "mktemp", "timeout"):
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

    archiver#128, CR finding 1. The file-level parity test moved to
    CannObserv/broker with the drop-in it compares (archiver#193 D6), and it
    could never see a broker whose *running* config was changed by `CONFIG SET`
    in any case - which is exactly how the cap is applied. This is the check
    that observes the live value, and it stays with each client.

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


@pytest.mark.parametrize("tool", ["bash", "sed", "tr", "mktemp"])
def test_required_tools_exist(tool: str) -> None:
    """Guard against the stub-PATH tests silently passing because a tool the
    script relies on is missing from the environment."""
    assert shutil.which(tool) is not None


# --- auth failure vs unreachability (archiver#195) --------------------------
#
# Before this, `redis_probe` sent stderr to /dev/null and judged only stdout, so
# every no-output failure printed the same line: "could not read redis_version
# (broker unreachable?)". During CannObserv/broker#1's cutover that line was on
# every start of two services for days, describing an authentication problem
# while naming a network one - and it was believed, because the broker really
# had been briefly unreachable for an unrelated DNS reason.

_WRONGPASS = "AUTH failed: WRONGPASS invalid username-password pair or user is disabled."
_NOAUTH = "NOAUTH Authentication required."
_REFUSED = "Could not connect to Redis at broker:6379: Connection refused"


@pytest.mark.parametrize("message", [_WRONGPASS, _NOAUTH], ids=["wrongpass", "noauth"])
def test_auth_failure_is_reported_as_authentication(tmp_path: Path, message: str) -> None:
    """The operator must be sent to the credential, not to the network."""
    bindir = _stub_redis_cli(tmp_path, version=None, stderr=message, exit_code=1)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://:pw@broker:6379/0"})

    assert result.returncode == 0
    assert "authenticate" in result.stderr.lower()
    assert "unreachable" not in result.stderr.lower()


def test_auth_failure_names_the_empty_username_trap(tmp_path: Path) -> None:
    """The single most likely cause, and the one that costs the most time.

    `redis://:pw@host` authenticates for redis-py and fails for redis-cli: the
    latter sends a two-argument ``AUTH "" pw`` against a user that does not
    exist. So the service starts green while this probe cannot connect at all.
    Naming it in the message turns a post-cutover finding into a five-second
    one.
    """
    bindir = _stub_redis_cli(tmp_path, version=None, stderr=_WRONGPASS, exit_code=1)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://:pw@broker:6379/0"})

    assert "default:" in result.stderr


def test_auth_failure_says_the_floor_is_unverified(tmp_path: Path) -> None:
    """Silence about the floor is what made this survive.

    A probe that cannot read the version has not *passed* the >=7.0 check, it
    has skipped it. Saying so is the difference between a guard that is known
    to be off and one that is assumed to be on.
    """
    bindir = _stub_redis_cli(tmp_path, version=None, stderr=_WRONGPASS, exit_code=1)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://:pw@broker:6379/0"})

    assert "unverified" in result.stderr.lower()


def test_auth_failure_does_not_block_the_start(tmp_path: Path) -> None:
    """Deliberately NOT blocking, against #195's own suggestion.

    The reasoning that suggestion rests on - "a probe that cannot authenticate
    is evidence the service cannot either" - is exactly what this bug
    disproves. `redis://:pw@host` fails for redis-cli and **succeeds for
    redis-py**, so the probe's verdict is not the service's. Blocking on it
    would have converted this latent trap into a total outage of both archiver
    and replicator at the cutover, for a URL that worked.

    Blocking stays reserved for the one case where the shell client and the
    application client cannot disagree: a version string that was read, and is
    below 7.0.
    """
    bindir = _stub_redis_cli(tmp_path, version=None, stderr=_WRONGPASS, exit_code=1)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://:pw@broker:6379/0"})

    assert result.returncode == 0


def test_unreachable_broker_is_still_reported_as_unreachable(tmp_path: Path) -> None:
    """The other half of the distinction: a real connection failure must not
    start blaming the credential."""
    bindir = _stub_redis_cli(tmp_path, version=None, stderr=_REFUSED, exit_code=1)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://default:pw@broker:6379/0"})

    assert result.returncode == 0
    assert "unreachable" in result.stderr.lower()
    assert "authenticate" not in result.stderr.lower()


def test_silent_failure_claims_neither_cause(tmp_path: Path) -> None:
    """A timeout kill leaves no stderr at all. With nothing to classify, the
    message must not guess - naming a cause it cannot know is how the original
    line misled for days."""
    bindir = _stub_redis_cli(tmp_path, version=None, stderr="", exit_code=1)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://default:pw@broker:6379/0"})

    assert result.returncode == 0
    assert "could not reach or authenticate" in result.stderr.lower()


def test_auth_failure_skips_the_cap_probe(tmp_path: Path) -> None:
    """A second probe against a broker that just refused authentication can
    only produce a second misleading line."""
    bindir = _stub_redis_cli(tmp_path, version=None, stderr=_WRONGPASS, exit_code=1)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://:pw@broker:6379/0"})

    assert "maxmemory" not in result.stderr.lower()
    assert "maxmemory" not in result.stdout.lower()


_CLI_PASSWORD_WARNING = (
    "Warning: Using a password with '-a' or '-u' option on the command line "
    "interface may not be safe."
)


def test_broker_quote_excludes_the_cli_s_own_warning(tmp_path: Path) -> None:
    """redis-cli prints that advisory on every `-u` call, so quoting it back
    under "broker said:" buries the real error and blames the server for the
    client's warning. Observed live against the authenticated broker."""
    bindir = _stub_redis_cli(
        tmp_path,
        version=None,
        stderr=f"{_CLI_PASSWORD_WARNING}\n{_WRONGPASS}",
        exit_code=1,
    )
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://:pw@broker:6379/0"})

    assert "may not be safe" not in result.stderr
    assert "WRONGPASS" in result.stderr


def test_the_cli_warning_alone_does_not_read_as_an_auth_failure(tmp_path: Path) -> None:
    """The filter has to run BEFORE classification, not just before printing.

    That advisory contains none of the auth tokens, so it classifies as
    `unknown` either way - but a future pattern that matched it would silently
    turn every timed-out probe into a confident wrong diagnosis. Pin the order.
    """
    bindir = _stub_redis_cli(tmp_path, version=None, stderr=_CLI_PASSWORD_WARNING, exit_code=1)
    result = _run(bindir, {"ARCHIVER_REDIS_URL": "redis://default:pw@broker:6379/0"})

    assert "could not reach or authenticate" in result.stderr.lower()
