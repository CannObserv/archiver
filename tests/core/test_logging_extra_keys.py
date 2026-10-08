"""Guard: no ``extra`` key in ``src`` collides with a ``LogRecord`` attribute (archiver#327 CR 3).

``Logger.makeRecord`` raises ``KeyError`` for an ``extra`` key that names a
record attribute (``name``, ``msg``, ``module``...) or ``message``/``asctime``:
the log call itself crashes its caller. The follower's ``pm_org_missing``
carried ``"name"`` and would have ended every hourly sweep. Spied or disabled
loggers in tests never build a record, so this reads the source instead.
Literal keys only: ``extra={...}`` and ``extra=dict(...)``.
"""

import ast
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RESERVED = frozenset(vars(logging.LogRecord("n", logging.INFO, "p", 0, "m", (), None))) | {
    "message",
    "asctime",
}


def _extra_keys(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "extra":
                continue
            value = kw.value
            if isinstance(value, ast.Dict):
                found += [
                    (k.lineno, k.value)
                    for k in value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                ]
            elif (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "dict"
            ):
                found += [(value.lineno, k.arg) for k in value.keywords if k.arg]
    return found


def test_no_extra_key_collides_with_a_log_record_attribute():
    collisions = sorted(
        f"{path.relative_to(ROOT)}:{line} {key!r}"
        for path in (ROOT / "src").rglob("*.py")
        for line, key in _extra_keys(ast.parse(path.read_text(encoding="utf-8")))
        if key in RESERVED
    )
    assert not collisions, f"rename these extra keys (e.g. name -> org_name): {collisions}"


def test_the_scan_catches_a_planted_collision():
    planted = ast.parse(
        'logger.warning("x", extra={"pm_org_id": 1, "name": 2})\n'
        'logger.info("y", extra=dict(module="m"))\n'
    )
    assert {key for _, key in _extra_keys(planted)} >= {"name", "module"}
    assert {"name", "module", "msg", "message", "asctime"} <= RESERVED
