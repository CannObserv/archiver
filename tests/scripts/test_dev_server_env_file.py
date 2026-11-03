"""The dev-server launcher parses the repo ``.env`` and keeps its own names (#452).

It used to source ``/etc/archiver/.env`` and the repo ``.env`` under ``set -a``,
so uvicorn inherited every PAT, ``ANTHROPIC_API_KEY`` and ``EXE_API_TOKEN`` in
the developer's file. Its only inputs there are ``ARCHIVER_DEV_*`` and the
``TEST_DATABASE_URL`` fallback, so those are all it exports, through
``scripts/lib/env.sh``. ``/etc/archiver/.env`` is not read at all: root's alone
since #339, and production's under ``sudo`` (#452 D2).

``ARCHIVER_DEV_SERVER_ENV_FILE`` points the launcher at a fixture file. The dry
run reports the names it loaded, never a value; one case runs the exec path
against a fake ``uv`` that records the environment uvicorn would get.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev_server.sh"

DEV_URL = "postgresql+asyncpg://u:p@localhost:5432/archiver_dev"
SECRET = "ghp_not-a-real-token"
ENV_TEXT = f"""\
GH_TOKEN={SECRET}
ANTHROPIC_API_KEY="{SECRET}-2"
ARCHIVER_DEV_DATABASE_URL={DEV_URL}
"""

FAKE_UV = """\
#!/usr/bin/env bash
env > "$PROBE/env"
"""


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.env"
    path.write_text(ENV_TEXT)
    return path


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={"PATH": "/usr/bin:/bin", **env},
        text=True,
        capture_output=True,
        timeout=30,
    )


def _report(stdout: str, key: str) -> str:
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1 :]
    raise AssertionError(f"no {key}= line in dry-run output:\n{stdout}")


def test_dry_run_loads_the_dev_key_and_not_the_token(env_file: Path) -> None:
    result = _run(
        {"ARCHIVER_DEV_SERVER_DRY_RUN": "1", "ARCHIVER_DEV_SERVER_ENV_FILE": str(env_file)}
    )
    assert result.returncode == 0, result.stderr
    assert _report(result.stdout, "ARCHIVER_DATABASE_URL") == DEV_URL
    assert _report(result.stdout, "ENV_NAMES") == "ARCHIVER_DEV_DATABASE_URL"
    for text in ("GH_TOKEN", "ANTHROPIC_API_KEY", SECRET):
        assert text not in result.stdout + result.stderr


def test_dry_run_reports_skipped_env_files() -> None:
    result = _run(
        {
            "ARCHIVER_DEV_SERVER_DRY_RUN": "1",
            "ARCHIVER_DEV_SERVER_SKIP_ENV_FILES": "1",
            "TEST_DATABASE_URL": DEV_URL.replace("_dev", "_test"),
        }
    )
    assert result.returncode == 0, result.stderr
    assert _report(result.stdout, "ENV_NAMES") == "(skipped)"


def test_uvicorn_inherits_no_token(env_file: Path, tmp_path: Path) -> None:
    """The exec path, not the report: what the child process actually gets."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(FAKE_UV)
    (bin_dir / "uv").chmod(0o755)
    probe = tmp_path / "probe"
    probe.mkdir()
    result = _run(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "PROBE": str(probe),
            "ARCHIVER_DEV_SKIP_MIGRATE": "1",
            "ARCHIVER_DEV_SERVER_ENV_FILE": str(env_file),
        }
    )
    assert result.returncode == 0, result.stderr
    seen = dict(
        line.split("=", 1) for line in (probe / "env").read_text().splitlines() if "=" in line
    )
    assert seen["ARCHIVER_DATABASE_URL"] == DEV_URL
    for name in ("GH_TOKEN", "ANTHROPIC_API_KEY"):
        assert name not in seen, name
    assert SECRET not in result.stdout + result.stderr


def test_never_names_the_production_env_file() -> None:
    """Not behavioural, since a test cannot plant ``/etc/archiver/.env``: no line
    of code may name an ``/etc`` path (comments may, to say why)."""
    code = [line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in code if "/etc/" in line]
