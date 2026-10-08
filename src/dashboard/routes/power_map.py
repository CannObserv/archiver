"""Dashboard — Power Map type-ahead for the InfoItem Organization row (archiver#306).

``GET /dashboard/power-map/orgs?q=&item_id=`` answers the row's combobox with
its options. Under ``MIN_QUERY`` characters it lists the orgs already linked on
the item's domains (``local_org_options``) and never calls Power Map; from
there it searches Power Map, archived orgs excluded. Power Map dormant or
unavailable is a ``role="status"`` line in a 200: the type-ahead degrades, and
nothing else on the page notices.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session, get_power_map
from src.core.models import InfoItem
from src.core.power_map import PowerMapClient, PowerMapUnavailableError
from src.dashboard.deps import get_dashboard_user
from src.dashboard.org_row import OrgOption, local_org_options, option_from_hit

router = APIRouter(prefix="/dashboard/power-map")

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

MIN_QUERY = 2
SEARCH_LIMIT = 10

NOT_CONFIGURED = "Power Map not configured: search is unavailable."
UNAVAILABLE = "Power Map unavailable: try again shortly."


async def _local_options(session: AsyncSession, item_id: str) -> list[OrgOption]:
    """The item's local suggestions; an item id that names nothing has none."""
    try:
        uid = ULID.from_str(item_id.strip())
    except ValueError:
        return []
    item = await session.get(InfoItem, uid)
    return await local_org_options(session, item) if item is not None else []


@router.get("/orgs", response_class=HTMLResponse)
async def search_orgs(
    request: Request,
    q: str = Query(default=""),
    item_id: str = Query(default=""),
    user=Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    power_map: PowerMapClient | None = Depends(get_power_map),
) -> HTMLResponse:
    """HTMX partial: the combobox's options, or a status line saying why there are none."""
    query = q.strip()
    options: list[OrgOption] = []
    status: str | None = None
    if len(query) < MIN_QUERY:
        options = await _local_options(session, item_id)
    elif power_map is None:
        status = NOT_CONFIGURED
    else:
        try:
            options = [option_from_hit(h) for h in await power_map.search_orgs(query, SEARCH_LIMIT)]
        except PowerMapUnavailableError:
            status = UNAVAILABLE
        else:
            if not options:
                status = f"No Power Map organization matches “{query}”."
    response = _templates.TemplateResponse(
        request,
        "power_map/_org_options.html",
        {"user": user, "options": options, "status": status},
    )
    response.headers["Cache-Control"] = "no-store"
    return response
