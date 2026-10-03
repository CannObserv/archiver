"""Guard: ``effective_rep_fields`` is the only caller of ``resolve_rep_fields`` (archiver#303).

Every consumer of an InfoItem's bag - render, the ``required_fields`` check, the
probe, issuance, the tool routes, ``set_rep_fields`` - has to agree on what a
path is. #304 overlays the linked Power Map org inside ``effective_rep_fields``;
a site that resolved the stored bag directly would render a different path from
the rest without failing anything. So the sweep refuses any *reference* to
``resolve_rep_fields`` in ``src/`` outside that one function: a call, an import
(an alias would dodge a name check), or an attribute reach through the module.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from src.core.rep_fields_schema.validator import validate_rep_fields_against_spec
from src.core.replication.destination import probe_destination, render_destination
from src.core.tools.rep_fields_gate import check_bag_against_spec

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
HOME = Path("src/core/rep_fields.py")
TARGET = "resolve_rep_fields"
ALLOWED_CALLER = "effective_rep_fields"


def resolve_violations(source: str, relpath: Path) -> list[str]:
    """Every reference to ``resolve_rep_fields`` in *source* other than its sanctioned one.

    The sanctioned one is a reference inside ``effective_rep_fields`` in
    ``src/core/rep_fields.py``. The ``def`` itself is a definition, not a
    reference, so it is never reported.
    """
    tree = ast.parse(source)
    allowed: set[int] = set()
    if relpath == HOME:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == ALLOWED_CALLER:
                allowed.update(id(n) for n in ast.walk(node))

    violations: list[str] = []
    for node in ast.walk(tree):
        if id(node) in allowed:
            continue
        if isinstance(node, ast.ImportFrom) and any(a.name == TARGET for a in node.names):
            violations.append(f"{relpath}:{node.lineno} imports {TARGET}")
        elif isinstance(node, ast.Name) and node.id == TARGET:
            violations.append(f"{relpath}:{node.lineno} references {TARGET}")
        elif isinstance(node, ast.Attribute) and node.attr == TARGET:
            violations.append(f"{relpath}:{node.lineno} references .{TARGET}")
    return violations


def test_only_effective_rep_fields_resolves_a_bag():
    violations = []
    for path in sorted(SRC.rglob("*.py")):
        violations += resolve_violations(path.read_text(), path.relative_to(ROOT))
    assert violations == [], f"resolve through effective_rep_fields(bag, org): {violations}"


def test_the_sweep_sees_the_sanctioned_call():
    """A vacuous pass otherwise: a sweep that finds nothing anywhere also passes."""
    home = (ROOT / HOME).read_text()
    renamed = home.replace(f"def {ALLOWED_CALLER}(", "def somewhere_else(")
    assert resolve_violations(home, HOME) == []
    assert resolve_violations(renamed, HOME) != []


def test_the_sweep_catches_a_direct_call():
    planted = (
        "from src.core.rep_fields import resolve_rep_fields\n"
        "\n"
        "def render(bag):\n"
        "    return resolve_rep_fields(bag)\n"
    )
    assert resolve_violations(planted, Path("src/core/replication/planted.py")) == [
        f"src/core/replication/planted.py:1 imports {TARGET}",
        f"src/core/replication/planted.py:4 references {TARGET}",
    ]


def test_the_sweep_catches_an_aliased_import():
    planted = "from src.core.rep_fields import resolve_rep_fields as r\n\nr({})\n"
    assert resolve_violations(planted, Path("src/x.py")) == [f"src/x.py:1 imports {TARGET}"]


def test_the_sweep_catches_a_reach_through_the_module():
    planted = "from src.core import rep_fields\n\nrep_fields.resolve_rep_fields({})\n"
    assert resolve_violations(planted, Path("src/x.py")) == [f"src/x.py:3 references .{TARGET}"]


def test_the_sweep_catches_a_call_elsewhere_in_the_home_module():
    planted = (
        "def resolve_rep_fields(bag):\n"
        "    return bag\n"
        "\n"
        "def effective_rep_fields(bag, org):\n"
        "    return resolve_rep_fields(bag)\n"
        "\n"
        "def shortcut(bag):\n"
        "    return resolve_rep_fields(bag)\n"
    )
    assert resolve_violations(planted, HOME) == [f"{HOME}:8 references {TARGET}"]


@pytest.mark.parametrize(
    "consumer",
    [
        render_destination,
        probe_destination,
        validate_rep_fields_against_spec,
        check_bag_against_spec,
    ],
)
def test_every_consumer_names_its_org(consumer):
    """``org`` is keyword-only with no default: a call site that forgets it fails loudly.

    Until #304 every caller passes ``org=None``; a default would let a new one
    omit it and keep resolving the stored bag alone once #304 links orgs.
    """
    param = inspect.signature(consumer).parameters["org"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty
