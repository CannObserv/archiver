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
from pathlib import Path

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
#: the scrub while following house naming, not deliberately evading it.
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


def outbound_shaped(name: str) -> bool:
    """Whether ``name`` looks like it addresses an external resource."""
    return name.endswith(_OUTBOUND_NAME_SUFFIXES)


def _module_level_string_constants(trees: dict[Path, ast.Module]) -> dict[str, str]:
    """Map ``NAME -> "literal"`` for module-level string assignments in ``trees``.

    Collected across the whole tree rather than per file because the read and
    the definition routinely live apart: ``src/core/db_safety.py`` defines
    ``ALLOW_PRODUCTION_DB_ENV`` and ``src/api/main.py`` imports it to read the
    environment with. Names are assumed unique across the package, which holds
    here and fails safe if it ever stops - a collision over-reports a variable
    as read, which surfaces as a spurious registry entry rather than a hole.
    """
    constants: dict[str, str] = {}
    for tree in trees.values():
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    return constants


def _env_name_from(node: ast.expr, constants: dict[str, str]) -> str | None:
    """Resolve an env-var-name argument to the literal it denotes, if it can be."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _is_environ_attribute(node: ast.expr) -> bool:
    """Whether ``node`` is ``os.environ`` (or a bare ``environ``)."""
    if isinstance(node, ast.Attribute):
        return node.attr == "environ"
    return isinstance(node, ast.Name) and node.id == "environ"


def env_names_read_under(root: Path) -> set[str]:
    """Every environment variable name read by the Python sources under ``root``.

    Recognises the three spellings that appear in this codebase -
    ``os.environ.get(X)``, ``os.getenv(X)``, and ``os.environ[X]`` - and
    resolves a name-mediated argument through module-level string constants, so
    the ``os.environ.get(ALLOW_PRODUCTION_DB_ENV)`` indirection is not missed.

    Reads are what matter, not writes: a variable the application never consults
    cannot leak a production resource into it, however it got into the process.
    """
    trees: dict[Path, ast.Module] = {}
    for path in sorted(root.rglob("*.py")):
        trees[path] = ast.parse(path.read_text(), filename=str(path))

    constants = _module_level_string_constants(trees)
    names: set[str] = set()

    for tree in trees.values():
        for node in ast.walk(tree):
            # os.environ[X]
            if isinstance(node, ast.Subscript) and _is_environ_attribute(node.value):
                if (name := _env_name_from(node.slice, constants)) is not None:
                    names.add(name)
                continue

            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue

            # os.environ.get(X) / os.getenv(X) - and nothing else, so an
            # unrelated dict `.get("SOME_URL")` is not mistaken for an env read.
            is_environ_get = func.attr == "get" and _is_environ_attribute(func.value)
            is_getenv = func.attr == "getenv"
            if not (is_environ_get or is_getenv):
                continue
            if (name := _env_name_from(node.args[0], constants)) is not None:
                names.add(name)

    return names
