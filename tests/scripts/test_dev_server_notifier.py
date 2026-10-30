"""The dev-server launcher maps a dev Notifier pair, or runs Notifier dormant (archiver#368).

Operator decision D3. ``scripts/dev_server.sh`` drops every ``ARCHIVER_NOTIFIER_*``
it inherited, then maps ``ARCHIVER_DEV_NOTIFIER_BASE_URL`` and
``ARCHIVER_DEV_NOTIFIER_API_KEY`` onto the gate's variables, setting the flag only
when both are present. A dev URL on port 9000 (production Notifier) is refused,
the ``ARCHIVER_DEV_REDIS_URL`` same-broker rule. Asserted through the dry-run
report, which never echoes a key. The verdict's parity with the Python gate is
``tests/scripts/test_db_guard_parity.py``.
"""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev_server.sh"
_TEST_DB = "postgresql+asyncpg://u:p@localhost:5432/archiver_test"
DEV_URL = "http://notifier:9001"
DEV_KEY = "nk_dev-0123456789"
PROD_KEY = "nk_prod-0123456789"


def _run(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "ARCHIVER_DEV_SERVER_DRY_RUN": "1",
        "ARCHIVER_DEV_SERVER_SKIP_ENV_FILES": "1",
        "TEST_DATABASE_URL": _TEST_DB,
        **extra_env,
    }
    return subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)


def _line(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("NOTIFIER="):
            return line[len("NOTIFIER=") :]
    raise AssertionError(f"no NOTIFIER= line in dry-run output:\n{stdout}")


def test_nothing_set_is_dormant() -> None:
    result = _run({})
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == "(dormant)"


def test_the_units_variables_are_never_inherited() -> None:
    result = _run(
        {
            "ARCHIVER_NOTIFIER_BASE_URL": "http://notifier:9000",
            "ARCHIVER_NOTIFIER_API_KEY": PROD_KEY,
            "ARCHIVER_NOTIFIER_ENABLED": "1",
            "CREDENTIALS_DIRECTORY": "/run/credentials/archiver.service",
        }
    )
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == "(dormant)"
    assert PROD_KEY not in result.stdout + result.stderr


def test_a_dev_pair_is_mapped_and_the_key_never_echoed() -> None:
    result = _run(
        {"ARCHIVER_DEV_NOTIFIER_BASE_URL": DEV_URL, "ARCHIVER_DEV_NOTIFIER_API_KEY": DEV_KEY}
    )
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == f"{DEV_URL} (dev key)"
    assert DEV_KEY not in result.stdout + result.stderr


def test_a_dev_pair_replaces_whatever_was_inherited() -> None:
    result = _run(
        {
            "ARCHIVER_NOTIFIER_BASE_URL": "http://notifier:9000",
            "ARCHIVER_NOTIFIER_API_KEY": PROD_KEY,
            "ARCHIVER_DEV_NOTIFIER_BASE_URL": DEV_URL,
            "ARCHIVER_DEV_NOTIFIER_API_KEY": DEV_KEY,
        }
    )
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == f"{DEV_URL} (dev key)"


@pytest.mark.parametrize(
    "half",
    [
        {"ARCHIVER_DEV_NOTIFIER_BASE_URL": DEV_URL},
        {"ARCHIVER_DEV_NOTIFIER_API_KEY": DEV_KEY},
    ],
)
def test_half_a_pair_is_dormant_and_says_so(half: dict[str, str]) -> None:
    """The flag is set only beside both: half a pair is a mistake worth a line, not a
    refusal, so a forgotten variable never blocks the dev server."""
    result = _run(half)
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == "(dormant)"
    assert "ARCHIVER_DEV_NOTIFIER" in result.stderr
    assert DEV_KEY not in result.stderr


@pytest.mark.parametrize(
    "url", ["http://notifier:9000", "http://100.64.0.7:9000/", "https://notifier:09000"]
)
def test_a_dev_url_on_productions_port_refuses(url: str) -> None:
    result = _run({"ARCHIVER_DEV_NOTIFIER_BASE_URL": url, "ARCHIVER_DEV_NOTIFIER_API_KEY": DEV_KEY})
    assert result.returncode != 0
    assert "9000" in result.stderr
    assert DEV_KEY not in result.stderr


def test_a_dev_url_on_productions_port_refuses_even_without_a_key() -> None:
    result = _run({"ARCHIVER_DEV_NOTIFIER_BASE_URL": "http://notifier:9000"})
    assert result.returncode != 0


@pytest.mark.parametrize("url", ["notifier:9001", "ftp://notifier:9001", "http://u@notifier:9001"])
def test_an_unusable_dev_url_refuses(url: str) -> None:
    result = _run({"ARCHIVER_DEV_NOTIFIER_BASE_URL": url, "ARCHIVER_DEV_NOTIFIER_API_KEY": DEV_KEY})
    assert result.returncode != 0
    assert "http(s)://host[:port]" in result.stderr
