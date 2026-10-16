"""The dev-server launcher never runs the liveness heartbeat (archiver#297).

Only ``deploy/archiver.service`` sets ``CO_ARCHIVER_LIVE_MONITOR_ID`` and hands
over the key in ``$CREDENTIALS_DIRECTORY``. A dev server that had both would
check in ``ok`` for production and mask its silence, so the launcher drops both
whatever it inherited. Asserted through the dry-run report.
"""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev_server.sh"
_TEST_DB = "postgresql+asyncpg://u:p@localhost:5432/archiver_test"
_MONITOR = "01M46EXP45TVCVAMQXK043N1Q7"


def _liveness(extra_env: dict[str, str]) -> str:
    env = {
        "PATH": "/usr/bin:/bin",
        "ARCHIVER_DEV_SERVER_DRY_RUN": "1",
        "ARCHIVER_DEV_SERVER_SKIP_ENV_FILES": "1",
        "TEST_DATABASE_URL": _TEST_DB,
        **extra_env,
    }
    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    for line in result.stdout.splitlines():
        if line.startswith("LIVENESS="):
            return line[len("LIVENESS=") :]
    raise AssertionError(f"no LIVENESS= line in dry-run output:\n{result.stdout}")


def test_liveness_is_off_by_default() -> None:
    assert _liveness({}) == "(off)"


def test_an_inherited_monitor_and_key_are_dropped() -> None:
    assert (
        _liveness({"CO_ARCHIVER_LIVE_MONITOR_ID": _MONITOR, "CREDENTIALS_DIRECTORY": "/run/x"})
        == "(off)"
    )
