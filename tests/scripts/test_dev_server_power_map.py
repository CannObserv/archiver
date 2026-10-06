"""The dev-server launcher never inherits production's Power Map key (archiver#304).

``/etc/archiver/.env`` carries ``ARCHIVER_POWER_MAP_API_KEY`` for the live
service. A dev server reads ``ARCHIVER_DEV_POWER_MAP_API_KEY`` (and optionally
``ARCHIVER_DEV_POWER_MAP_BASE_URL``) or runs with Power Map dormant - the
``ARCHIVER_DEV_REDIS_URL`` rule. Production Power Map is a fine target for dev
(the key is read-only and dev writes only ``archiver_dev``); what must not
happen is a credential travelling from the service's env file without anyone
choosing it. Asserted through the dry-run report.
"""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev_server.sh"
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


def _line(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("POWER_MAP="):
            return line[len("POWER_MAP=") :]
    raise AssertionError(f"no POWER_MAP= line in dry-run output:\n{stdout}")


def test_no_dev_key_runs_power_map_dormant() -> None:
    result = _run({})
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == "(dormant)"


def test_productions_key_is_not_inherited() -> None:
    result = _run(
        {
            "ARCHIVER_POWER_MAP_API_KEY": "prod-key",
            "ARCHIVER_POWER_MAP_BASE_URL": "https://power-map.exe.xyz",
        }
    )
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == "(dormant)"
    assert "prod-key" not in result.stdout


def test_a_dev_key_is_used_against_the_default_base_url() -> None:
    result = _run({"ARCHIVER_DEV_POWER_MAP_API_KEY": "dev-key"})
    assert result.returncode == 0, result.stderr
    # The key itself is never echoed.
    assert _line(result.stdout) == "(default base URL, dev key)"
    assert "dev-key" not in result.stdout


def test_a_dev_base_url_overrides() -> None:
    result = _run(
        {
            "ARCHIVER_DEV_POWER_MAP_API_KEY": "dev-key",
            "ARCHIVER_DEV_POWER_MAP_BASE_URL": "https://pm-staging.test",
            "ARCHIVER_POWER_MAP_BASE_URL": "https://power-map.exe.xyz",
        }
    )
    assert result.returncode == 0, result.stderr
    assert _line(result.stdout) == "https://pm-staging.test (dev key)"
