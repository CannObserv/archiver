"""certifi stays at or above the release that distrusts eMudhra's compromised chain (#418).

httpx (the preview's fetch, Power Map, the drift check's GitHub call) and requests
(google-cloud-storage: the nightly backup) verify TLS against certifi's bundle, not
the system store, so an apt or exe.dev update to ``/etc/ssl`` doesn't reach them.
certifi 2026.4.22 trusts emSign ECC Root CA - G3, which the leaked intermediates
chain to; 2026.10.19 drops it. Nothing imports certifi, so the floor is a uv
constraint, and a re-lock below it fails here. Ported from CannObserv/provisioner#79.
"""

import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.version import Version

from tests.scripts._skills_lists import tracked_files

FLOOR = "2026.10.19"
ROOT = Path(__file__).resolve().parent.parent

# A `uv run --no-project --with` env resolves at run time, where pyproject's
# constraint never reaches, so any such command floors certifi itself. #498
# retired the last one, the wheelhouse fetch: the co-pypi mint (the one process
# that holds the reader key) runs from the lock instead. Dated records (plans,
# the changelog) keep the commands as they were.
UNLOCKED = re.compile(r"uv run --no-project[^\n]*?--with [^\n]*")
DATED = ("docs/plans/", "CHANGELOG.md")
WRAPPER = ROOT / "scripts" / "co-pypi.sh"
# This file names the pattern it sweeps for.
SELF = "tests/test_certifi_floor.py"


def test_pyproject_constrains_the_floor() -> None:
    uv = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]
    assert f"certifi>={FLOOR}" in uv.get("constraint-dependencies", [])


# Every tracked lock: the SDK's runs CI's SDK job, and #418 missed it (#420).
LOCKS = ("uv.lock", "clients/python/uv.lock")


def test_locks_names_every_tracked_lock() -> None:
    """A new lock fails here until it is added, and so floored."""
    tracked = {path for path in tracked_files() if path.rsplit("/", 1)[-1] == "uv.lock"}
    assert tracked == set(LOCKS)


@pytest.mark.parametrize("path", LOCKS)
def test_lock_resolves_at_or_above_the_floor(path: str) -> None:
    lock = tomllib.loads((ROOT / path).read_text())
    (locked,) = [p["version"] for p in lock["package"] if p["name"] == "certifi"]
    assert Version(locked) >= Version(FLOOR), locked


def test_installed_at_or_above_the_floor() -> None:
    assert Version(version("certifi")) >= Version(FLOOR), version("certifi")


def _unfloored(text: str) -> list[str]:
    """The unlocked-env commands in *text* that don't floor certifi. A command
    continued with a backslash is read as one line."""
    joined = re.sub(r"\\\n\s*", " ", text)
    return [cmd for cmd in UNLOCKED.findall(joined) if f"--with 'certifi>={FLOOR}'" not in cmd]


def test_every_unlocked_env_floors_certifi() -> None:
    unfloored = []
    for path in tracked_files():
        file = ROOT / path
        if path.startswith(DATED) or path == SELF or not file.is_file():
            continue
        unfloored += [(path, cmd) for cmd in _unfloored(file.read_text(errors="replace"))]
    assert not unfloored, unfloored


@pytest.mark.parametrize(
    ("text", "caught"),
    [
        ("uv run --no-project --with 'google-auth>=2' python x.py\n", True),
        ("uv run --no-project \\\n  --with 'google-auth>=2' python x.py\n", True),
        (f"uv run --no-project --with 'x>=1' --with 'certifi>={FLOOR}' python x.py\n", False),
        (f"uv run --no-project --with 'x>=1' \\\n  --with 'certifi>={FLOOR}' python x.py\n", False),
        ("uv run --no-project --python 3.12 python x.py\n", False),
    ],
    ids=["one-line", "continued", "floored", "floored-continued", "no-with"],
)
def test_the_sweep_catches_an_unfloored_env(text: str, caught: bool) -> None:
    """Guard the guard: no tracked file holds such an env since #498, so the
    sweep above passes vacuously unless its pattern is known to bite."""
    assert bool(_unfloored(text)) is caught


def test_the_co_pypi_mint_runs_from_the_floored_lock() -> None:
    """Its env is the lock's ``co-pypi`` group, so the constraint reaches it;
    tests/test_dependency_index.py holds certifi in that group's closure."""
    text = WRAPPER.read_text()
    assert "--frozen --only-group co-pypi" in text
    assert "--no-project" not in text
