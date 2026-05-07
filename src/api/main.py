"""Archiver service — FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI

from src.api.deps import require_api_key
from src.api.routes.health import router as health_router
from src.api.routes.info_items import router as info_items_router
from src.api.routes.info_specs import router as info_specs_router
from src.api.routes.tools import router as tools_router
from src.core.fetchers.http import HttpFetcher
from src.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build a single shared HttpFetcher for the process; close it on shutdown.

    Tool routes that need to fetch a target URL share one ``httpx.AsyncClient``
    via this fetcher — per-request construction would leak connection pools
    since each ``HttpFetcher`` lazily builds its own client and never closes it.
    """
    app.state.http_fetcher = HttpFetcher()
    try:
        yield
    finally:
        await app.state.http_fetcher.aclose()


app = FastAPI(title="archiver", version="0.1.0", lifespan=lifespan)

v1_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
v1_router.include_router(info_items_router)
v1_router.include_router(info_specs_router)
v1_router.include_router(tools_router)

app.include_router(v1_router)
app.include_router(health_router)
