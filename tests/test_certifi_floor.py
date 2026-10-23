"""certifi stays at or above the release that distrusts eMudhra's compromised chain (#418).

httpx (the preview's fetch, Power Map, the drift check's GitHub call) and requests
(google-cloud-storage: the nightly backup) verify TLS against certifi's bundle, not
the system store, so an apt or exe.dev update to ``/etc/ssl`` doesn't reach them.
certifi 2026.4.22 trusts emSign ECC Root CA - G3, which the leaked intermediates
chain to; 2026.10.19 drops it. Nothing imports certifi, so the floor is a uv
constraint, and a re-lock below it fails here. Ported from CannObserv/provisioner#79.
"""

import tomllib
from importlib.metadata import version
from pathlib import Path

from packaging.version import Version

FLOOR = "2026.10.19"
ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_constrains_the_floor() -> None:
    uv = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]
    assert f"certifi>={FLOOR}" in uv.get("constraint-dependencies", [])


def test_lock_resolves_at_or_above_the_floor() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    (locked,) = [p["version"] for p in lock["package"] if p["name"] == "certifi"]
    assert Version(locked) >= Version(FLOOR), locked


def test_installed_at_or_above_the_floor() -> None:
    assert Version(version("certifi")) >= Version(FLOOR), version("certifi")
