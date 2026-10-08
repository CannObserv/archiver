"""Guard: ``src/core/power_map/`` imports nothing from ``src/core/tools/`` (archiver#327).

``tools`` (``link_org``, ``set_rep_fields``, ``refresh_orgs``) depends on
``power_map`` for the adapter and the snapshot; the reverse edge made the two
packages a cycle that held only while ``power_map/__init__`` left the follower
out. A static scan, so an import under ``if TYPE_CHECKING:`` counts too.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "src" / "core" / "power_map"
FORBIDDEN = "src.core.tools"


def _imports_tools(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            a.name == FORBIDDEN or a.name.startswith(f"{FORBIDDEN}.") for a in node.names
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == FORBIDDEN or node.module.startswith(f"{FORBIDDEN}."))
        ):
            return True
    return False


def test_power_map_imports_nothing_from_tools():
    importers = sorted(
        str(path.relative_to(ROOT))
        for path in PACKAGE.rglob("*.py")
        if _imports_tools(ast.parse(path.read_text()))
    )
    assert importers == []


def test_the_scan_catches_a_planted_import():
    assert _imports_tools(ast.parse("from src.core.tools.set_rep_fields import log_moves"))
    assert _imports_tools(ast.parse("import src.core.tools"))
    assert not _imports_tools(ast.parse("from src.core.toolshed import x"))
