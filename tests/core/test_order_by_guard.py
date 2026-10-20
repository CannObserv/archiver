"""Guard: every ``order_by`` in ``src/`` sorts into a total order (archiver#149).

Postgres returns rows that tie on every sort key in whatever order the plan
produces, so a list ordered by ``created_at`` alone can come back reshuffled
between two identical requests, and an offset-paginated one can skip or repeat
a row across pages. The issue named one such site; the 2026-10-13 triage found
six more. This sweep ends the class instead of waiting for the next sweep.

The rule is positive: an ``order_by`` passes when its keys include every column
of a primary key or a non-partial unique key of one mapped model (the models'
own metadata decides), or every ``group_by`` key of the same chain, which is
unique per result row. Anything else - a timestamp, a name, an aggregate, a
label - is a violation unless ``ALLOWED`` carries it with a reason.

Both spellings are swept: the ``.order_by(...)`` method and the ``order_by=``
keyword (``relationship``, ``.over``), where ties reshuffle a collection or a rank.

Limits accepted: a key unique in its table is taken as unique in a joined
result, which holds only for to-one joins; raw SQL ``ORDER BY`` is not parsed.
"""

from __future__ import annotations

import ast
from collections import Counter
from functools import cache
from pathlib import Path

from sqlalchemy import Column, Index, Integer, MetaData, Table, Text, UniqueConstraint

from src.core.models import Base

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

# (file, the sort as written: "order_by(...)" or "order_by=...") -> why it is already total.
ALLOWED: dict[tuple[str, str], str] = {
    ("src/dashboard/routes/info_items.py", "order_by(PmOrganization.name)"): (
        "selects only PmOrganization.name, so tied rows are identical output"
    ),
    ("src/core/services/source_revision.py", "order_by(InfoItemSource.info_item_id)"): (
        "filtered to active bindings, where uq_info_item_sources_active makes info_item_id unique"
    ),
}

_DIRECTIONS = {"asc", "desc", "nulls_first", "nulls_last", "nullsfirst", "nullslast"}


def _unique_keys(table: Table) -> list[frozenset[Column]]:
    keys = [frozenset(table.primary_key.columns)]
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            keys.append(frozenset(constraint.columns))
    for index in table.indexes:
        if isinstance(index, Index) and index.unique:
            if index.dialect_options["postgresql"].get("where") is None:
                keys.append(frozenset(index.columns))
    keys += [frozenset([c]) for c in table.columns if c.unique]
    # UNIQUE admits many NULLs, so a key over a nullable column can still tie.
    return [k for k in keys if k and not any(c.nullable for c in k)]


_MAPPERS = {m.class_.__name__: m for m in Base.registry.mappers}


def _strip_direction(node: ast.expr) -> ast.expr:
    """``X.desc()``, ``X.desc().nulls_last()`` and ``desc(X)`` all sort on ``X``."""
    while isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _DIRECTIONS and not node.args:
            node = func.value
        elif isinstance(func, ast.Name) and func.id in _DIRECTIONS and len(node.args) == 1:
            node = node.args[0]
        else:
            break
    return node


def _column(node: ast.expr) -> Column | None:
    """``Model.attr`` resolved through the mapper, or None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        mapper = _MAPPERS.get(node.value.id)
        if mapper is not None and node.attr in mapper.columns:
            return mapper.columns[node.attr]
    return None


def _group_by_keys(call: ast.Call) -> set[str] | None:
    """The ``group_by`` keys earlier in the same method chain, if any."""
    if not isinstance(call.func, ast.Attribute):
        return None
    node = call.func.value
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "group_by":
            return {ast.unparse(a) for a in node.args}
        node = node.func.value
    return None


def _is_total(written_keys: list[ast.expr], grouped: set[str] | None) -> bool:
    keys = [_strip_direction(a) for a in written_keys]
    if grouped and grouped <= {ast.unparse(k) for k in keys}:
        return True
    columns = {c for c in map(_column, keys) if c is not None}
    tables = {c.table for c in columns}
    return any(key <= columns for table in tables for key in _unique_keys(table))


# (keys, the chain's group_by keys if any, line, the sort as written)
_Site = tuple[list[ast.expr], set[str] | None, int, str]


def _order_by_calls(tree: ast.AST) -> list[_Site]:
    """Each sort: ``.order_by(...)`` with arguments, and any ``order_by=`` keyword
    (``relationship``, ``.over``, ``aggregate_order_by``). A keyword sort has no
    method chain, so no ``group_by`` keys."""
    sites: list[_Site] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "order_by" and node.args:
            written = f"order_by({', '.join(ast.unparse(a) for a in node.args)})"
            line = func.end_lineno or node.lineno
            sites.append((node.args, _group_by_keys(node), line, written))
        for kw in node.keywords:
            if kw.arg == "order_by":
                v = kw.value
                keys = list(v.elts) if isinstance(v, ast.List | ast.Tuple) else [v]
                sites.append((keys, None, kw.lineno, f"order_by={ast.unparse(v)}"))
    return sites


def _violations(sites: list[_Site], relpath: Path) -> list[str]:
    found = [
        (line, written)
        for keys, grouped, line, written in sites
        if (str(relpath), written) not in ALLOWED and not _is_total(keys, grouped)
    ]
    return [f"{relpath}:{line} {what}" for line, what in sorted(found)]


def order_by_violations(source: str, relpath: Path) -> list[str]:
    """Every ``order_by`` in *source* whose keys do not include a unique key."""
    return _violations(_order_by_calls(ast.parse(source)), relpath)


@cache
def _sweep() -> tuple[list[str], Counter[tuple[str, str]]]:
    """One parse of ``src/``, shared by the tests below."""
    violations: list[str] = []
    seen: Counter[tuple[str, str]] = Counter()
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT)
        sites = _order_by_calls(ast.parse(path.read_text()))
        violations += _violations(sites, rel)
        seen.update((str(rel), written) for *_, written in sites)
    return violations, seen


def test_every_order_by_in_src_is_total():
    violations, _ = _sweep()
    assert violations == [], (
        f"end each order_by in a primary or unique key (archiver#149): {violations}"
    )


def test_every_allowlist_entry_names_exactly_one_site():
    """A stale entry would pre-approve whatever lands under its text next, and a
    shared one approves a second site its reason was never written for (CR 1)."""
    _, seen = _sweep()
    assert {key: seen[key] for key in ALLOWED} == dict.fromkeys(ALLOWED, 1)


def test_the_sweep_sees_order_by_sites():
    """A vacuous pass otherwise: a sweep that parses nothing also finds nothing."""
    _, seen = _sweep()
    assert len(seen) > 30


def _check(body: str) -> list[str]:
    return order_by_violations(body, Path("src/x.py"))


def test_a_timestamp_alone_is_caught():
    assert _check("q = select(InfoItem).order_by(InfoItem.created_at.desc())\n") == [
        "src/x.py:1 order_by(InfoItem.created_at.desc())"
    ]


def test_a_non_unique_name_is_caught():
    assert _check("q = select(PmOrganization).order_by(PmOrganization.name)\n") == [
        "src/x.py:1 order_by(PmOrganization.name)"
    ]


def test_an_aggregate_is_caught():
    planted = "q = select(InfoSource.domain_name).order_by(func.count().desc())\n"
    assert _check(planted) == ["src/x.py:1 order_by(func.count().desc())"]


def test_a_partial_unique_index_is_not_a_unique_key():
    """``uq_info_item_sources_active`` holds only for active rows."""
    assert _check("q = select(X).order_by(InfoItemSource.info_item_id)\n") == [
        "src/x.py:1 order_by(InfoItemSource.info_item_id)"
    ]


def test_a_nullable_unique_key_is_not_a_total_order():
    """Postgres UNIQUE admits many NULLs, so NULL rows still tie (CR 2)."""
    table = Table(
        "planted",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("code", Text, nullable=True, unique=True),
        Column("slug", Text, nullable=False, unique=True),
    )
    keys = _unique_keys(table)
    assert frozenset([table.c.code]) not in keys
    assert frozenset([table.c.slug]) in keys


def test_a_pk_in_any_direction_passes():
    planted = (
        "a = select(InfoItem).order_by(InfoItem.created_at.desc(), InfoItem.info_item_id.desc())\n"
        "b = select(InfoItem).order_by(InfoItem.created_at, desc(InfoItem.info_item_id))\n"
        "c = select(SourceRevision).order_by("
        "SourceRevision.source_revision_id.desc().nulls_last())\n"
    )
    assert _check(planted) == []


def test_a_unique_constraint_passes():
    """``uq_domains_name``."""
    assert _check("q = select(Domain).order_by(Domain.name)\n") == []


def test_the_full_group_by_key_passes():
    planted = (
        "q = (select(InfoSource.domain_name, func.count())"
        ".group_by(InfoSource.domain_name)"
        ".order_by(func.count().desc(), InfoSource.domain_name))\n"
    )
    assert _check(planted) == []


def test_part_of_a_group_by_key_is_caught():
    planted = "q = select(A).group_by(A.x, A.y).order_by(func.count(), A.x)\n"
    assert _check(planted) == ["src/x.py:1 order_by(func.count(), A.x)"]


def test_an_unknown_model_is_caught():
    """No mapper, no metadata to vouch for it."""
    assert _check("q = select(T).order_by(T.id)\n") == ["src/x.py:1 order_by(T.id)"]


def test_the_allowlist_matches_by_file():
    planted = "q = select(PmOrganization.name).order_by(PmOrganization.name)\n"
    assert order_by_violations(planted, Path("src/dashboard/routes/info_items.py")) == []
    assert _check(planted) == ["src/x.py:1 order_by(PmOrganization.name)"]


def test_the_keyword_spelling_is_caught():
    """``relationship(order_by=…)`` and ``.over(order_by=…)`` tie the same way (CR 7)."""
    planted = (
        "r = relationship(ApiKey, order_by=ApiKey.created_at)\n"
        "w = func.row_number().over(partition_by=X.y, order_by=[SourceRevision.captured_at])\n"
        "ok = func.row_number().over(order_by=(ApiKey.created_at, ApiKey.id))\n"
    )
    assert _check(planted) == [
        "src/x.py:1 order_by=ApiKey.created_at",
        "src/x.py:2 order_by=[SourceRevision.captured_at]",
    ]
