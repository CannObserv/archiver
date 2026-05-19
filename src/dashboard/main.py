"""Dashboard registration — call register_dashboard(app) once at startup."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from src.dashboard.deps import DashboardAuthRequired
from src.dashboard.routes.index import router as index_router
from src.dashboard.routes.settings import router as settings_router


async def _dashboard_auth_redirect(
    request: Request, exc: DashboardAuthRequired
) -> RedirectResponse:
    return RedirectResponse(url=exc.redirect_to, status_code=307)


def register_dashboard(app: FastAPI) -> None:
    """Mount static files, register exception handler, include dashboard routers."""
    static_dir = Path(__file__).parent / "static"
    app.mount(
        "/dashboard/static",
        StaticFiles(directory=str(static_dir)),
        name="dashboard-static",
    )
    app.add_exception_handler(DashboardAuthRequired, _dashboard_auth_redirect)
    app.include_router(index_router)
    app.include_router(settings_router)
