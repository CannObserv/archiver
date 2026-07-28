"""Archiver service — FastAPI application entry point."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as _package_version

from co_core_aio.bus import AsyncBusPublisher
from co_core_aio.fetch import AsyncFetchDriver
from fastapi import APIRouter, Depends, FastAPI
from redis.asyncio import Redis as RedisAsync
from sqlalchemy.ext.asyncio import async_sessionmaker
from watcher_client import WatcherClient

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
from src.core.db_safety import (
    ALLOW_PRODUCTION_DB_ENV,
    ProductionDatabaseRefused,
    assert_production_db_allowed,
)
from src.core.logging import configure_logging, get_logger
from src.dashboard.main import register_dashboard

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Set up shared resources for the process lifetime.

    - Refuses to serve a production database unless the caller opted in via
      ``ARCHIVER_ALLOW_PRODUCTION_DB=1`` (only ``deploy/archiver.service``
      does).  Launch-path-independent backstop for the 2026-07-18 incident —
      see ``src.core.db_safety``.
    - Builds a single shared ``AsyncFetchDriver`` (shared ``httpx.AsyncClient``
      connection pool) for tool routes.
    - Optionally starts the outbox publisher background task when
      ``ARCHIVER_REDIS_URL`` is set in the environment.  When the variable is
      absent the publisher is skipped silently so the service starts without a
      Redis dependency in dev/test environments.
    """
    # Before any resource is built or any request is served.
    try:
        assert_production_db_allowed(
            os.environ.get("ARCHIVER_DATABASE_URL") or os.environ.get("DATABASE_URL") or "",
            allow_flag=os.environ.get(ALLOW_PRODUCTION_DB_ENV),
        )
    except ProductionDatabaseRefused as e:
        # Log before re-raising: under systemd the bare exception surfaces in
        # journalctl as a lifespan traceback, burying the actionable text.
        logger.critical("Refusing to start: %s", e)
        raise

    app.state.fetch_driver = AsyncFetchDriver()

    # --- Optional WatcherClient ---
    watcher_base_url = os.environ.get("WATCHER_BASE_URL", "").strip()
    watcher_api_key = os.environ.get("WATCHER_API_KEY", "").strip()
    watcher_client: WatcherClient | None = None
    if watcher_base_url and watcher_api_key:
        watcher_client = WatcherClient(base_url=watcher_base_url, api_key=watcher_api_key)
        app.state.watcher_client = watcher_client
        logger.info("WatcherClient initialised", extra={"base_url": watcher_base_url})
    else:
        app.state.watcher_client = None
        logger.info("WATCHER_BASE_URL/WATCHER_API_KEY not set — Watcher integration disabled")

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
            # The drain loop publishes via the shared co-core bus driver; it
            # borrows the long-lived redis client (injection-only, never closes
            # it — the lifespan owns aclose below).
            pub_task = asyncio.create_task(
                outbox_publisher.run(
                    session_factory=session_factory,
                    publisher=AsyncBusPublisher(redis_client),
                    stop_event=stop_event,
                )
            )
            app.state.redis_client = redis_client
            app.state.publisher_task = pub_task
            app.state.publisher_stop_event = stop_event
            logger.info("Outbox publisher started", extra={"redis_url": redis_url})
        except Exception:
            logger.exception("Failed to initialise outbox publisher; skipping")
            redis_client = None
            app.state.redis_client = None
    else:
        app.state.redis_client = None
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
        # Then close the fetch driver and WatcherClient
        await app.state.fetch_driver.aclose()
        if watcher_client is not None:
            await watcher_client.aclose()


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
