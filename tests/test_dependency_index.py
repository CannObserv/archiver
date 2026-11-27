"""co-core resolves from the co-pypi index, and only from it (archiver#498).

Ported from CannObserv/broker#144 (after CannObserv/watcher#358 and
CannObserv/processor#121). ``co-core`` and ``co-core-aio`` are private: they are
in the co-pypi Artifact Registry index and nowhere public. cannobserv's
RELEASING.md, *Path C*, states the rules a consumer keeps, and each is a test
here, because each one breaks quietly:

* **The URL is the org registry's byte for byte**, trailing slash included.
  Dependabot's updater matches it to the org's registry by string; a near miss
  sends it without credentials.
* **``explicit = true``, plus a ``[tool.uv.sources]`` entry per cannobserv
  name.** An explicit index serves only the names pinned to it, so co-core never
  comes from PyPI, where the names are unclaimed, and nothing else comes from
  co-pypi.
* **Every cannobserv package is declared directly.** uv binds a source to a
  direct dependency only; one reached transitively would go to PyPI.
* **The lock carries each file's sha256.** ``find-links`` locked a filename and
  left integrity to the bucket's access control; ``uv sync --locked`` refuses a
  file that misses the lock's hash. The 0.38.0 files' index sha256 equalled the
  bucket's before the move (#498, read 2026-11-26).

Pure file reads: no network.
"""

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests.scripts._skills_lists import tracked_files

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text())
LOCK = tomllib.loads((REPO / "uv.lock").read_text())

INDEX = "co-pypi"
URL = "https://us-west1-python.pkg.dev/co-gcs/co-pypi/simple/"
HOST = "us-west1-python.pkg.dev"
# cannobserv's published names.
CANNOBSERV = {"cannobserv", "co-core", "co-core-aio", "co-core-sync"}


def _is_cannobserv(name: str) -> bool:
    return canonicalize_name(name) in CANNOBSERV


def _locked_cannobserv() -> list[dict]:
    return [p for p in LOCK["package"] if _is_cannobserv(p["name"])]


def _uv() -> dict:
    return PYPROJECT["tool"]["uv"]


class TestTheIndex:
    def test_one_co_pypi_index_at_the_org_registrys_url(self):
        indexes = [i for i in _uv().get("index", []) if i.get("name") == INDEX]
        assert len(indexes) == 1, f"want one [[tool.uv.index]] named {INDEX!r}"
        assert indexes[0]["url"] == URL, "byte for byte, trailing slash included"

    def test_the_index_is_explicit(self):
        [index] = [i for i in _uv()["index"] if i["name"] == INDEX]
        assert index.get("explicit") is True, (
            "an implicit index would serve every name, and co-core would be one"
            " lookup away from PyPI's unclaimed namesake"
        )

    def test_no_find_links_and_no_other_index(self):
        assert "find-links" not in _uv(), "#498 retired the wheelhouse; one source per name"
        assert [i["name"] for i in _uv()["index"]] == [INDEX]

    def test_no_credential_in_a_committed_url(self):
        """The pair travels by environment alone: never ``user:token@`` in a URL."""
        for path in ("pyproject.toml", "uv.lock"):
            text = (REPO / path).read_text()
            assert f"@{HOST}" not in text, path
            assert "oauth2accesstoken" not in text, path


class TestEveryCannobservPackage:
    def test_the_sweep_finds_both(self):
        """Guard the guard: a rename would leave every test below vacuous."""
        assert {p["name"] for p in _locked_cannobserv()} == {"co-core", "co-core-aio"}

    @pytest.mark.parametrize("package", _locked_cannobserv(), ids=lambda p: p["name"])
    def test_is_declared_directly(self, package: dict):
        declared = {
            canonicalize_name(Requirement(r).name) for r in PYPROJECT["project"]["dependencies"]
        }
        assert canonicalize_name(package["name"]) in declared, (
            f"{package['name']} is locked but not declared: uv binds sources to direct"
            " dependencies only, so a transitive one resolves from PyPI"
        )

    @pytest.mark.parametrize("package", _locked_cannobserv(), ids=lambda p: p["name"])
    def test_is_pinned_to_the_index(self, package: dict):
        assert _uv()["sources"][package["name"]] == {"index": INDEX}

    @pytest.mark.parametrize("package", _locked_cannobserv(), ids=lambda p: p["name"])
    def test_locks_from_the_index_with_a_sha256_per_file(self, package: dict):
        assert package["source"] == {"registry": URL}
        files = [*([package["sdist"]] if "sdist" in package else []), *package.get("wheels", [])]
        assert files, "no file locked"
        for dist in files:
            assert dist["url"].startswith(f"https://{HOST}/"), dist["url"]
            assert dist["hash"].startswith("sha256:") and len(dist["hash"]) == 7 + 64

    @pytest.mark.parametrize("package", _locked_cannobserv(), ids=lambda p: p["name"])
    def test_is_locked_to_a_wheel(self, package: dict):
        """CI's ``prune-cache`` drops downloaded wheels and keeps wheels built
        from source: it keeps private co-core out of a public repo's Actions
        cache only while co-core installs from a wheel (#192)."""
        assert package.get("wheels"), f"{package['name']} would build from its sdist"


def test_nothing_else_resolves_from_the_index():
    others = [
        p["name"]
        for p in LOCK["package"]
        if not _is_cannobserv(p["name"]) and p.get("source", {}).get("registry") == URL
    ]
    assert others == []


def test_the_wrappers_group_is_locked_and_needs_nothing_from_the_index():
    """``scripts/co-pypi.sh`` installs the ``co-pypi`` group before any co-core
    file can be fetched, so it must resolve from PyPI alone, from the lock."""
    assert PYPROJECT["dependency-groups"][INDEX] == ["google-auth[requests]>=2,<3"]
    [project] = [p for p in LOCK["package"] if p["name"] == "archiver"]
    assert [d["name"] for d in project["dev-dependencies"][INDEX]] == ["google-auth"]
    by_name: dict[str, list[dict]] = {}
    for package in LOCK["package"]:
        by_name.setdefault(package["name"], []).append(package)
    closure, todo = set(), ["google-auth"]
    while todo:
        name = todo.pop()
        if name in closure:
            continue
        closure.add(name)
        for package in by_name[name]:
            todo += [d["name"] for d in package.get("dependencies", [])]
            todo += [
                d["name"] for d in package.get("optional-dependencies", {}).get("requests", [])
            ]
    assert {"requests", "certifi"} <= closure, "the mint's transport, and its TLS bundle"
    assert not {canonicalize_name(n) for n in closure} & CANNOBSERV
    assert all(p["source"].get("registry") != URL for n in closure for p in by_name[n])


def test_the_group_is_never_installed_by_default():
    """``deploy.sh`` syncs ``--no-dev``; a default group would ride along."""
    assert INDEX not in _uv().get("default-groups", ["dev"])


def test_the_wheelhouse_is_gone():
    tracked = set(tracked_files())
    assert "scripts/sync_wheelhouse.py" not in tracked
    assert ".wheelhouse/.gitkeep" not in tracked
