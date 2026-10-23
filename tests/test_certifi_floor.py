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

# The wheelhouse fetch runs in `uv run --no-project`, which pyproject's constraint
# never reaches, so each copy of the command floors certifi itself. Dated records
# (plans, the changelog) keep the command as it was.
FETCH = re.compile(r"uv run --no-project[^\n]*?scripts/sync_wheelhouse\.py")
DATED = ("docs/plans/", "CHANGELOG.md")


def test_pyproject_constrains_the_floor() -> None:
    uv = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]
    assert f"certifi>={FLOOR}" in uv.get("constraint-dependencies", [])


def _locks() -> list[str]:
    """Every tracked ``uv.lock``: the SDK's runs CI's SDK job, and #418 missed it (#420)."""
    return [path for path in tracked_files() if path.rsplit("/", 1)[-1] == "uv.lock"]


def test_both_locks_are_found() -> None:
    assert {"uv.lock", "clients/python/uv.lock"} <= set(_locks()), _locks()


@pytest.mark.parametrize("path", _locks())
def test_lock_resolves_at_or_above_the_floor(path: str) -> None:
    lock = tomllib.loads((ROOT / path).read_text())
    (locked,) = [p["version"] for p in lock["package"] if p["name"] == "certifi"]
    assert Version(locked) >= Version(FLOOR), locked


def test_installed_at_or_above_the_floor() -> None:
    assert Version(version("certifi")) >= Version(FLOOR), version("certifi")


def test_every_wheelhouse_fetch_floors_certifi() -> None:
    fetches = []
    for path in tracked_files():
        file = ROOT / path
        if path.startswith(DATED) or not file.is_file():
            continue
        text = re.sub(r"\\\n\s*", " ", file.read_text(errors="replace"))
        fetches += [(path, cmd) for cmd in FETCH.findall(text)]
    assert len({path for path, _ in fetches}) >= 6, fetches
    unfloored = [path for path, cmd in fetches if f"--with 'certifi>={FLOOR}'" not in cmd]
    assert not unfloored, unfloored
