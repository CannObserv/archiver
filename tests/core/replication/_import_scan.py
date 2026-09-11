"""Static import scanning, shared by the layering and delegation guards (CR 7).

Extracted from ``test_layering``, which owned it while it had one caller. A
second guard — ``test_destination``'s check that the ``mimetypes`` fallback has
not come back — needs the same answer, and importing a *test* module for a
private helper made one guard's collection depend on another's.

**Both callers ask the same question**: what does this file reach, however the
author spelled it. A grep answers a different and weaker one, which is the
distinction CR 9-11 and CR 3 were each filed about.

**Paths must be inside the repository** when the file contains a relative
import: resolving one means knowing which package the importing file sits in,
and :func:`package_of` computes that against the repo root. An absolute-only
file (a planted snippet under ``tmp_path``, say) is scanned correctly from
anywhere, because the relative branch never runs.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def package_of(path: Path) -> str:
    """The dotted package a module at *path* lives in, e.g. ``src.core.replication``.

    Raises:
        ValueError: *path* is outside the repository, so there is no package
            name to give it.
    """
    return ".".join(path.resolve().parent.relative_to(ROOT).parts)


def resolved_relative(path: Path, node: ast.ImportFrom) -> str:
    """The absolute module name a relative ``ImportFrom`` denotes (CR 9).

    ``level`` counts the leading dots: one means this package, two the parent,
    and so on. ``node.module`` is only the tail, so the name a relative import
    actually reaches has to be rebuilt from the importing file's own location.
    Dropping these is what let ``from ..tools.assign_rep_spec import …`` name
    the forbidden layer and read as no import at all.
    """
    parts = package_of(path).split(".")
    base = parts[: len(parts) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, however it spells the import.

    ``import x``, ``import x as y`` and ``from x import y`` all yield ``x``, and
    relative imports resolve to their absolute names, so the set answers "what
    does this module reach" rather than "what did the author type".
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.add(resolved_relative(path, node))
            elif node.module:
                names.add(node.module)
    return names


def assigned_names(path: Path) -> set[str]:
    """Every name this module binds by assignment, at any nesting depth.

    Sees a binding a ``hasattr`` check cannot — one created under a conditional,
    or shadowed before import time — and misses one built dynamically, which is
    why ``test_destination`` keeps both.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names
