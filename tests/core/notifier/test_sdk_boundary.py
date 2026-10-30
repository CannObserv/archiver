"""Guard: ``src/core/notifier/client.py`` is the only importer of the Notifier SDK, and
nothing under ``src/`` reaches a call that sends or writes, but one (archiver#368, #367).

The SDK's facade exposes ``dispatch``, ``redeliver``, ``channels.send_test`` and
channel ``create``/``update``/``delete``; its generated tree has
``test_channel``. Each sends a notification or changes the tenant.

**#367 widens the adapter by ``dispatch`` alone** (D6), reachable only through
``Notifier.dispatch_composed``, which D3 shapes: the composed text travels as
variables, never as Notifier's template. The rest stays banned. A static scan,
so an import under ``if TYPE_CHECKING:`` counts too.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK = "notifier_client"
ADAPTER = Path("src/core/notifier/client.py")
#: The SDK calls that send, or change the tenant. None may appear in src/.
SENDING = ("send_test", "test_channel", "redeliver", "apprise", "templates")
#: The one sending call the adapter may make, and the one function that makes it.
DISPATCH = "dispatch"
DISPATCHER = "dispatch_composed"


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


def _dispatch_sites(tree: ast.Module) -> list[tuple[str, ast.Call]]:
    """Every ``<x>.dispatch(...)`` call, with the function it sits in."""
    sites = []
    for func in ast.walk(tree):
        if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == DISPATCH
                ):
                    sites.append((func.name, node))
    return sites


def test_the_adapter_dispatches_in_one_place() -> None:
    tree = ast.parse((ROOT / ADAPTER).read_text())
    sites = _dispatch_sites(tree)
    assert [name for name, _ in sites] == [DISPATCHER]
    every = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == DISPATCH]
    assert len(every) == 1, "dispatch is named outside its one call"


def test_the_one_dispatch_passes_text_as_variables() -> None:
    """D3, statically: the templates are the two constants, never composed text."""
    ((_, call),) = _dispatch_sites(ast.parse((ROOT / ADAPTER).read_text()))
    keywords = {k.arg: k.value for k in call.keywords}
    assert "template_id" not in keywords
    for field, constant in (
        ("title_template", "TITLE_TEMPLATE"),
        ("body_template", "BODY_TEMPLATE"),
    ):
        assert isinstance(keywords[field], ast.Name) and keywords[field].id == constant


def test_nothing_else_in_src_calls_dispatch() -> None:
    hits = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if path.relative_to(ROOT) != ADAPTER and _dispatch_sites(ast.parse(path.read_text()))
    )
    assert hits == []


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
