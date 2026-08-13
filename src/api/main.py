"""Archiver service — FastAPI application entry point."""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
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
from src.core.changes import consumer as revisions_consumer
from src.core.changes import publisher as outbox_publisher
from src.core.changes import registry_snapshot, watch_status_consumer
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


def _bus_task_exit_logger(label: str, stop_event: asyncio.Event) -> Callable[[asyncio.Task], None]:
    """Build a done-callback that reports a bus task ending on its own.

    Without one, a task that dies on its first tick is silent: nothing awaits it
    until the lifespan's shutdown handler, which swallows the exception, so the
    service runs to completion looking healthy while nothing is publishing or
    consuming (CR round 1, finding 1).

    ``stop_event`` is what separates "we asked it to stop" from "it stopped".
    Cancellation covers the usual shutdown, but a loop that observes the stop
    event and returns cleanly is *also* an expected exit — and deciding that from
    the task alone would depend on there being no ``await`` between
    ``stop_event.set()`` and ``task.cancel()`` below, which is far too subtle a
    thing for a future edit to preserve by accident (CR round 2, finding 18).
    """

    def _log(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Bus task exited with an error", extra={"task": label}, exc_info=exc)
        elif stop_event.is_set():
            logger.info("Bus task stopped", extra={"task": label})
        else:
            logger.warning("Bus task exited unexpectedly", extra={"task": label})

    return _log


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
    - Optionally starts the ``content.revisions`` consumer, which additionally
      requires ``ARCHIVER_BUS_CONSUMER=1``.  Producing from a stray process is
      noisy; consuming *removes* messages from a production consumer group, so
      that one gets an explicit opt-in only ``deploy/archiver.service`` sets
      (archiver#139).
    - Optionally starts the ``info.watch-status`` tail (archiver#151), gated on
      the Redis URL alone — deliberately **not** on ``ARCHIVER_BUS_CONSUMER``.
      That gate exists because a group consumer removes messages from
      production's PEL; a groupless tail removes nothing, so a stray tail is
      harmless.
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
    consumer_task: asyncio.Task | None = None
    snapshot_task: asyncio.Task | None = None
    watch_status_task: asyncio.Task | None = None

    if redis_url:
        try:
            redis_client = RedisAsync.from_url(redis_url)
            session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
            stop_event = asyncio.Event()
            # Operator-side stream cap (archiver#109): with no consumer yet,
            # info.changes accumulates, so the drain loop periodically XTRIMs it.
            # Resolved defensively — a malformed knob degrades trimming, never
            # disables the publisher (it would be swallowed by the except below).
            stream_maxlen = outbox_publisher.resolve_stream_maxlen(
                os.environ.get("ARCHIVER_REDIS_STREAM_MAXLEN")
            )
            # The drain loop publishes via the shared co-core bus driver; it
            # borrows the long-lived redis client (injection-only, never closes
            # it — the lifespan owns aclose below), and reuses it for the XTRIM.
            # info.registry retention is a consumer contract riding each publish
            # (replay-from-0-0 stream), so the topic is excluded from the global
            # XTRIM loop and its deltas carry their own maxlen (archiver#141).
            registry_maxlen = registry_snapshot.resolve_registry_maxlen(
                os.environ.get("ARCHIVER_REGISTRY_STREAM_MAXLEN")
            )
            registry_topic = registry_snapshot.INFO_REGISTRY_TOPIC
            pub_task = asyncio.create_task(
                outbox_publisher.run(
                    session_factory=session_factory,
                    publisher=AsyncBusPublisher(redis_client),
                    stop_event=stop_event,
                    redis_client=redis_client,
                    stream_maxlen=stream_maxlen,
                    no_trim_topics=frozenset({registry_topic}),
                    topic_maxlen={registry_topic: registry_maxlen},
                )
            )
            pub_task.add_done_callback(_bus_task_exit_logger("outbox_publisher", stop_event))
            app.state.redis_client = redis_client
            app.state.publisher_task = pub_task
            app.state.publisher_stop_event = stop_event
            logger.info("Outbox publisher started", extra={"redis_url": redis_url})

            # --- Registry snapshot timer (archiver#141) ---
            # Shares the publisher's client and stop event; its own task so a
            # snapshot failure never touches the outbox drain. Publishes a full
            # set at startup, then hourly (configurable). No retry — the next
            # period is the repair, per the streams table's durability column.
            snapshot_trigger = asyncio.Event()
            snapshot_task = asyncio.create_task(
                registry_snapshot.run(
                    session_factory=session_factory,
                    publisher=AsyncBusPublisher(redis_client),
                    interval=registry_snapshot.resolve_snapshot_interval(
                        os.environ.get("ARCHIVER_REGISTRY_SNAPSHOT_INTERVAL")
                    ),
                    maxlen=registry_maxlen,
                    stop_event=stop_event,
                    trigger=snapshot_trigger,
                )
            )
            snapshot_task.add_done_callback(_bus_task_exit_logger("registry_snapshot", stop_event))
            app.state.registry_snapshot_task = snapshot_task
            app.state.registry_snapshot_trigger = snapshot_trigger
        except Exception:
            logger.exception("Failed to initialise outbox publisher; skipping")
            redis_client = None
            app.state.redis_client = None
            app.state.publisher_task = None
            app.state.publisher_stop_event = None
            app.state.registry_snapshot_task = None
            app.state.registry_snapshot_trigger = None

        # --- Optional content.revisions consumer (archiver#139) ---
        # Gated separately from the publisher and started in its own try, so a
        # consumer that cannot start leaves the publisher running. It shares the
        # publisher's Redis client and stop event: one broker connection pool,
        # one shutdown signal.
        gate = os.environ.get("ARCHIVER_BUS_CONSUMER")
        if redis_client is not None and revisions_consumer.consumer_enabled(gate):
            try:
                consumer_task = asyncio.create_task(
                    revisions_consumer.run(
                        session_factory=async_sessionmaker(
                            bind=get_engine(), expire_on_commit=False
                        ),
                        consumer=revisions_consumer.build_consumer(redis_client),
                        stop_event=stop_event,
                    )
                )
                consumer_task.add_done_callback(
                    _bus_task_exit_logger("revisions_consumer", stop_event)
                )
                app.state.revisions_consumer_task = consumer_task
                logger.info(
                    "content.revisions consumer task scheduled",
                    extra={"group": revisions_consumer.CONSUMER_GROUP},
                )
            except Exception:
                logger.exception("Failed to initialise content.revisions consumer; skipping")
                app.state.revisions_consumer_task = None
        else:
            app.state.revisions_consumer_task = None
            logger.info(
                "content.revisions consumer disabled",
                extra={"reason": "gate" if redis_client is not None else "no_redis_client"},
            )

        # --- info.watch-status tail (archiver#151) ---
        # Groupless: no PEL, no gate beyond the Redis URL. Its own try so a
        # tail that cannot start leaves the publisher and group consumer
        # running; shares their client and stop event.
        if redis_client is not None:
            try:
                ws_session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
                start_id = await watch_status_consumer.resolve_start_id(ws_session_factory)
                watch_status_task = asyncio.create_task(
                    watch_status_consumer.run(
                        session_factory=ws_session_factory,
                        reader=watch_status_consumer.build_reader(redis_client, start_id=start_id),
                        stop_event=stop_event,
                    )
                )
                watch_status_task.add_done_callback(
                    _bus_task_exit_logger("watch_status_tail", stop_event)
                )
                app.state.watch_status_task = watch_status_task
                logger.info("info.watch-status tail task scheduled", extra={"start_id": start_id})
            except Exception:
                logger.exception("Failed to initialise info.watch-status tail; skipping")
                app.state.watch_status_task = None
        else:
            app.state.watch_status_task = None
    else:
        # Every dormant path nulls *both* handles. Leaving app.state.publisher_task
        # set from a previous lifespan made it describe a publisher that is not
        # running, and made two lifespan assertions satisfiable by a stale value
        # (CR round 2, finding 15).
        app.state.redis_client = None
        app.state.publisher_task = None
        app.state.publisher_stop_event = None
        app.state.revisions_consumer_task = None
        app.state.registry_snapshot_task = None
        app.state.registry_snapshot_trigger = None
        app.state.watch_status_task = None
        logger.info("ARCHIVER_REDIS_URL not set — outbox publisher and bus consumers disabled")

    try:
        yield
    finally:
        # Stop the bus tasks first — both watch the same stop event.
        if stop_event is not None:
            stop_event.set()
        for task in (pub_task, consumer_task, snapshot_task, watch_status_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
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
