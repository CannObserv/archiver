"""Every unsafe dashboard route carries the same-origin check (#404).

The check is mounted once, in ``register_dashboard``'s router loop, so it covers
the routes by construction rather than by a list. This is the tripwire for the
ways around that loop: a router included elsewhere, a route added straight to
the app, or a router mounted without the dependency. Walks every unsafe route
outside ``/api/`` - wider than ``/dashboard`` on purpose, so a dashboard router
mounted under the wrong prefix cannot slip out of scope with its guard.
"""

from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from src.api.main import app
from src.dashboard.deps import require_same_origin

_UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _calls(dependant: Dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def _unsafe_browser_routes(target: FastAPI) -> list[APIRoute]:
    return [
        r
        for r in target.routes
        if isinstance(r, APIRoute) and r.methods & _UNSAFE and not r.path.startswith("/api/")
    ]


def unguarded(target: FastAPI) -> list[str]:
    """``METHODS path`` of each unsafe non-API route the check does not reach."""
    return sorted(
        f"{','.join(sorted(r.methods & _UNSAFE))} {r.path}"
        for r in _unsafe_browser_routes(target)
        if require_same_origin not in set(_calls(r.dependant))
    )


def test_every_unsafe_dashboard_route_is_same_origin_checked():
    routes = _unsafe_browser_routes(app)
    # Non-vacuity: 46 at #404's brief (2026-11-14). A walk that finds none is
    # broken, not passing.
    assert len(routes) >= 46, f"only {len(routes)} unsafe routes found - is the walk broken?"

    missing = unguarded(app)
    assert not missing, (
        f"{len(missing)} unsafe route(s) skip the same-origin check (#404). Include the "
        "router through register_dashboard's loop, which mounts require_same_origin. "
        "Unguarded:\n  " + "\n  ".join(missing)
    )


def test_the_walk_catches_a_seeded_unguarded_route():
    """Proof the tripwire fires: one guarded router, one not, one deep in a dependency."""
    seeded = FastAPI()

    guarded = APIRouter(prefix="/dashboard/ok")

    @guarded.post("/write")
    async def _guarded_write() -> None: ...

    bare = APIRouter(prefix="/dashboard/bare")

    @bare.post("/write")
    async def _bare_write() -> None: ...

    @bare.get("/read")
    async def _bare_read() -> None: ...

    async def _wraps_the_guard(_=Depends(require_same_origin)) -> None: ...

    nested = APIRouter(prefix="/dashboard/nested")

    @nested.delete("/write")
    async def _nested_write(_=Depends(_wraps_the_guard)) -> None: ...

    @seeded.put("/elsewhere")
    async def _off_prefix_write() -> None: ...

    @seeded.post("/api/v1/thing")
    async def _api_write() -> None: ...

    seeded.include_router(guarded, dependencies=[Depends(require_same_origin)])
    seeded.include_router(bare)
    seeded.include_router(nested)

    assert unguarded(seeded) == ["POST /dashboard/bare/write", "PUT /elsewhere"]
