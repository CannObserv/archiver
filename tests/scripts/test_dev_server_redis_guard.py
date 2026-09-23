"""The dev-server launcher must isolate the Redis change bus from production.

`scripts/dev_server.sh` sources `/etc/archiver/.env`, which on the VM sets the
production `ARCHIVER_REDIS_URL`. A dev server that inherited it would publish
onto prod's `info.changes` stream — the same leak class as the 2026-07-18
database incident, now for the bus (archiver#109).

The guard's contract (asserted here via the dry-run report):

  - No dev override        → the bus runs dormant; prod's URL is NOT inherited.
  - Explicit dev override  → that distinct URL is used.
  - Dev override on prod's host:port → refuse to start, whatever the DB
                             index (archiver#240: the broker runs `databases 1`
                             and denies SELECT, so an index is no boundary).

Each case is driven with env files skipped, so the test controls the exact
`ARCHIVER_REDIS_URL` / `ARCHIVER_DEV_REDIS_URL` inputs the launcher sees.
"""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev_server.sh"

# A valid disposable dev database so the launcher clears the DB guard and
# proceeds to the Redis resolution the tests actually exercise.
_TEST_DB = "postgresql+asyncpg://u:p@localhost:5432/archiver_test"


def _run(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "ARCHIVER_DEV_SERVER_DRY_RUN": "1",
        "ARCHIVER_DEV_SERVER_SKIP_ENV_FILES": "1",
        "TEST_DATABASE_URL": _TEST_DB,
        **extra_env,
    }
    return subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)


def _redis_line(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("REDIS="):
            return line[len("REDIS=") :]
    raise AssertionError(f"no REDIS= line in dry-run output:\n{stdout}")


def test_no_override_runs_bus_dormant() -> None:
    """Neither var set → the dev bus is dormant."""
    result = _run({})
    assert result.returncode == 0, result.stderr
    assert _redis_line(result.stdout) == "(dormant)"


def test_prod_url_is_not_inherited() -> None:
    """Prod's ARCHIVER_REDIS_URL present but no dev override → still dormant.

    This is the core leak guard: the production URL sourced from
    /etc/archiver/.env must never drive the dev server.
    """
    result = _run({"ARCHIVER_REDIS_URL": "redis://localhost:6379/0"})
    assert result.returncode == 0, result.stderr
    assert _redis_line(result.stdout) == "(dormant)"


def test_explicit_dev_override_is_used() -> None:
    """A distinct ARCHIVER_DEV_REDIS_URL is adopted for the dev server."""
    result = _run(
        {
            "ARCHIVER_REDIS_URL": "redis://localhost:6379/0",
            "ARCHIVER_DEV_REDIS_URL": "redis://localhost:6380/0",
        }
    )
    assert result.returncode == 0, result.stderr
    assert _redis_line(result.stdout) == "redis://localhost:6380/0"


def test_dev_override_equal_to_prod_is_refused() -> None:
    """A dev override equal to the production URL is refused outright."""
    result = _run(
        {
            "ARCHIVER_REDIS_URL": "redis://localhost:6379/0",
            "ARCHIVER_DEV_REDIS_URL": "redis://localhost:6379/0",
        }
    )
    assert result.returncode == 1
    assert "same broker" in result.stderr


def test_cosmetically_different_but_same_broker_is_refused() -> None:
    """127.0.0.1 vs localhost and an omitted default port/db address the same
    broker — normalized identity catches what raw string equality would miss."""
    result = _run(
        {
            "ARCHIVER_REDIS_URL": "redis://localhost:6379/0",
            "ARCHIVER_DEV_REDIS_URL": "redis://127.0.0.1/0",  # default port omitted
        }
    )
    assert result.returncode == 1
    assert "same broker" in result.stderr


def test_distinct_db_index_on_same_broker_is_refused() -> None:
    """A different DB index on prod's host:port is the same broker (archiver#240).

    The broker runs `databases 1` and archiver's ACL has no `+select`, so
    `.../1` cannot connect at all; and an index was never a boundary — Redis
    ACLs cannot partition by it. Refuse at launch rather than let it surface as
    a publisher-init failure that reads like dormancy.
    """
    result = _run(
        {
            "ARCHIVER_REDIS_URL": "redis://default:s3cret@broker:6379/0",
            "ARCHIVER_DEV_REDIS_URL": "redis://default:s3cret@broker:6379/1",
        }
    )
    assert result.returncode == 1
    assert "same broker" in result.stderr
    assert "s3cret" not in result.stderr  # names host:port, never prod's credentials


def test_refusal_names_a_local_throwaway_not_a_db_index() -> None:
    """The refusal points at the supported alternative, not the retracted `.../1`."""
    result = _run(
        {
            "ARCHIVER_REDIS_URL": "redis://localhost:6379/0",
            "ARCHIVER_DEV_REDIS_URL": "redis://localhost:6379/0",
        }
    )
    assert result.returncode == 1
    assert "throwaway" in result.stderr
    assert "DB index (e.g." not in result.stderr


def test_dev_override_without_prod_set_is_used() -> None:
    """Dev override set, prod unset → override used, equality guard not tripped
    (empty prod URL must not spuriously match a non-empty override)."""
    result = _run({"ARCHIVER_DEV_REDIS_URL": "redis://localhost:6380/0"})
    assert result.returncode == 0, result.stderr
    assert _redis_line(result.stdout) == "redis://localhost:6380/0"


def test_bracketed_ipv6_with_omitted_port_is_the_same_broker() -> None:
    """`[::1]` with and without the default port is one broker — and loopback,
    like localhost. A bracketed host must not be split on its inner colons."""
    result = _run(
        {
            "ARCHIVER_REDIS_URL": "redis://localhost:6379/0",
            "ARCHIVER_DEV_REDIS_URL": "redis://[::1]/0",
        }
    )
    assert result.returncode == 1
    assert "same broker" in result.stderr


def test_bracketed_ipv6_on_a_distinct_port_is_allowed() -> None:
    """The bracket parse still reads an explicit port, so a throwaway on
    [::1]:6380 is distinct from prod's [::1]:6379."""
    result = _run(
        {
            "ARCHIVER_REDIS_URL": "redis://[::1]:6379/0",
            "ARCHIVER_DEV_REDIS_URL": "redis://[::1]:6380/0",
        }
    )
    assert result.returncode == 0, result.stderr
    assert _redis_line(result.stdout) == "redis://[::1]:6380/0"


def test_distinct_unix_sockets_are_distinct_brokers() -> None:
    """A unix:// URL's identity is its socket path — not a TCP loopback default
    that every socket (and prod on localhost:6379) would collapse onto."""
    result = _run(
        {
            "ARCHIVER_REDIS_URL": "redis://localhost:6379/0",
            "ARCHIVER_DEV_REDIS_URL": "unix:///tmp/archiver-dev-redis.sock",
        }
    )
    assert result.returncode == 0, result.stderr
    assert _redis_line(result.stdout) == "unix:///tmp/archiver-dev-redis.sock"


def test_same_unix_socket_is_refused() -> None:
    """The same socket path, whatever its ?db= query, is the same broker."""
    result = _run(
        {
            "ARCHIVER_REDIS_URL": "unix:///run/redis/redis.sock?db=0",
            "ARCHIVER_DEV_REDIS_URL": "unix://u:p@/run/redis/redis.sock?db=1",
        }
    )
    assert result.returncode == 1
    assert "same broker" in result.stderr
