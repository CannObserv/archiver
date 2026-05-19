"""Dashboard home — placeholder for Epic 7; serves shell for Foundation."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.core.models import AppUser
from src.dashboard.deps import get_dashboard_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard_index(
    request: Request,
    user: AppUser = Depends(get_dashboard_user),
) -> HTMLResponse:
    """Dashboard home page."""
    return _templates.TemplateResponse(request, "index.html", {"user": user})
