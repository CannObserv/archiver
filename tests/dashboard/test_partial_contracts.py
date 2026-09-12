"""Behaviour-bearing partials take their whole context from one builder (archiver#219).

**Why the lenient default is the hazard.** Jinja's default ``Undefined`` does not
fail on a missing key. It is falsy, it renders as the empty string, and an
``is defined`` test or a ``default`` filter turns it into an ordinary branch. So a
render site that forgets a key produces no error page and no 500 - it produces a
page that renders, looks right, and quietly omits behaviour.

That is how archiver#212 shipped its own defect (PR #218, CR 12).
``_rep_spec_assignments.html`` read ``{% if poll is defined and poll.active %}``;
three of its four render sites supplied ``poll`` and the item detail page did
not, so a reload while a replication was in flight rendered a section that never
polled. Every test passed, because every test took a path that *did* pass the
key. The guard was removed (CR 13): a defensive read of a required key converts a
missing contract into exactly that silent section. **Do not add one back - supply
the key from the builder.** ``test_no_required_key_is_read_leniently`` fails if
you do.

**Why statically.** The site that shipped the defect was one no test rendered
without the key, so a guard that needs each site exercised has the same hole.
This module finds the render sites itself - every ``TemplateResponse`` naming the
partial or any template that includes or extends it, transitively - and requires
each to spread the partial's builder. The required keys are read from the
template rather than listed here, so the contract cannot go stale the way
``required_fields`` did before #168 checked it against the template.

**Why not ``StrictUndefined``.** It is the real fix, and a blanket switch fails 104
dashboard tests (measured in archiver#219) on templates that rely on lenient
undefined for optional context - a migration of its own, across nine
``Jinja2Templates`` instances. Until then, a partial whose missing key changes
behaviour rather than omitting text is registered in ``_CONTRACTS``.
"""

from __future__ import annotations

import ast
import re
import textwrap
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest
from jinja2 import DictLoader, Environment, FileSystemLoader, meta, nodes
from ulid import ULID

from src.core.models import RepSpec
from src.dashboard.routes import info_items as info_items_routes
from src.dashboard.routes import rep_specs as rep_specs_routes

_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD = _ROOT / "src" / "dashboard"
_ENV = Environment(loader=FileSystemLoader(str(_DASHBOARD / "templates")))

_SWAPPED = (
    "the caller's to decide, and absent from a full page by design: the focus "
    "script belongs to a swap the operator caused (docs/SCREENS.md § HTMX mutations)"
)


@dataclass(frozen=True)
class _Contract:
    """What a behaviour-bearing partial reads, and the one place that supplies it."""

    builder: Callable[..., Awaitable[dict]]
    # Arguments putting the builder on an empty screen: the keys it returns do
    # not depend on the rows it finds.
    empty_args: Callable[[], tuple]
    # Keys the partial reads that a render site may leave out, each with its reason.
    optional: Mapping[str, str]


_CONTRACTS: dict[str, _Contract] = {
    "info_items/_rep_spec_assignments.html": _Contract(
        builder=info_items_routes._rep_spec_assignments_context,
        empty_args=lambda: (ULID(),),
        optional={"swapped": _SWAPPED},
    ),
    "rep_specs/_assignments.html": _Contract(
        builder=rep_specs_routes._assignments_context,
        empty_args=lambda: (
            RepSpec(
                rep_spec_id=ULID(),
                provider="gcs",
                name="contract probe",
                schema_version=1,
                document={},
            ),
        ),
        optional={"swapped": _SWAPPED},
    ),
}


# ---------------------------------------------------------------------------
# Reading the templates
# ---------------------------------------------------------------------------


def _parse(env: Environment, name: str) -> nodes.Template:
    source, _, _ = env.loader.get_source(env, name)
    return env.parse(source)


def _literal_names(expr: nodes.Expr, where: str) -> list[str]:
    """The template names an include or extends points at.

    A computed name cannot be followed, and skipping it would quietly narrow the
    check to the templates it can read - so it fails instead.
    """
    if isinstance(expr, nodes.Const) and isinstance(expr.value, str):
        return [expr.value]
    if isinstance(expr, nodes.List | nodes.Tuple) and all(
        isinstance(item, nodes.Const) for item in expr.items
    ):
        return [item.value for item in expr.items]
    raise AssertionError(f"{where}: a computed include/extends target cannot be followed")


def _renders_into(env: Environment, name: str) -> set[str]:
    """Templates ``name`` renders as part of itself: its includes and its parent.

    Imports are left out - a macro library gets no context unless it asks for
    one, so importing a partial's macros does not render the partial.
    """
    return {
        target
        for node in _parse(env, name).find_all((nodes.Include, nodes.Extends))
        for target in _literal_names(node.template, name)
    }


def _carriers(env: Environment, partial: str) -> set[str]:
    """``partial`` and every template that renders it, however indirectly."""
    edges = {name: _renders_into(env, name) for name in env.list_templates(extensions=["html"])}
    carriers = {partial}
    while grown := {name for name, targets in edges.items() if targets & carriers} - carriers:
        carriers |= grown
    return carriers


def _bound_names(tree: nodes.Template) -> set[str]:
    """Names a template binds for itself - loop variables and ``set`` targets."""
    names: set[str] = set()
    for node in tree.find_all((nodes.For, nodes.Assign, nodes.AssignBlock)):
        target = node.target
        names.update(
            n.name for n in (target, *target.find_all(nodes.Name)) if isinstance(n, nodes.Name)
        )
    return names


def _reads(env: Environment, name: str) -> set[str]:
    """Every context key ``name`` reads, its includes' reads included.

    An included template sees its includer's context, so what it reads is the
    includer's contract too - less what the includer binds for it (the hub's row
    template reads ``assignment``, which is the section's own loop variable).
    """
    tree = _parse(env, name)
    reads = set(meta.find_undeclared_variables(tree))
    bound = _bound_names(tree)
    for node in tree.find_all(nodes.Include):
        for child in _literal_names(node.template, name):
            reads |= _reads(env, child) - bound
    return reads


def _required(env: Environment, partial: str) -> set[str]:
    return _reads(env, partial) - set(_CONTRACTS[partial].optional)


def _header(env: Environment, name: str) -> str:
    """The template's leading comment - where a partial declares its contract."""
    source, _, _ = env.loader.get_source(env, name)
    match = re.match(r"\s*\{#(.*?)#\}", source, re.S)
    return match.group(1) if match else ""


def _root_name(expr: nodes.Node | None) -> str | None:
    """``poll`` for ``poll``, ``poll.active`` and ``poll["active"]`` alike."""
    while isinstance(expr, nodes.Getattr | nodes.Getitem):
        expr = expr.node
    return expr.name if isinstance(expr, nodes.Name) else None


def _lenient_reads(env: Environment, name: str, keys: set[str]) -> list[str]:
    """Each place ``name``, or a template it includes, reads one of ``keys`` leniently."""
    tree = _parse(env, name)
    found = [
        f"{name}: `{_root_name(node.node)} is {node.name}`"
        for node in tree.find_all(nodes.Test)
        if node.name in {"defined", "undefined"} and _root_name(node.node) in keys
    ] + [
        f"{name}: `{_root_name(node.node)} | {node.name}`"
        for node in tree.find_all(nodes.Filter)
        if node.name in {"default", "d"} and _root_name(node.node) in keys
    ]
    for node in tree.find_all(nodes.Include):
        for child in _literal_names(node.template, name):
            found += _lenient_reads(env, child, keys)
    return found


# ---------------------------------------------------------------------------
# Reading the routes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Site:
    """One ``TemplateResponse`` rendering a carrier, and the builders feeding it."""

    where: str
    template: str
    builders: frozenset[str]


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def _assigned_values(name: str, scopes: list[ast.AST]) -> list[ast.expr]:
    """What ``name`` is assigned in the nearest enclosing function that assigns it."""
    for scope in reversed(scopes):
        values = [
            node.value
            for node in ast.walk(scope)
            if isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr)
            and node.value is not None
            and any(
                isinstance(t, ast.Name) and t.id == name
                for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
            )
        ]
        if values:
            return values
    return []


def _builders_reaching(
    expr: ast.expr | None, scopes: list[ast.AST], seen: frozenset[str] = frozenset()
) -> frozenset[str]:
    """Functions whose returned dict provably ends up in ``expr``.

    Follows the three shapes the routes use: a call, a dict literal's ``**``
    spreads, and a local name - which counts only when *every* assignment to it
    carries the builder, since a name rebound on one branch would not.
    """
    if isinstance(expr, ast.Await):
        return _builders_reaching(expr.value, scopes, seen)
    if isinstance(expr, ast.Call):
        name = _called_name(expr)
        return frozenset({name}) if name else frozenset()
    if isinstance(expr, ast.Dict):
        return frozenset().union(
            *(
                _builders_reaching(value, scopes, seen)
                for key, value in zip(expr.keys, expr.values, strict=True)
                if key is None
            )
        )
    if isinstance(expr, ast.Name) and expr.id not in seen:
        values = _assigned_values(expr.id, scopes)
        if values:
            return frozenset.intersection(
                *(_builders_reaching(value, scopes, seen | {expr.id}) for value in values)
            )
    return frozenset()


class _SiteFinder(ast.NodeVisitor):
    """Every render of a carrier in one module, and any carrier name it cannot follow."""

    def __init__(self, path: str, carriers: set[str]) -> None:
        self.path = path
        self.carriers = carriers
        self.scopes: list[ast.AST] = []
        self.sites: list[_Site] = []
        self.unfollowable: list[str] = []
        self._consumed: set[int] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scopes.append(node)
        self.generic_visit(node)
        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if _called_name(node) == "TemplateResponse":
            self._record(node)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        # A carrier's name anywhere but a TemplateResponse's name argument - held
        # in a constant, or handed to get_template() - is a render the scan
        # cannot see, so it fails rather than passing on what it did see.
        if node.value in self.carriers and id(node) not in self._consumed:
            self.unfollowable.append(f"{self.path}:{node.lineno}")

    def _record(self, call: ast.Call) -> None:
        for i, arg in enumerate(call.args):
            if isinstance(arg, ast.Constant) and arg.value in self.carriers:
                context = call.args[i + 1] if i + 1 < len(call.args) else _keyword(call, "context")
                break
        else:
            arg = _keyword(call, "name")
            if not (isinstance(arg, ast.Constant) and arg.value in self.carriers):
                return
            context = _keyword(call, "context")
        self._consumed.add(id(arg))
        where = ".".join(scope.name for scope in self.scopes) or "<module>"
        self.sites.append(
            _Site(
                where=f"{self.path}:{call.lineno} in {where}",
                template=arg.value,
                builders=_builders_reaching(context, self.scopes),
            )
        )


def _scan(source: str, path: str, carriers: set[str]) -> _SiteFinder:
    finder = _SiteFinder(path, carriers)
    finder.visit(ast.parse(source))
    return finder


def _scan_dashboard(carriers: set[str]) -> tuple[list[_Site], list[str]]:
    sites: list[_Site] = []
    unfollowable: list[str] = []
    for file in sorted(_DASHBOARD.rglob("*.py")):
        finder = _scan(file.read_text(), str(file.relative_to(_ROOT)), carriers)
        sites += finder.sites
        unfollowable += finder.unfollowable
    return sites, unfollowable


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("partial", list(_CONTRACTS))
def test_every_render_site_spreads_the_partials_builder(partial: str) -> None:
    """What a fifth render site is held to, without anyone writing a test for it."""
    builder = _CONTRACTS[partial].builder.__name__
    sites, unfollowable = _scan_dashboard(_carriers(_ENV, partial))

    # Non-vacuity: a scan that finds nothing passes forever. Today the partial is
    # rendered directly (the swaps and the poll) and inside its detail page.
    assert any(site.template == partial for site in sites), f"no direct render of {partial}"
    assert any(site.template != partial for site in sites), f"no page carrying {partial}"

    assert not unfollowable, (
        f"a template carrying {partial} is named where this scan cannot follow it - "
        "render it by literal name in a TemplateResponse call:\n  " + "\n  ".join(unfollowable)
    )
    offenders = [f"{s.where} ({s.template})" for s in sites if builder not in s.builders]
    assert not offenders, (
        f"render sites of {partial} that do not spread {builder}(). A key the partial "
        "reads and they omit renders as a quietly wrong section, not an error - see "
        "this module's docstring:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", list(_CONTRACTS))
async def test_the_builder_supplies_every_key_the_partial_reads(partial: str, session) -> None:
    contract = _CONTRACTS[partial]
    required = _required(_ENV, partial)
    # Non-vacuity: the derivation still sees the keys that shipped the defect.
    assert {"poll", "poll_interval_seconds"} <= required

    context = await contract.builder(*contract.empty_args(), session)

    missing = sorted(required - context.keys())
    assert not missing, f"{contract.builder.__name__}() omits {missing}, which {partial} reads"


@pytest.mark.parametrize("partial", list(_CONTRACTS))
def test_every_optional_key_is_one_the_partial_still_reads(partial: str) -> None:
    """An exemption for a key nothing reads is a stale list entry waiting to hide one."""
    stale = sorted(set(_CONTRACTS[partial].optional) - _reads(_ENV, partial))
    assert not stale, f"{partial} no longer reads {stale}; drop them from _CONTRACTS"


@pytest.mark.parametrize("partial", list(_CONTRACTS))
def test_the_partial_header_declares_every_required_key(partial: str) -> None:
    """The header is the contract a reader of the template sees. It stopped short
    of ``poll`` once, and that is the document CR 12 would have been checked
    against (CR 14)."""
    header = _header(_ENV, partial)
    undeclared = sorted(key for key in _required(_ENV, partial) if f"`{key}`" not in header)
    assert not undeclared, f"{partial}'s header comment does not name {undeclared}"


@pytest.mark.parametrize("partial", list(_CONTRACTS))
def test_no_required_key_is_read_leniently(partial: str) -> None:
    """``is defined`` on a required key is the CR 13 defect, not a defence."""
    offenders = _lenient_reads(_ENV, partial, _required(_ENV, partial))
    assert not offenders, (
        "a required key read through `is defined` or `default` turns a missing key into "
        "a section that renders and silently does nothing (archiver#212 CR 12/13). "
        "Supply it from the builder instead:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# The scan's own tests. Every check above passes on today's tree, which is also
# what a broken scan would do; these hand it the failures it exists to catch.
# ---------------------------------------------------------------------------

_PARTIAL = "rep_specs/_assignments.html"


def test_a_render_site_that_builds_its_own_context_is_caught() -> None:
    """archiver#219's acceptance: a new render site without ``poll`` fails."""
    finder = _scan(
        textwrap.dedent("""
            async def added_later(request, spec, session):
                rows, items, latest = await _load_active_assignments(spec, session)
                return _templates.TemplateResponse(
                    request,
                    "rep_specs/_assignments.html",
                    {"spec": spec, "assignments": rows, "latest_commands": latest},
                )
        """),
        "canary.py",
        {_PARTIAL},
    )

    assert [(site.template, site.builders) for site in finder.sites] == [(_PARTIAL, frozenset())]


def test_a_builder_rebound_on_one_branch_does_not_count() -> None:
    finder = _scan(
        textwrap.dedent("""
            async def added_later(request, spec, session, htmx):
                ctx = await _assignments_context(spec, session)
                if htmx:
                    ctx = {"spec": spec}
                return _templates.TemplateResponse(request, "rep_specs/_assignments.html", ctx)
        """),
        "canary.py",
        {_PARTIAL},
    )

    assert [site.builders for site in finder.sites] == [frozenset()]


def test_a_template_name_the_scan_cannot_follow_fails_it() -> None:
    finder = _scan(
        textwrap.dedent("""
            _SECTION = "rep_specs/_assignments.html"

            async def added_later(request):
                return _templates.TemplateResponse(request, _SECTION, {})
        """),
        "canary.py",
        {_PARTIAL},
    )

    assert finder.unfollowable == ["canary.py:2"]


def test_a_page_that_includes_or_extends_a_carrier_is_one_itself() -> None:
    env = Environment(
        loader=DictLoader(
            {
                "_section.html": "{{ poll.active }}",
                "page.html": "{% block body %}{% include '_section.html' %}{% endblock %}",
                "child.html": "{% extends 'page.html' %}",
                "imports_only.html": "{% from '_section.html' import nothing %}",
            }
        )
    )

    assert _carriers(env, "_section.html") == {"_section.html", "page.html", "child.html"}


def test_an_included_template_reads_on_its_includers_behalf() -> None:
    env = Environment(
        loader=DictLoader(
            {
                "_section.html": "{% for row in rows %}{% include '_row.html' %}{% endfor %}",
                "_row.html": "{{ row.id }} {{ item_id }}",
            }
        )
    )

    assert _reads(env, "_section.html") == {"rows", "item_id"}


def test_a_lenient_read_is_found_through_an_include() -> None:
    env = Environment(
        loader=DictLoader(
            {
                "_section.html": (
                    "{% if poll is defined and poll.active %}{% endif %}{% include '_row.html' %}"
                ),
                "_row.html": "{{ poll_interval_seconds | default(2) }}{{ swapped | default(0) }}",
            }
        )
    )

    assert _lenient_reads(env, "_section.html", {"poll", "poll_interval_seconds"}) == [
        "_section.html: `poll is defined`",
        "_row.html: `poll_interval_seconds | default`",
    ]
