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

_REPLICATION = Path(__file__).resolve().parents[3] / "src" / "core" / "replication"

# The layer above: authoring operations that routes call. They compose the
# domain, so they may import downward; the reverse is what this file refuses.
FORBIDDEN_PREFIX = "src.core.tools"


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, however it spells the import."""
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
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
