"""Derive the outbound env-var surface from ``src/`` by static analysis.

Why this exists (archiver#157, and CannObserv/watcher#277 as the recurrence).

``tests/conftest.py`` scrubs a hand-maintained tuple of environment variables
so a suite run cannot inherit a live production resource from a sourced env
file. ``test_outbound_service_env_is_scrubbed`` guards that tuple, but only by
iterating it: it asserts the *listed* names are absent from the environment. A
variable that was never added to the list is invisible to it. The scrub simply
does not cover the new integration, and nothing goes red.

That gap is not theoretical. Watcher's notifier client reads
``NOTIFIER_BASE_URL``/``NOTIFIER_API_KEY`` directly from ``os.environ``; its
conftest scrubs the bus variables and never gained those two; a pytest run in a
prod-sourced shell therefore dispatches to production notifier, as the
production tenant, successfully and silently. Archiver's own #157 was the same
shape under a different name (``WATCHER_BASE_URL``). #142 deleted that specific
route, but the registry can drift again the moment archiver grows its next
outbound integration.

So this module inverts the direction of the check. Rather than trusting a
hand-kept list to be complete, it reads ``src/`` and reports every environment
variable the application actually consults. The caller then asserts that each
resource-addressing one is either scrubbed or explicitly exempted with a
reason. Forgetting the scrub becomes a test failure instead of a silent hole.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

#: Name suffixes that mark a variable as *addressing an external resource* -
#: something a process can connect to, authenticate against, or write into.
#:
#: The classifier is deliberately name-shaped rather than value-shaped: it must
#: fire on a variable that is merely *declared*, long before anything sets it,
#: and on this VM the sibling services already agree on these conventions
#: (``*_BASE_URL``, ``*_API_KEY``, ``*_DATABASE_URL``). Tuning knobs and build
#: metadata are not resources and are not swept up.
#:
#: A new outbound integration that follows none of these conventions would slip
#: past. That is an accepted limit: the failure mode this guards is *forgetting*
#: the scrub while following house naming, not deliberately evading it. The
#: in-repo example is ``ARCHIVER_WHEELHOUSE_BUCKET`` (``scripts/sync_wheelhouse.py``),
#: which addresses a real GCS bucket under a name no suffix here matches - it is
#: harmless because ``scripts/`` is not among SCANNED_ROOTS and does not run in
#: the test process, but it shows the shape of what this classifier cannot see.
_OUTBOUND_NAME_SUFFIXES = (
    "_URL",
    "_URI",
    "_DSN",
    "_ENDPOINT",
    "_HOST",
    "_API_KEY",
    "_TOKEN",
    "_SECRET",
    "_PASSWORD",
    "_CREDENTIALS",
)

#: Outbound-shaped variables that a test process may legitimately hold, each
#: with the reason it is safe. An entry here is a claim that some *other*
#: mechanism contains the variable - state which, so the exemption can be
#: re-checked when that mechanism changes.
_OUTBOUND_ENV_ALLOWLIST = {
    "ARCHIVER_DATABASE_URL": (
        "Pinned, not scrubbed. conftest sets it to TEST_DATABASE_URL at import "
        "and _check_test_url_safety refuses a value equal to the production "
        "URL, so the test process holds a deliberately non-production value. "
        "Scrubbing it instead would leave the suite with no database at all."
    ),
    "DATABASE_URL": (
        "Pinned for the same reason: src/core/database.py falls back to it when "
        "ARCHIVER_DATABASE_URL is unset, so conftest pins both. "
        "scripts/dev_server.sh clears it outright for the same fallback reason."
    ),
    "ARCHIVER_PUBLIC_BASE_URL": (
        "Not dialed. It is interpolated into rep-spec public_url values and "
        "bus payloads as text; no code path opens a connection to it, so "
        "inheriting production's value causes no side effect."
    ),
}


#: Trees scanned by the registry guard: everything that reads the environment
#: *inside the pytest process*.
#:
#: ``src/`` is the application. ``alembic/`` is here because ``tests/conftest.py``
#: runs ``alembic_command.upgrade`` in an executor thread at session setup, so
#: ``alembic/env.py`` consults ``os.environ`` under pytest exactly as ``src/``
#: does; scanning only ``src/`` left a file that genuinely runs under the suite
#: outside the guard (CR round 1, finding 2).
#:
#: ``scripts/`` is deliberately absent - those run by hand or in CI, never inside
#: the test process, so the conftest scrub they would be measured against does
#: not apply to them.
SCANNED_ROOTS = (
    _REPO_ROOT / "src",
    _REPO_ROOT / "alembic",
)


def outbound_shaped(name: str) -> bool:
    """Whether ``name`` looks like it addresses an external resource."""
    return name.endswith(_OUTBOUND_NAME_SUFFIXES)


def _module_level_string_constants(trees: dict[Path, ast.Module]) -> dict[str, set[str]]:
    """Map ``NAME -> {"literal", ...}`` for module-level string assignments.

    Collected across the whole tree rather than per file because the read and
    the definition routinely live apart: ``src/core/db_safety.py`` defines
    ``ALLOW_PRODUCTION_DB_ENV`` and ``src/api/main.py`` imports it to read the
    environment with.

    Each name maps to the *set* of every literal bound to it anywhere in the
    tree, deliberately not to one winner. Import graphs are not resolved here,
    so two modules defining the same constant name are indistinguishable to this
    pass; keeping one flat ``name -> literal`` map meant the later-sorted file
    overwrote the earlier, and a read in the earlier module then resolved to the
    *wrong* variable while the real one went unrecorded - a hole, in the guard
    whose whole job is not to have one (CR round 1, finding 1). Unioning makes a
    collision over-report instead: both variables are treated as read, which
    surfaces as a spurious registry entry someone must account for. That is the
    only safe direction, because a spurious entry is visible and cheap while a
    swallowed read is neither.
    """
    constants: dict[str, set[str]] = {}
    for tree in trees.values():
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants.setdefault(target.id, set()).add(node.value.value)
    return constants


def _env_names_from(node: ast.expr, constants: dict[str, set[str]]) -> set[str]:
    """Every env-var name an argument may denote; empty when it cannot be resolved.

    An empty result means *unresolvable*, not *no name* - callers that care
    about the difference use :func:`unresolvable_env_reads_under`.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        return set(constants.get(node.id, ()))
    return set()


def _is_environ_attribute(node: ast.expr) -> bool:
    """Whether ``node`` is ``os.environ`` (or a bare ``environ``)."""
    if isinstance(node, ast.Attribute):
        return node.attr == "environ"
    return isinstance(node, ast.Name) and node.id == "environ"


def _parse_trees(root: Path) -> dict[Path, ast.Module]:
    """Parse every Python source under ``root``."""
    return {
        path: ast.parse(path.read_text(), filename=str(path)) for path in sorted(root.rglob("*.py"))
    }


def _env_read_arguments(trees: dict[Path, ast.Module]) -> Iterator[tuple[Path, ast.expr]]:
    """Yield ``(path, argument_node)`` for every environment read in ``trees``.

    Recognises the three spellings that appear in this codebase -
    ``os.environ.get(X)``, ``os.getenv(X)``, and ``os.environ[X]`` - and nothing
    else, so an unrelated ``dict.get("SOME_URL")`` is not mistaken for one.

    Reads are what matter, not writes: a variable the application never consults
    cannot leak a production resource into it, however it got into the process.
    """
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and _is_environ_attribute(node.value):
                yield path, node.slice
                continue

            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            is_environ_get = func.attr == "get" and _is_environ_attribute(func.value)
            is_getenv = func.attr == "getenv"
            if is_environ_get or is_getenv:
                yield path, node.args[0]


def env_names_read_under(root: Path) -> set[str]:
    """Every environment variable name read by the Python sources under ``root``.

    Name-mediated arguments resolve through module-level string constants, so
    the ``os.environ.get(ALLOW_PRODUCTION_DB_ENV)`` indirection is not missed.
    Arguments that resolve to no literal contribute nothing here and are
    reported separately by :func:`unresolvable_env_reads_under`.
    """
    trees = _parse_trees(root)
    constants = _module_level_string_constants(trees)
    return {
        name for _, arg in _env_read_arguments(trees) for name in _env_names_from(arg, constants)
    }


def unresolvable_env_reads_under(root: Path) -> list[str]:
    """``"path:line"`` for each environment read whose name cannot be resolved.

    A computed argument - ``os.environ.get(f"{prefix}_API_KEY")``, a concatenation,
    a function's return value - denotes a variable this static pass cannot name.
    Returning nothing for those made an unscannable read indistinguishable from
    no read at all, which is a fail-open in a guard (CR round 1, finding 3). The
    guard cannot classify what it cannot name, so it reports the site instead and
    lets the caller decide; today the caller fails the suite, which keeps the
    unscannable case loud rather than absent.
    """
    trees = _parse_trees(root)
    constants = _module_level_string_constants(trees)
    return [
        f"{path.relative_to(root)}:{arg.lineno}"
        for path, arg in _env_read_arguments(trees)
        if not _env_names_from(arg, constants)
    ]
