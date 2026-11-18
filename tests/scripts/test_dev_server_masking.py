"""``scripts/dev_server.sh`` never prints a password (archiver#448).

The script used to print the dev database URL whole: in the dry-run report, on
the migrate line and on the launch line. Its output lands in background-task
logs and agent transcripts, so the ``archiver_dev`` password went with it. Every
URL the script prints now goes through one function, ``mask_url``. It keeps what
a reader needs to confirm the target (user, host, port, database) and replaces
the password, and any query string, with ``***``.

The sentinel password holds ``@``, ``:`` and ``%``, the characters a URL must
percent-encode. Each of its four pieces is distinctive, so the tests catch a
partial leak as well as a whole one, raw or encoded, on stdout or stderr. The
refusal paths are included.
"""

import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev_server.sh"

PIECES = ("Zq7sent", "Kx9col", "Wm4pct", "Vb2end")
RAW = f"{PIECES[0]}@{PIECES[1]}:{PIECES[2]}%{PIECES[3]}"
ENC = quote(RAW, safe="")  # Zq7sent%40Kx9col%3AWm4pct%25Vb2end

WITHHELD = "(value withheld: not a well-formed URL)"


def db_url(name: str, password: str = ENC) -> str:
    return f"postgresql+asyncpg://archiver:{password}@localhost:5432/{name}"


MASKED_TEST = "postgresql+asyncpg://archiver:***@localhost:5432/archiver_test"

FAKE_UV = """\
#!/usr/bin/env bash
[[ -z "${PROBE:-}" ]] || env > "$PROBE"
exit 0
"""


@pytest.fixture
def fake_uv(tmp_path: Path) -> Path:
    """A ``uv`` that runs nothing, so the launch path runs end to end."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(0o755)
    return bin_dir


def run(env: dict[str, str], *, launch_bin: Path | None = None) -> subprocess.CompletedProcess[str]:
    """The dry run, or with *launch_bin* the real launch path through a fake ``uv``."""
    base = {"PATH": "/usr/bin:/bin", "ARCHIVER_DEV_SERVER_SKIP_ENV_FILES": "1"}
    if launch_bin is None:
        base["ARCHIVER_DEV_SERVER_DRY_RUN"] = "1"
    else:
        base["PATH"] = f"{launch_bin}:/usr/bin:/bin"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={**base, **env},
        text=True,
        capture_output=True,
        timeout=30,
    )


def assert_no_password(result: subprocess.CompletedProcess[str]) -> None:
    """No piece of the sentinel, in any case, on stdout or stderr."""
    out = (result.stdout + result.stderr).lower()
    for piece in PIECES:
        assert piece.lower() not in out, (piece, result.stdout, result.stderr)
    assert ENC.lower() not in out


def report(stdout: str, key: str) -> str:
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1 :]
    raise AssertionError(f"no {key}= line in dry-run output:\n{stdout}")


# --- No path prints the password ---------------------------------------------

# URLs that pass the database guard, each with the sentinel in it some way.
SERVED_URLS = {
    "encoded": db_url("archiver_test"),
    "raw @ and : in the password": db_url("archiver_test", RAW),
    "raw / in the password": db_url("archiver_test", f"{PIECES[0]}/{PIECES[1]}"),
    "raw # in the password": db_url("archiver_test", f"{PIECES[0]}#{PIECES[1]}"),
    "password in the query": (
        f"postgresql+asyncpg://archiver@localhost:5432/archiver_test?password={ENC}"
    ),
}


@pytest.mark.parametrize("url", SERVED_URLS.values(), ids=SERVED_URLS.keys())
def test_dry_run_prints_no_password(url: str) -> None:
    result = run({"TEST_DATABASE_URL": url})
    assert result.returncode == 0, result.stderr
    assert_no_password(result)


@pytest.mark.parametrize("url", SERVED_URLS.values(), ids=SERVED_URLS.keys())
def test_launch_prints_no_password(url: str, fake_uv: Path) -> None:
    """The migrate and launch lines, the path the 2026-10-28 leak took.

    The script's own lines only: the fake ``uv`` runs neither alembic nor
    uvicorn, whose output is outside ``mask_url`` (a known limit on #448).
    """
    result = run({"ARCHIVER_DEV_DATABASE_URL": url}, launch_bin=fake_uv)
    assert result.returncode == 0, result.stderr
    assert "alembic upgrade head" in result.stdout
    assert_no_password(result)


REFUSALS = {
    "production name": {"TEST_DATABASE_URL": db_url("archiver")},
    "raw ? hides the name": {
        "TEST_DATABASE_URL": db_url("archiver_test", f"{PIECES[0]}?{PIECES[1]}")
    },
    # db_name reads `Wm4pct@localhost/x` here: the name itself holds a piece.
    "raw @ and / put a piece in the name": {
        "TEST_DATABASE_URL": f"postgresql://archiver:{PIECES[0]}@{PIECES[1]}/{PIECES[2]}@localhost/x"
    },
    "port 8000": {"TEST_DATABASE_URL": db_url("archiver_test"), "ARCHIVER_DEV_PORT": "8000"},
    "same broker": {
        "TEST_DATABASE_URL": db_url("archiver_test"),
        "ARCHIVER_REDIS_URL": f"redis://default:{ENC}@localhost:6379/0",
        "ARCHIVER_DEV_REDIS_URL": f"redis://default:{ENC}@127.0.0.1:6379/1",
    },
    "shared broker": {
        "TEST_DATABASE_URL": db_url("archiver_test"),
        "ARCHIVER_DEV_REDIS_URL": f"redis://default:{ENC}@broker:6379/0",
    },
    "raw @ in a redis password": {
        "TEST_DATABASE_URL": db_url("archiver_test"),
        "ARCHIVER_DEV_REDIS_URL": f"redis://:{RAW}@127.0.0.1:6380/0",
    },
    "notifier userinfo": {
        "TEST_DATABASE_URL": db_url("archiver_test"),
        "ARCHIVER_DEV_NOTIFIER_BASE_URL": f"http://u:{ENC}@notifier:9001",
        "ARCHIVER_DEV_NOTIFIER_API_KEY": "nk_dev-test",
    },
}


@pytest.mark.parametrize("env", REFUSALS.values(), ids=REFUSALS.keys())
def test_refusals_print_no_password(env: dict[str, str]) -> None:
    result = run(env)
    assert result.returncode != 0
    assert result.stderr
    assert_no_password(result)


def test_dev_broker_and_power_map_reports_print_no_password() -> None:
    result = run(
        {
            "TEST_DATABASE_URL": db_url("archiver_test"),
            "ARCHIVER_DEV_REDIS_URL": f"redis://:{ENC}@127.0.0.1:6380/0",
            "ARCHIVER_DEV_POWER_MAP_API_KEY": "pm-dev-key",
            "ARCHIVER_DEV_POWER_MAP_BASE_URL": f"https://u:{ENC}@pm-staging.test",
        }
    )
    assert result.returncode == 0, result.stderr
    assert_no_password(result)


# --- What the mask keeps -----------------------------------------------------


def test_dry_run_keeps_user_host_port_and_database() -> None:
    result = run({"TEST_DATABASE_URL": db_url("archiver_test")})
    assert result.returncode == 0, result.stderr
    assert report(result.stdout, "ARCHIVER_DATABASE_URL") == MASKED_TEST
    assert report(result.stdout, "MIGRATE") == MASKED_TEST


def test_launch_lines_are_masked(fake_uv: Path) -> None:
    result = run({"TEST_DATABASE_URL": db_url("archiver_test")}, launch_bin=fake_uv)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert f"dev_server: alembic upgrade head → {MASKED_TEST}" in lines
    assert f"dev_server: port 8001 → {MASKED_TEST}" in lines


def test_the_child_still_gets_the_real_urls(tmp_path: Path, fake_uv: Path) -> None:
    """Masking changes what is printed, never what uvicorn connects with."""
    probe = tmp_path / "env"
    redis = f"redis://:{ENC}@127.0.0.1:6380/0"
    result = run(
        {
            "TEST_DATABASE_URL": db_url("archiver_test"),
            "ARCHIVER_DEV_REDIS_URL": redis,
            "ARCHIVER_DEV_SKIP_MIGRATE": "1",
            "PROBE": str(probe),
        },
        launch_bin=fake_uv,
    )
    assert result.returncode == 0, result.stderr
    seen = dict(line.split("=", 1) for line in probe.read_text().splitlines() if "=" in line)
    assert seen["ARCHIVER_DATABASE_URL"] == db_url("archiver_test")
    assert seen["ARCHIVER_REDIS_URL"] == redis


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://archiver@localhost:5432/archiver_test",  # user, no password
        "postgresql+asyncpg://localhost:5432/archiver_test",  # no credentials
        "postgresql://[::1]:5432/archiver_test",
    ],
)
def test_a_url_without_a_password_prints_whole(url: str) -> None:
    result = run({"TEST_DATABASE_URL": url})
    assert result.returncode == 0, result.stderr
    assert report(result.stdout, "ARCHIVER_DATABASE_URL") == url


def test_an_empty_password_is_masked_too() -> None:
    """``user:@host`` still says a password field was there."""
    result = run({"TEST_DATABASE_URL": db_url("archiver_test", "")})
    assert result.returncode == 0, result.stderr
    assert report(result.stdout, "ARCHIVER_DATABASE_URL") == MASKED_TEST


def test_a_query_is_withheld() -> None:
    """``?password=`` reaches asyncpg's ``connect()``, so no query value prints."""
    url = "postgresql+asyncpg://archiver@localhost:5432/archiver_test?sslmode=require"
    result = run({"TEST_DATABASE_URL": url})
    assert result.returncode == 0, result.stderr
    assert report(result.stdout, "ARCHIVER_DATABASE_URL") == (
        "postgresql+asyncpg://archiver@localhost:5432/archiver_test?***"
    )


def test_a_raw_at_sign_masks_up_to_the_last_one() -> None:
    """Credentials end at the authority's last ``@``, as urlsplit and redis-py read it."""
    result = run({"TEST_DATABASE_URL": db_url("archiver_test", RAW)})
    assert result.returncode == 0, result.stderr
    assert report(result.stdout, "ARCHIVER_DATABASE_URL") == MASKED_TEST


@pytest.mark.parametrize(
    "password", [f"{PIECES[0]}/{PIECES[1]}", f"{PIECES[0]}#{PIECES[1]}"], ids=["slash", "hash"]
)
def test_an_ambiguous_url_is_withheld_whole(password: str) -> None:
    """An ``@`` past the authority means a raw delimiter in the password: fail closed."""
    result = run({"TEST_DATABASE_URL": db_url("archiver_test", password)})
    assert result.returncode == 0, result.stderr
    assert report(result.stdout, "ARCHIVER_DATABASE_URL") == WITHHELD
    assert report(result.stdout, "MIGRATE") == WITHHELD


def test_db_refusal_still_names_the_database() -> None:
    result = run({"TEST_DATABASE_URL": db_url("archiver")})
    assert result.returncode == 1
    assert "refusing to start against database 'archiver'" in result.stderr


def test_redis_refusals_name_the_masked_url() -> None:
    result = run(
        {
            "TEST_DATABASE_URL": db_url("archiver_test"),
            "ARCHIVER_REDIS_URL": f"redis://default:{ENC}@broker:6379/0",
            "ARCHIVER_DEV_REDIS_URL": f"redis://default:{ENC}@broker:6379/1",
        }
    )
    assert result.returncode == 1
    assert "same broker" in result.stderr
    assert "redis://default:***@broker:6379/1" in result.stderr

    result = run(
        {
            "TEST_DATABASE_URL": db_url("archiver_test"),
            "ARCHIVER_DEV_REDIS_URL": f"redis://:{RAW}@127.0.0.1:6380/0",
        }
    )
    assert result.returncode == 1
    assert "not a local broker" in result.stderr
    assert "redis://:***@127.0.0.1:6380/0" in result.stderr


def test_reports_are_masked() -> None:
    result = run(
        {
            "TEST_DATABASE_URL": db_url("archiver_test"),
            "ARCHIVER_DEV_REDIS_URL": f"redis://:{ENC}@127.0.0.1:6380/0",
            "ARCHIVER_DEV_POWER_MAP_API_KEY": "pm-dev-key",
            "ARCHIVER_DEV_POWER_MAP_BASE_URL": f"https://u:{ENC}@pm-staging.test",
        }
    )
    assert result.returncode == 0, result.stderr
    assert report(result.stdout, "REDIS") == "redis://:***@127.0.0.1:6380/0"
    assert report(result.stdout, "POWER_MAP") == "https://u:***@pm-staging.test (dev key)"


def test_a_value_that_is_not_a_url_is_withheld() -> None:
    """A bare redis ``host:port`` passes the guard; it could be a pasted secret."""
    result = run(
        {"TEST_DATABASE_URL": db_url("archiver_test"), "ARCHIVER_DEV_REDIS_URL": "127.0.0.1:6380"}
    )
    assert result.returncode == 0, result.stderr
    assert report(result.stdout, "REDIS") == WITHHELD
