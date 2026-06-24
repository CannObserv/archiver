"""Tests for ``scripts/check_client_drift.py``.

The drift checker regenerates a vendored OpenAPI client into a temp dir and
compares it against the committed ``generated/`` tree; a non-empty diff means
the committed client has drifted from its upstream contract (the failure mode
behind #66). The regen step shells out to ``openapi-python-client`` and is
exercised end-to-end by CI; here we unit-test the pure tree comparator
``diff_trees`` — the logic that decides *what counts as drift*.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_client_drift.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_client_drift", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass introspection can resolve __module__.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()
diff_trees = mod.diff_trees


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture
def trees(tmp_path: Path) -> tuple[Path, Path]:
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    return expected, actual


def test_identical_trees_report_no_drift(trees):
    expected, actual = trees
    for root in (expected, actual):
        _write(root, "models/__init__.py", "x = 1\n")
        _write(root, "api/foo.py", "def foo():\n    return 1\n")
    assert diff_trees(expected, actual) == []


def test_changed_file_is_reported(trees):
    expected, actual = trees
    _write(expected, "models/item.py", "value = 1\n")
    _write(actual, "models/item.py", "value = 2\n")
    assert diff_trees(expected, actual) == [("changed", "models/item.py")]


def test_file_only_in_actual_is_reported(trees):
    """A file the fresh regen produces but the committed tree lacks (stale client)."""
    expected, actual = trees
    _write(actual, "models/domain_out.py", "x = 1\n")
    assert diff_trees(expected, actual) == [("only_in_actual", "models/domain_out.py")]


def test_file_only_in_expected_is_reported(trees):
    """A file the committed tree has but the regen no longer produces (removed upstream)."""
    expected, actual = trees
    _write(expected, "models/retired.py", "x = 1\n")
    assert diff_trees(expected, actual) == [("only_in_expected", "models/retired.py")]


def test_pycache_and_ruff_cache_are_ignored(trees):
    expected, actual = trees
    _write(expected, "models/item.py", "v = 1\n")
    _write(actual, "models/item.py", "v = 1\n")
    # Noise that must never count as drift.
    _write(actual, "__pycache__/item.cpython-312.pyc", "binary-ish\n")
    _write(actual, "models/__pycache__/item.cpython-312.pyc", "binary-ish\n")
    _write(actual, ".ruff_cache/0.1.2/abc", "cache\n")
    assert diff_trees(expected, actual) == []


def test_nested_paths_use_relative_posix_paths(trees):
    expected, actual = trees
    _write(expected, "api/info_items/get.py", "a = 1\n")
    _write(actual, "api/info_items/get.py", "a = 2\n")
    assert diff_trees(expected, actual) == [("changed", "api/info_items/get.py")]


def test_results_are_sorted_and_aggregate_all_drift(trees):
    expected, actual = trees
    _write(expected, "models/a.py", "1\n")
    _write(actual, "models/a.py", "2\n")  # changed
    _write(actual, "models/b.py", "1\n")  # only_in_actual
    _write(expected, "models/c.py", "1\n")  # only_in_expected
    assert diff_trees(expected, actual) == [
        ("changed", "models/a.py"),
        ("only_in_actual", "models/b.py"),
        ("only_in_expected", "models/c.py"),
    ]
