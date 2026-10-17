"""Guard: ``bind_info_source`` is the only writer of a new ``info_item_sources`` row (archiver#390).

Every new active binding is a primary binding, and every one has to emit
``info_item_primary_changed`` on ``info.changes``. Four bind paths once built the
row inline and emitted nothing, so a subscriber tracking succession never heard
of them. The emit now lives inside the tool, and this sweep refuses any other
site in ``src/`` that could insert a row: a constructor call, a Core ``insert``
reaching the model or its table, an aliased import (an alias dodges the name
check), or raw SQL inserting into the table. Updates are out of scope: rows are
never reactivated since #392, and a reactivation would be an ``UPDATE``.

The reverse failure is guarded too (CR 2): any reference to
``emit_primary_changed`` outside the tool. A route that binds and then emits
again, as ``POST …/info-sources`` did before #390, would emit twice.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
HOME = Path("src/core/tools/bind_info_source.py")
MODEL = "InfoItemSource"
ALLOWED_WRITER = "bind_info_source"
EMITTER = "emit_primary_changed"
_RAW_INSERT = re.compile(r'insert\s+into\s+("?\w+"?\.)?"?info_item_sources\b', re.IGNORECASE)


def _names_model(node: ast.AST) -> bool:
    return any(
        (isinstance(n, ast.Name) and n.id == MODEL)
        or (isinstance(n, ast.Attribute) and n.attr == MODEL)
        for n in ast.walk(node)
    )


def _callee(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def binding_violations(source: str, relpath: Path) -> list[str]:
    """Every site in *source* that could insert a binding row or emit beside the tool.

    The sanctioned one is inside ``bind_info_source`` in
    ``src/core/tools/bind_info_source.py``.
    """
    tree = ast.parse(source)
    allowed: set[int] = set()
    if relpath == HOME:
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == ALLOWED_WRITER:
                allowed.update(id(n) for n in ast.walk(node))

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if id(node) in allowed:
            continue
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == MODEL and alias.asname not in (None, MODEL):
                    found.append((node.lineno, f"aliases {MODEL}"))
                elif alias.name == EMITTER:
                    found.append((node.lineno, f"imports {EMITTER}"))
        elif isinstance(node, ast.Name) and node.id == EMITTER:
            found.append((node.lineno, f"references {EMITTER}"))
        elif isinstance(node, ast.Attribute) and node.attr == EMITTER:
            found.append((node.lineno, f"references .{EMITTER}"))
        elif isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == MODEL) or (
                isinstance(func, ast.Attribute) and func.attr == MODEL
            ):
                found.append((node.lineno, f"constructs {MODEL}"))
            elif _callee(func).endswith("insert"):
                # insert(M), pg_insert(M), postgresql.insert(M), M.__table__.insert()
                receiver = func.value if isinstance(func, ast.Attribute) else None
                if any(_names_model(a) for a in node.args) or (
                    receiver is not None and _names_model(receiver)
                ):
                    found.append((node.lineno, f"inserts {MODEL}"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _RAW_INSERT.search(node.value):
                found.append((node.lineno, "inserts info_item_sources in SQL"))
    # ast.walk is breadth-first; report in source order.
    return [f"{relpath}:{line} {what}" for line, what in sorted(found)]


def test_only_bind_info_source_writes_a_binding():
    violations = []
    for path in sorted(SRC.rglob("*.py")):
        violations += binding_violations(path.read_text(), path.relative_to(ROOT))
    assert violations == [], f"bind through bind_info_source, which emits: {violations}"


def test_the_sweep_sees_the_sanctioned_writer():
    """A vacuous pass otherwise: a sweep that finds nothing anywhere also passes."""
    home = (ROOT / HOME).read_text()
    renamed = home.replace(f"async def {ALLOWED_WRITER}(", "async def somewhere_else(")
    assert binding_violations(home, HOME) == []
    assert binding_violations(renamed, HOME) != []


def test_the_sweep_catches_an_inline_constructor():
    planted = (
        "from src.core.models import InfoItemSource\n"
        "\n"
        "def bind(db, item, source):\n"
        "    db.add(InfoItemSource(info_item_id=item, info_source_id=source))\n"
    )
    assert binding_violations(planted, Path("src/dashboard/routes/x.py")) == [
        "src/dashboard/routes/x.py:4 constructs InfoItemSource"
    ]


def test_the_sweep_catches_a_constructor_through_the_module():
    planted = "from src.core import models\n\nmodels.InfoItemSource(info_item_id=1)\n"
    assert binding_violations(planted, Path("src/x.py")) == ["src/x.py:3 constructs InfoItemSource"]


def test_the_sweep_catches_an_aliased_import():
    planted = "from src.core.models import InfoItemSource as Binding\n"
    assert binding_violations(planted, Path("src/x.py")) == ["src/x.py:1 aliases InfoItemSource"]


def test_the_sweep_catches_a_core_insert():
    planted = (
        "from sqlalchemy import insert\n"
        "from src.core.models import InfoItemSource\n"
        "\n"
        "a = insert(InfoItemSource).values(info_item_id=1)\n"
        "b = InfoItemSource.__table__.insert()\n"
    )
    assert binding_violations(planted, Path("src/x.py")) == [
        "src/x.py:4 inserts InfoItemSource",
        "src/x.py:5 inserts InfoItemSource",
    ]


def test_the_sweep_catches_the_dialect_inserts():
    """``pg_insert`` is this repo's upsert idiom; the model may sit in the args (CR 7)."""
    planted = (
        "from sqlalchemy.dialects import postgresql\n"
        "from sqlalchemy.dialects.postgresql import insert as pg_insert\n"
        "from src.core.models import InfoItemSource\n"
        "\n"
        "a = pg_insert(InfoItemSource).on_conflict_do_nothing()\n"
        "b = postgresql.insert(InfoItemSource)\n"
    )
    assert binding_violations(planted, Path("src/x.py")) == [
        "src/x.py:5 inserts InfoItemSource",
        "src/x.py:6 inserts InfoItemSource",
    ]


def test_the_sweep_catches_quoted_raw_sql():
    planted = 'SQL = \'INSERT INTO "information"."info_item_sources" (id) VALUES (:i)\'\n'
    assert binding_violations(planted, Path("src/x.py")) == [
        "src/x.py:1 inserts info_item_sources in SQL"
    ]


def test_the_sweep_catches_raw_sql():
    planted = 'SQL = "INSERT INTO information.info_item_sources (info_item_id) VALUES (:i)"\n'
    assert binding_violations(planted, Path("src/x.py")) == [
        "src/x.py:1 inserts info_item_sources in SQL"
    ]


def test_the_sweep_catches_a_second_emitter():
    """A site that binds and then emits again double-emits: the shape #390 removed."""
    planted = (
        "from src.core.tools.bind_info_source import bind_info_source, emit_primary_changed\n"
        "from src.core.tools import bind_info_source as tool\n"
        "\n"
        "async def route(db, i, s):\n"
        "    await bind_info_source(db, info_item_id=i, info_source_id=s)\n"
        "    emit_primary_changed(db, info_item_id=i, new_info_source_id=s)\n"
        "    tool.emit_primary_changed(db)\n"
    )
    assert binding_violations(planted, Path("src/x.py")) == [
        "src/x.py:1 imports emit_primary_changed",
        "src/x.py:6 references emit_primary_changed",
        "src/x.py:7 references .emit_primary_changed",
    ]


def test_reads_and_updates_pass():
    planted = (
        "from sqlalchemy import select, update\n"
        "from src.core.models import InfoItemSource\n"
        "\n"
        "q = select(InfoItemSource).where(InfoItemSource.deactivated_at.is_(None))\n"
        "u = update(InfoItemSource).values(deactivated_at=None)\n"
    )
    assert binding_violations(planted, Path("src/x.py")) == []
