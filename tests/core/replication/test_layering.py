"""``src/core/replication/`` may not import any layer that imports it (CR 2, 11).

archiver#206 gave the renderer a second consumer of the rep_fields derivation
and reached for it where it then lived, under ``src/core/tools/``. That made
``replication`` import ``tools`` while ``tools.assign_rep_spec`` imports
``replication`` — a genuine cycle, held open only by ``src/core/tools/__init__.py``
happening to be empty. Nothing failed, and nothing would have until the first
re-export landed in that file, at which point the failure is an ``ImportError``
at startup rather than a test.

A scan rather than an import probe: the cycle is latent, so importing the
package proves nothing while ``__init__.py`` stays empty. The dependency
*direction* is the invariant, and it is readable statically.
"""

from pathlib import Path

import pytest

from tests.core.replication._import_scan import ROOT, imported_modules, package_of

_ROOT = ROOT
_REPLICATION = _ROOT / "src" / "core" / "replication"

_SRC = _ROOT / "src"
_PACKAGE = "src.core.replication"

# The exemplar the planted-import tests below spell out. The set this file
# actually enforces is *derived* (CR 11): naming one layer caught one of the
# five that import replication, and the invariant was never about that name.
FORBIDDEN_PREFIX = "src.core.tools"

# Floor for the derivation. A scan that silently matched nothing would forbid
# nothing and pass every assertion, so the derived set has to contain at least
# the layers known to import replication today.
KNOWN_CONSUMER_PACKAGES = frozenset(
    {
        "src.api.routes",
        "src.core.services",
        "src.core.tools",
        "src.core.rep_spec_schema",
    }
)


def _modules() -> list[Path]:
    """Every module in the package, at any depth (CR 10).

    ``rglob`` rather than ``glob``: the package is flat today, and a
    top-level-only scan would leave the first subpackage anyone adds unchecked
    while the floor assertion below kept passing on the three files it names.
    """
    return sorted(p for p in _REPLICATION.rglob("*.py") if p.name != "__init__.py")


def test_the_scan_sees_the_modules_it_claims_to():
    """A glob that matched nothing would pass every assertion below."""
    assert {p.name for p in _modules()} >= {"destination.py", "template.py", "errors.py"}


def test_the_scan_reaches_into_a_subpackage(tmp_path):
    """The floor above names three flat files, so only this notices a missed depth."""
    nested = _REPLICATION / "_scan_probe" / "deep.py"
    nested.parent.mkdir()
    nested.write_text("x = 1\n")
    try:
        assert nested.resolve() in {p.resolve() for p in _modules()}
    finally:
        nested.unlink()
        nested.parent.rmdir()


def _reaches(name: str, target: str) -> bool:
    """Whether an imported *name* is *target* or something inside it."""
    return name == target or name.startswith(target + ".")


def _consumer_packages() -> frozenset[str]:
    """Every package outside replication that imports it (CR 11).

    Derived rather than listed, so a new consumer layer is forbidden from being
    imported back the moment it appears, without anyone remembering to edit a
    tuple here. Read by AST rather than by grep: ``src/core/rep_fields.py``
    names ``src.core.replication.destination`` in its module docstring and
    imports nothing of the sort, and a text scan calls that a consumer.

    A package that *contains* replication is skipped. ``src.core`` importing it
    would be a real inversion, but forbidding that prefix would forbid
    ``src.core.replication`` itself and fail every module on its own siblings.
    """
    packages: set[str] = set()
    for path in _SRC.rglob("*.py"):
        if path.resolve().is_relative_to(_REPLICATION.resolve()):
            continue
        if not any(_reaches(name, _PACKAGE) for name in imported_modules(path)):
            continue
        package = package_of(path)
        if _reaches(_PACKAGE, package):
            continue
        packages.add(package)
    return frozenset(packages)


def test_the_derived_consumer_set_covers_the_known_layers():
    """A derivation that matched nothing would forbid nothing, silently."""
    assert _consumer_packages() >= KNOWN_CONSUMER_PACKAGES


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_replication_does_not_import_a_layer_that_imports_it(module):
    consumers = _consumer_packages()
    offenders = {
        name
        for name in imported_modules(module)
        if any(_reaches(name, package) for package in consumers)
    }
    assert not offenders, (
        f"{module.name} imports {sorted(offenders)}, which sits above replication "
        "and imports it back — a cycle. Put the shared code in a leaf module such "
        "as src/core/rep_fields.py instead."
    )


def test_the_guard_fires_on_a_planted_import(tmp_path):
    """Without this, a scan that stopped parsing would pass silently."""
    planted = tmp_path / "planted.py"
    planted.write_text("from src.core.tools.assign_rep_spec import assign_rep_spec\n")
    assert FORBIDDEN_PREFIX + ".assign_rep_spec" in imported_modules(planted)


def test_the_guard_fires_on_a_planted_relative_import():
    """The same cycle, spelled relatively (CR 9).

    ``from ..tools.assign_rep_spec import …`` inside ``src/core/replication/``
    resolves to the identical module and re-creates the identical cycle. The
    scan dropped it, because a relative ``ImportFrom`` carries ``level > 0`` and
    a ``module`` that is only the tail of the name. Planted against a real path
    inside the scanned package, since resolving the leading dots needs one.
    """
    planted = _REPLICATION / "planted_relative.py"
    planted.write_text("from ..tools.assign_rep_spec import assign_rep_spec\n")
    try:
        assert FORBIDDEN_PREFIX + ".assign_rep_spec" in imported_modules(planted)
    finally:
        planted.unlink()
