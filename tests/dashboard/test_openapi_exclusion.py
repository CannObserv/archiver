"""Dashboard routes must stay out of the OpenAPI document (#87).

`clients/python/scripts/regen.sh` pipes `app.openapi()` straight into
`openapi-python-client`, so any dashboard path that reaches the schema is one
routine regen away from shipping as public `archiver_client` API surface —
HTML-returning, proxy-header-authed, and useless-to-broken as a client method.
The failure mode is silent until someone regenerates, hence a tripwire.
"""

from fastapi.routing import APIRoute

from src.api.main import app


def test_no_dashboard_paths_in_openapi():
    # Non-vacuity: the guard proves nothing if the dashboard stopped
    # registering routes under /dashboard altogether.
    mounted = [
        r.path for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/dashboard")
    ]
    assert mounted, "no /dashboard APIRoutes registered — the guard is vacuous, not passing"

    leaked = sorted(p for p in app.openapi()["paths"] if p.startswith("/dashboard"))
    assert not leaked, (
        f"{len(leaked)} dashboard paths leak into the OpenAPI schema; the next "
        "clients/python regen would generate them into the public SDK (#87). "
        "register_dashboard must include every dashboard router with "
        "include_in_schema=False. Leaked:\n  " + "\n  ".join(leaked)
    )
