"""Dashboard registration — call register_dashboard(app) once at startup."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from src.dashboard.deps import DashboardAuthRequired
from src.dashboard.exceptions import DashboardNotFound
from src.dashboard.routes.domains import router as domains_router
from src.dashboard.routes.index import router as index_router
from src.dashboard.routes.info_items import router as info_items_router
from src.dashboard.routes.info_sources import router as info_sources_router
from src.dashboard.routes.register import router as register_router
from src.dashboard.routes.rep_specs import router as rep_specs_router
from src.dashboard.routes.settings import router as settings_router
from src.dashboard.routes.source_revisions import router as source_revisions_router


async def _dashboard_auth_redirect(
    request: Request, exc: DashboardAuthRequired
) -> RedirectResponse:
    return RedirectResponse(url=exc.redirect_to, status_code=307)


_error_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


async def _dashboard_not_found(request: Request, exc: DashboardNotFound) -> HTMLResponse:
    return _error_templates.TemplateResponse(
        request, "_404.html", {"message": exc.message}, status_code=404
    )


def register_dashboard(app: FastAPI) -> None:
    """Mount static files, register exception handler, include dashboard routers."""
    static_dir = Path(__file__).parent / "static"
    app.mount(
        "/dashboard/static",
        StaticFiles(directory=str(static_dir)),
        name="dashboard-static",
    )
    app.add_exception_handler(DashboardAuthRequired, _dashboard_auth_redirect)
    app.add_exception_handler(DashboardNotFound, _dashboard_not_found)
    # include_in_schema=False on every router: dashboard routes are HTML +
    # proxy-header auth, and clients/python/scripts/regen.sh generates the SDK
    # from app.openapi() — any leaked path becomes public client surface (#87).
    for router in (
        domains_router,
        register_router,
        index_router,
        info_items_router,
        info_sources_router,
        rep_specs_router,
        source_revisions_router,
        settings_router,
    ):
        app.include_router(router, include_in_schema=False)
