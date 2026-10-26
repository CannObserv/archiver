"""``publish_policy_events`` may only be called with the complete set (archiver#366).

Its retention floor is ``len(events) * RETAINED_FULL_SETS``: the corpus only
while the batch is the corpus. A partial batch floors the cap at a fraction of
the set, and the publish then trims the set down to it, so a boot replay returns
a partial set no consumer can tell from a complete one. Watcher's #292, CR 1,
and its ``tests/test_full_set_publishers.py``, ported.

Reads the source rather than the runtime: the failure is a *new* call site
written the wrong way, which no existing test would exercise. It asserts that
it found the call site, so a rename fails rather than passing vacuously.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCANNED_ROOTS = (ROOT / "src", ROOT / "scripts")

HELPER = "publish_policy_events"
ALLOWED_CALLER = "publish_full_policy_set"


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _call_sites():
    """Every call to the helper, with its nearest enclosing function (None at module scope)."""
    for root in SCANNED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text())
            enclosing: dict[int, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            enclosing[id(child)] = node.name
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _callee(node) == HELPER:
                    yield path, enclosing.get(id(node))


def test_publish_policy_events_is_called_only_by_the_full_set():
    sites = list(_call_sites())
    assert sites, f"no call to {HELPER}() found - renamed? A vacuous pass is the failure mode."
    for path, enclosing in sites:
        assert enclosing == ALLOWED_CALLER, (
            f"{path.relative_to(ROOT)}: {HELPER}() called from "
            f"{enclosing or '<module scope>'!r}; only {ALLOWED_CALLER}() may call it. Its "
            "retention floor is derived from the batch (len(events) * RETAINED_FULL_SETS), "
            "so a partial batch trims the stream below one full set. Publish the full set, "
            "or give the new path its own cap."
        )


def test_the_precondition_is_stated_where_the_caller_reads_it():
    """The guard is not the documentation: the docstring has to say it too."""
    for path in sorted((ROOT / "src").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == HELPER:
                assert "must be the complete" in (ast.get_docstring(node) or "")
                return
    raise AssertionError(f"{HELPER} not found under src/ - renamed?")
