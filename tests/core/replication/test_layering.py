"""``src/core/replication/`` may not import the authoring layer above it (CR 2).

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

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_REPLICATION = _ROOT / "src" / "core" / "replication"

# The layer above: authoring operations that routes call. They compose the
# domain, so they may import downward; the reverse is what this file refuses.
FORBIDDEN_PREFIX = "src.core.tools"


def _package_of(path: Path) -> str:
    """The dotted package a module at *path* lives in, e.g. ``src.core.replication``."""
    return ".".join(path.resolve().parent.relative_to(_ROOT).parts)


def _resolved_relative(path: Path, node: ast.ImportFrom) -> str:
    """The absolute module name a relative ``ImportFrom`` denotes (CR 9).

    ``level`` counts the leading dots: one means this package, two the parent,
    and so on. ``node.module`` is only the tail, so the name a relative import
    actually reaches has to be rebuilt from the importing file's own location.
    Dropping these is what let ``from ..tools.assign_rep_spec import …`` name
    the forbidden layer and read as no import at all.
    """
    parts = _package_of(path).split(".")
    base = parts[: len(parts) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, however it spells the import.

    Relative imports are resolved to their absolute names, so the set answers
    "what does this module reach" rather than "what did the author type".
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.add(_resolved_relative(path, node))
            elif node.module:
                names.add(node.module)
    return names


def _modules() -> list[Path]:
    return sorted(p for p in _REPLICATION.glob("*.py") if p.name != "__init__.py")


def test_the_scan_sees_the_modules_it_claims_to():
    """A glob that matched nothing would pass every assertion below."""
    assert {p.name for p in _modules()} >= {"destination.py", "template.py", "errors.py"}


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_replication_does_not_import_the_authoring_layer(module):
    offenders = {
        name
        for name in _imported_modules(module)
        if name == FORBIDDEN_PREFIX or name.startswith(FORBIDDEN_PREFIX + ".")
    }
    assert not offenders, (
        f"{module.name} imports {sorted(offenders)}; src/core/tools/ sits above "
        "replication and imports it back (tools.assign_rep_spec -> "
        "replication.destination). Put the shared code in a leaf module such as "
        "src/core/rep_fields.py instead."
    )


def test_the_guard_fires_on_a_planted_import(tmp_path):
    """Without this, a scan that stopped parsing would pass silently."""
    planted = tmp_path / "planted.py"
    planted.write_text("from src.core.tools.assign_rep_spec import assign_rep_spec\n")
    assert FORBIDDEN_PREFIX + ".assign_rep_spec" in _imported_modules(planted)


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
        assert FORBIDDEN_PREFIX + ".assign_rep_spec" in _imported_modules(planted)
    finally:
        planted.unlink()
