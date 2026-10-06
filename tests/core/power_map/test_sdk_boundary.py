"""Guard: ``src/core/power_map/client.py`` is the only importer of the Power Map SDK (archiver#304).

The SDK's models are attrs classes generated from Power Map's OpenAPI spec; a
module that imported them directly would couple archiver's domain to Power
Map's wire shape and skip the adapter's status mapping. A static scan, so an
import under ``if TYPE_CHECKING:`` counts too.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK = "power_map_client"
ADAPTER = Path("src/core/power_map/client.py")


def _imports_sdk(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            a.name == SDK or a.name.startswith(f"{SDK}.") for a in node.names
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == SDK or node.module.startswith(f"{SDK}."))
        ):
            return True
    return False


def test_only_the_adapter_imports_the_sdk():
    importers = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if _imports_sdk(ast.parse(path.read_text()))
    )
    assert importers == [str(ADAPTER)]


def test_the_scan_catches_a_planted_import():
    assert _imports_sdk(ast.parse("from power_map_client.generated.models import OrgDetail"))
    assert _imports_sdk(ast.parse("import power_map_client"))
    assert not _imports_sdk(ast.parse("import power_map_clientele"))
