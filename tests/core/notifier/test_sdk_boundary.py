"""Guard: ``src/core/notifier/client.py`` is the only importer of the Notifier SDK, and
nothing under ``src/`` reaches a call that sends or writes (archiver#368).

The SDK's facade also exposes ``dispatch``, ``redeliver``, ``channels.send_test``
and channel ``create``/``update``/``delete``; its generated tree has
``test_channel``. Each sends a notification or changes the tenant. The first
send is archiver#367's, as an operator action; dispatch is #369's. Until then
the adapter lists channels and nothing else. A static scan, so an import under
``if TYPE_CHECKING:`` counts too.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK = "notifier_client"
ADAPTER = Path("src/core/notifier/client.py")
#: The SDK calls that send, or change the tenant. None may appear in src/.
SENDING = ("send_test", "test_channel", "dispatch", "redeliver", "apprise", "templates")


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


def _sdk_attributes(source: str) -> set[str]:
    """Every attribute name the adapter reads, on anything."""
    return {n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)}


def test_only_the_adapter_imports_the_sdk() -> None:
    importers = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if _imports_sdk(ast.parse(path.read_text()))
    )
    assert importers == [str(ADAPTER)]


def test_the_adapter_reaches_no_sending_or_writing_call() -> None:
    attributes = _sdk_attributes((ROOT / ADAPTER).read_text())
    assert not attributes & {*SENDING, "create", "update", "delete", "preview"}


def test_nothing_in_src_names_a_sending_call() -> None:
    pattern = re.compile(r"\b(send_test|test_channel)\b")
    hits = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".html", ".js"}
        and pattern.search(path.read_text())
    )
    assert hits == []


def test_the_scan_catches_a_planted_import_and_call() -> None:
    assert _imports_sdk(ast.parse("from notifier_client import NotifierClient"))
    assert _imports_sdk(ast.parse("import notifier_client.generated"))
    assert not _imports_sdk(ast.parse("import notifier_clientele"))
    assert "send_test" in _sdk_attributes("client.channels.send_test('x')")
