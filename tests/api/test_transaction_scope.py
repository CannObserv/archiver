"""No ``/api/v1`` request holds a transaction across an outbound wait (#521).

``require_api_key`` resolves before every ``/api/v1`` route, through the
router's dependencies, and writes ``last_used_at``. Flushed and never
committed, that write held the key's row lock and ``ROW EXCLUSIVE`` on
``api_keys`` for the whole request: across every Power Map, fetch and broker
wait, with a second same-key request queued behind it. A route that never
committed then rolled the write back, so ``last_used_at`` never moved.

The #405 shape (``tests/dashboard/test_transaction_scope.py``), in four layers:

1. ``require_api_key`` commits its write: every route body starts with no
   transaction open, and the write lands even when the route never commits.
2. One test on real connections, with no session override: a read-only
   ``GET`` advances ``last_used_at`` as another connection sees it.
3. No other dependency of an ``/api/v1`` route resolves the session
   (structural), so a new dependency cannot reopen one before the body runs.
4. One test per outbound wait, recording ``session.in_transaction()`` at the
   moment of the wait. That covers a route body that reads and then waits.

Each test ``_cold()``s before its request: setup leaves rows in the shared
session's identity map, and a ``session.get`` would answer from memory with no
SQL, so a read that opens a transaction in production would open none here.
"""

import contextlib
import hashlib

import pytest
from fakeredis import aioredis as fakeredis_aio
from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.api.deps import (
    get_db_session,
    get_db_session_factory,
    get_power_map,
    get_redis_client,
    require_api_key,
)
from src.api.main import app
from src.core.database import get_engine, reset_engine
from src.core.models import ApiKey, InfoItem
from tests.core.power_map.fake import WSLCB_ID, FakePowerMap, org

_KEY = "test-secret-key"  # seeded, committed, by conftest's test_engine
_KEY_HASH = hashlib.sha256(_KEY.encode()).hexdigest()
_HEADERS = {"X-API-Key": _KEY}
_DLQ = "content.revisions.dlq"


async def _cold(session) -> None:
    """Hand the request a session that knows nothing, as production's does."""
    await session.commit()
    session.expunge_all()


# --- 1. the dependency ---------------------------------------------------


async def test_a_valid_key_is_resolved_with_no_transaction_left_open(session):
    await _cold(session)

    await require_api_key(_KEY, session)

    assert not session.in_transaction()
    stamped = await session.scalar(select(ApiKey.last_used_at).where(ApiKey.key_hash == _KEY_HASH))
    assert stamped is not None


async def test_a_bad_key_writes_nothing_and_leaves_nothing_open(session):
    await _cold(session)

    with pytest.raises(Exception, match="Invalid API key"):
        await require_api_key("not-a-key", session)

    # The lookup's read is still open here; get_db_session's close ends it.
    assert not session.dirty


# --- 2. on real connections ----------------------------------------------


@pytest.fixture
async def unshared_app(test_engine):
    """The app on ``get_engine()`` (the pinned test DB), with no session override.

    Requests commit for real, so the seeded key's ``last_used_at`` is put back.
    """
    assert get_db_session not in app.dependency_overrides
    async with test_engine.connect() as conn:
        before = await _last_used(conn)
    reset_engine()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await get_engine().dispose()
        reset_engine()
        async with test_engine.begin() as conn:
            await conn.execute(
                text("UPDATE information.api_keys SET last_used_at = :v WHERE key_hash = :h"),
                {"v": before, "h": _KEY_HASH},
            )


async def _last_used(conn):
    return await conn.scalar(
        text("SELECT last_used_at FROM information.api_keys WHERE key_hash = :h"), {"h": _KEY_HASH}
    )


async def test_a_read_only_request_advances_last_used_at(unshared_app, test_engine):
    async with test_engine.connect() as conn:
        before = await _last_used(conn)

    r = await unshared_app.get("/api/v1/domains", headers=_HEADERS)

    assert r.status_code == 200
    async with test_engine.connect() as conn:
        after = await _last_used(conn)
    assert after is not None and after != before


# --- 3. no other dependency takes the session ----------------------------


def _session_holders(dependant: Dependant) -> list[str]:
    """Each dependency below ``dependant``, except the key's, that resolves the session."""
    found = []
    for dep in dependant.dependencies:
        if dep.call in (get_db_session, require_api_key):
            continue
        if get_db_session in set(_calls(dep)):
            found.append(getattr(dep.call, "__qualname__", repr(dep.call)))
        found.extend(_session_holders(dep))
    return found


def _calls(dependant: Dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def _api_routes(target: FastAPI) -> list[APIRoute]:
    return [r for r in target.routes if isinstance(r, APIRoute) and r.path.startswith("/api/")]


def session_holding_routes(target: FastAPI) -> list[str]:
    """``path: dependency`` for each API dependency that could open a transaction."""
    return sorted(
        f"{r.path}: {name}" for r in _api_routes(target) for name in _session_holders(r.dependant)
    )


def test_no_api_dependency_but_the_keys_takes_the_session():
    routes = _api_routes(app)
    # Non-vacuity: a walk that finds no routes is broken, not passing.
    assert len(routes) >= 58, f"only {len(routes)} API routes found - is the walk broken?"

    holders = session_holding_routes(app)
    assert not holders, (
        "An API dependency resolves the DB session, so its read opens a transaction "
        "before the route body, and nothing ends it before an outbound wait (#521). Read "
        "in the route body, or end the read as require_api_key does:\n  " + "\n  ".join(holders)
    )


def test_the_walk_catches_a_seeded_session_dependency():
    """Proof the tripwire fires: direct, nested, and the key's own are told apart."""
    seeded = FastAPI()
    router = APIRouter(prefix="/api/v1/seeded", dependencies=[Depends(require_api_key)])

    async def reads_first(session=Depends(get_db_session)) -> None: ...

    async def wraps_it(_=Depends(reads_first)) -> None: ...

    @router.get("/fine")
    async def _fine(session=Depends(get_db_session)) -> None: ...

    @router.get("/direct")
    async def _direct(_=Depends(reads_first)) -> None: ...

    @router.get("/nested")
    async def _nested(_=Depends(wraps_it)) -> None: ...

    seeded.include_router(router)

    assert session_holding_routes(seeded) == [
        "/api/v1/seeded/direct: test_the_walk_catches_a_seeded_session_dependency."
        "<locals>.reads_first",
        "/api/v1/seeded/nested: test_the_walk_catches_a_seeded_session_dependency."
        "<locals>.reads_first",
        "/api/v1/seeded/nested: test_the_walk_catches_a_seeded_session_dependency."
        "<locals>.wraps_it",
    ]


# --- 4. each outbound wait -----------------------------------------------


class _WatchingPowerMap(FakePowerMap):
    def __init__(self, session) -> None:
        super().__init__(org())
        self.session = session
        self.held: list[bool] = []

    async def get_org(self, pm_org_id, etag=None):
        self.held.append(self.session.in_transaction())
        return await super().get_org(pm_org_id, etag)


class _WatchingRedis(fakeredis_aio.FakeRedis):
    """Records, per broker command, whether the request's session held a transaction."""

    def __init__(self, session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.held: list[bool] = []

    async def execute_command(self, *args, **options):
        self.held.append(self.session.in_transaction())
        return await super().execute_command(*args, **options)


class _WatchingFetcher:
    def __init__(self, session) -> None:
        self.session = session
        self.held: list[bool] = []

    async def execute(self, effect):
        self.held.append(self.session.in_transaction())
        raise RuntimeError("stub fetch: the wait is what is measured")


def _override(dep, value) -> None:
    app.dependency_overrides[dep] = lambda: value


async def test_creating_an_item_with_an_org_waits_on_power_map_with_no_transaction(client, session):
    await _cold(session)
    pm = _WatchingPowerMap(session)
    _override(get_power_map, pm)

    r = await client.post(
        "/api/v1/info-items",
        headers=_HEADERS,
        json={"name": "Txn Item", "rep_fields": {}, "pm_org_id": WSLCB_ID},
    )

    assert r.status_code == 201, r.text
    assert pm.held == [False]


async def test_linking_an_org_waits_on_power_map_with_no_transaction(client, session):
    """The route reads the item, then ``link_org`` asks Power Map: read, then wait."""
    item = InfoItem(name="Txn Item", rep_fields={})
    session.add(item)
    await session.flush()
    item_id = item.info_item_id
    await _cold(session)
    pm = _WatchingPowerMap(session)
    _override(get_power_map, pm)

    r = await client.put(
        f"/api/v1/info-items/{item_id}/org", headers=_HEADERS, json={"pm_org_id": WSLCB_ID}
    )

    assert r.status_code == 200, r.text
    assert pm.held == [False]
    assert (await session.get(InfoItem, item_id)).pm_org_id == WSLCB_ID


async def test_linking_an_unknown_item_is_still_a_404(client, session):
    await _cold(session)
    pm = _WatchingPowerMap(session)
    _override(get_power_map, pm)

    r = await client.put(
        "/api/v1/info-items/01JZZZZZZZZZZZZZZZZZZZZZZZ/org",
        headers=_HEADERS,
        json={"pm_org_id": WSLCB_ID},
    )

    assert r.status_code == 404, r.text
    assert pm.held == [], "Power Map is not asked for a missing item"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/tools/fetch-and-render", {"url": "https://example.com/page"}),
        (
            "/api/v1/tools/preview-extraction",
            {
                "url": "https://example.com/page",
                "source_spec": {
                    "schema_version": 1,
                    "extraction": {"algorithm": "full_page"},
                    "fingerprint": {},
                },
            },
        ),
        (
            "/api/v1/tools/propose-selectors",
            {"url": "https://example.com/page", "description": "the fee table"},
        ),
    ],
)
async def test_a_tool_fetches_with_no_transaction(client, session, path, body):
    await _cold(session)
    fetcher = _WatchingFetcher(session)
    original = app.state.fetch_driver
    app.state.fetch_driver = fetcher
    try:
        # The stub raises once it has recorded; whether the route maps it to a
        # status or lets it out is not what this test is about.
        with contextlib.suppress(RuntimeError):
            await client.post(path, headers=_HEADERS, json=body)
    finally:
        app.state.fetch_driver = original

    assert fetcher.held == [False]


async def test_a_dlq_listing_runs_with_no_transaction(client, session):
    await _cold(session)
    redis = _WatchingRedis(session)
    _override(get_redis_client, redis)

    r = await client.get(f"/api/v1/tools/dead-letters/{_DLQ}", headers=_HEADERS)

    assert r.status_code == 200, r.text
    assert redis.held and not any(redis.held), redis.held


async def test_a_dlq_discard_runs_with_no_transaction(client, session):
    redis = _WatchingRedis(session)
    entry_id = (await redis.xadd(_DLQ, {"n": "0"})).decode()
    await _cold(session)
    redis.held.clear()
    _override(get_redis_client, redis)

    r = await client.post(
        f"/api/v1/tools/dead-letters/{_DLQ}/discard",
        headers=_HEADERS,
        json={"entry_ids": [entry_id]},
    )

    assert r.status_code == 200, r.text
    assert redis.held and not any(redis.held), redis.held


async def test_a_dlq_reprocess_runs_with_no_transaction(client, session, test_engine):
    redis = _WatchingRedis(session)
    entry_id = (await redis.xadd(_DLQ, {"n": "0"})).decode()
    await _cold(session)
    redis.held.clear()
    _override(get_redis_client, redis)
    _override(get_db_session_factory, async_sessionmaker(bind=test_engine, expire_on_commit=False))

    r = await client.post(
        f"/api/v1/tools/dead-letters/{_DLQ}/reprocess",
        headers=_HEADERS,
        json={"entry_ids": [entry_id]},
    )

    assert r.status_code == 200, r.text
    assert redis.held and not any(redis.held), redis.held
