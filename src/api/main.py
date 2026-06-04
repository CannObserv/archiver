"""Archiver service — FastAPI application entry point."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as _package_version

from fastapi import APIRouter, Depends, FastAPI
from redis.asyncio import Redis as RedisAsync
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.api.deps import require_api_key
from src.api.errors import EnvelopeResponse, register_error_handlers
from src.api.routes.domains import router as domains_router
from src.api.routes.health import router as health_router
from src.api.routes.info_items import router as info_items_router
from src.api.routes.info_sources import router as info_sources_router
from src.api.routes.rep_specs import router as rep_specs_router
from src.api.routes.source_revisions import router as source_revisions_router
from src.api.routes.tools import router as tools_router
from src.core.changes import publisher as outbox_publisher
from src.core.database import get_engine
from src.core.fetchers.http import HttpFetcher
from src.core.logging import configure_logging, get_logger
from src.dashboard.main import register_dashboard

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Set up shared resources for the process lifetime.

    - Builds a single shared ``HttpFetcher`` (shared ``httpx.AsyncClient``
      connection pool) for tool routes.
    - Optionally starts the outbox publisher background task when
      ``ARCHIVER_REDIS_URL`` is set in the environment.  When the variable is
      absent the publisher is skipped silently so the service starts without a
      Redis dependency in dev/test environments.
    """
    app.state.http_fetcher = HttpFetcher()

    # --- Optional outbox publisher ---
    redis_url = os.environ.get("ARCHIVER_REDIS_URL")
    redis_client: RedisAsync | None = None
    stop_event: asyncio.Event | None = None
    pub_task: asyncio.Task | None = None

    if redis_url:
        try:
            redis_client = RedisAsync.from_url(redis_url)
            session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
            stop_event = asyncio.Event()
            pub_task = asyncio.create_task(
                outbox_publisher.run(
                    session_factory=session_factory,
                    redis=redis_client,
                    stop_event=stop_event,
                )
            )
            app.state.publisher_task = pub_task
            app.state.publisher_stop_event = stop_event
            logger.info("Outbox publisher started", extra={"redis_url": redis_url})
        except Exception:
            logger.exception("Failed to initialise outbox publisher; skipping")
            redis_client = None
    else:
        logger.info("ARCHIVER_REDIS_URL not set — outbox publisher disabled")

    try:
        yield
    finally:
        # Stop publisher first
        if stop_event is not None:
            stop_event.set()
        if pub_task is not None:
            pub_task.cancel()
            try:
                await pub_task
            except (asyncio.CancelledError, Exception):
                pass
        if redis_client is not None:
            await redis_client.aclose()
        # Then close HTTP fetcher
        await app.state.http_fetcher.aclose()


app = FastAPI(title="archiver", version=_package_version("archiver"), lifespan=lifespan)
register_error_handlers(app)

v1_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_api_key)],
    responses={
        400: {"model": EnvelopeResponse, "description": "Bad request (envelope)."},
        401: {"model": EnvelopeResponse, "description": "Auth required (envelope)."},
        403: {"model": EnvelopeResponse, "description": "Forbidden (envelope)."},
        404: {"model": EnvelopeResponse, "description": "Not found (envelope)."},
        409: {"model": EnvelopeResponse, "description": "Conflict (envelope)."},
        422: {"model": EnvelopeResponse, "description": "Validation failed (envelope)."},
        500: {"model": EnvelopeResponse, "description": "Internal error (envelope)."},
    },
)
v1_router.include_router(domains_router)
v1_router.include_router(info_items_router)
v1_router.include_router(info_sources_router)
v1_router.include_router(rep_specs_router)
v1_router.include_router(source_revisions_router)
v1_router.include_router(tools_router)

app.include_router(v1_router)
app.include_router(health_router)
register_dashboard(app)
