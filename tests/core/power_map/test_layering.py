"""``src/core/power_map/`` may not import any layer that imports it (archiver#327).

``tools`` (``link_org``, ``set_rep_fields``, ``refresh_orgs``) depends on
``power_map`` for the adapter and the snapshot. The follower used to live in
``power_map`` and import the move helpers back from ``tools``: a package cycle
held open only by ``power_map/__init__`` not importing the follower. The same
shape as replication's guard (``tests/core/replication/test_layering.py``):
the forbidden set is derived, and relative imports resolve.
"""

from pathlib import Path

import pytest

from tests.core._import_scan import ROOT, imported_modules, package_of

_POWER_MAP = ROOT / "src" / "core" / "power_map"
_SRC = ROOT / "src"
_PACKAGE = "src.core.power_map"

# The exemplar the planted-import tests spell out; the enforced set is derived.
FORBIDDEN_PREFIX = "src.core.tools"

# Floor for the derivation: a scan that matched nothing would forbid nothing.
KNOWN_CONSUMER_PACKAGES = frozenset({"src.core.tools"})


def _modules() -> list[Path]:
    return sorted(_POWER_MAP.rglob("*.py"))


def _reaches(name: str, target: str) -> bool:
    """Whether an imported *name* is *target* or something inside it."""
    return name == target or name.startswith(target + ".")


def _consumer_packages() -> frozenset[str]:
    """Every package outside power_map that imports it.

    A package that *contains* power_map (``src.core``) is skipped: forbidding
    that prefix would fail every module on its own siblings.
    """
    packages: set[str] = set()
    for path in _SRC.rglob("*.py"):
        if path.resolve().is_relative_to(_POWER_MAP.resolve()):
            continue
        if not any(_reaches(name, _PACKAGE) for name in imported_modules(path)):
            continue
        package = package_of(path)
        if _reaches(_PACKAGE, package):
            continue
        packages.add(package)
    return frozenset(packages)


def test_the_scan_sees_the_modules_it_claims_to():
    assert {p.name for p in _modules()} >= {"__init__.py", "client.py", "snapshots.py"}


def test_the_derived_consumer_set_covers_the_known_layers():
    assert _consumer_packages() >= KNOWN_CONSUMER_PACKAGES


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_power_map_does_not_import_a_layer_that_imports_it(module):
    consumers = _consumer_packages()
    offenders = {
        name
        for name in imported_modules(module)
        if any(_reaches(name, package) for package in consumers)
    }
    assert not offenders, (
        f"{module.name} imports {sorted(offenders)}, which imports power_map back "
        "- a cycle. Workflow logic that writes the effective bag belongs in tools/."
    )


def test_the_guard_fires_on_a_planted_import(tmp_path):
    planted = tmp_path / "planted.py"
    planted.write_text("from src.core.tools.set_rep_fields import log_moves\n")
    assert FORBIDDEN_PREFIX + ".set_rep_fields" in imported_modules(planted)


def test_the_guard_fires_on_a_planted_relative_import():
    """Planted inside the package: resolving the leading dots needs a real path."""
    planted = _POWER_MAP / "planted_relative.py"
    planted.write_text("from ..tools.set_rep_fields import log_moves\n")
    try:
        assert FORBIDDEN_PREFIX + ".set_rep_fields" in imported_modules(planted)
    finally:
        planted.unlink()
