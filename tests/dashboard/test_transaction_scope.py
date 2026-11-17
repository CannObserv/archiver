"""No dashboard request holds a transaction across an outbound wait (#405).

An open transaction holds ``ACCESS SHARE`` on every table it has read. A deploy
migration that needs ``ACCESS EXCLUSIVE`` on one of them queues behind it for
``MIGRATION_LOCK_TIMEOUT``, then fails, so viewing a page could fail a deploy.

Three layers:

1. ``get_dashboard_user`` ends its own read: every route body starts with no
   transaction open.
2. No other dependency of a dashboard route resolves the session (structural),
   so a new dependency cannot reopen one before the body runs.
3. One test per outbound wait, recording ``session.in_transaction()`` at the
   moment of the wait. That covers the route bodies that read and then wait,
   which layers 1 and 2 cannot see. The capture image's GCS read has its own
   test (``test_info_source_capture_image.py``).

Each test ``expunge_all()``s before its request. Setup leaves its rows in the
shared session's identity map, so the route's ``session.get`` would answer
from memory without SQL, and a read that opens a transaction in production
would open none here.
"""

from fakeredis import aioredis as fakeredis_aio
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.datastructures import Headers

from src.api.deps import get_db_session, get_notifier, get_power_map, get_redis_client
from src.api.main import app
from src.core.models import AppUser, ChangesOutboxRow, InfoItem, NotificationSubscription
from src.dashboard.deps import get_dashboard_user
from src.dashboard.routes import index as index_routes
from src.dashboard.routes import notifications as notification_routes
from tests.core.notifier.fake import DEV_SINK, FakeNotifier
from tests.core.power_map.fake import WSLCB_ID, FakePowerMap, org

_EXTERNAL_ID = "ext-txn"
_EMAIL = "txn@example.com"
_HEADERS = {"X-ExeDev-UserID": _EXTERNAL_ID, "X-ExeDev-Email": _EMAIL}


async def _known_user(session) -> None:
    """The steady state: a login whose row already matches, so no upsert commits."""
    session.add(AppUser(external_id=_EXTERNAL_ID, email=_EMAIL))
    await session.flush()


async def _cold(session) -> None:
    """Hand the request a session that knows nothing, as production's does."""
    await session.commit()
    session.expunge_all()


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/",
            "query_string": b"",
            "headers": Headers(headers).raw,
        }
    )


# --- 1. the dependency ---------------------------------------------------


async def test_a_known_user_is_resolved_with_no_transaction_left_open(session):
    await _known_user(session)
    await _cold(session)

    user = await get_dashboard_user(_request(_HEADERS), session)

    assert not session.in_transaction()
    # Committing (never rolling back) keeps the loaded attributes the templates read.
    assert user.email == _EMAIL


async def test_a_first_login_is_resolved_with_no_transaction_left_open(session):
    user = await get_dashboard_user(_request(_HEADERS), session)

    assert not session.in_transaction()
    assert user.external_id == _EXTERNAL_ID


async def test_an_email_change_is_resolved_with_no_transaction_left_open(session):
    session.add(AppUser(external_id=_EXTERNAL_ID, email="old@example.com"))
    await session.flush()
    await _cold(session)

    user = await get_dashboard_user(_request(_HEADERS), session)

    assert not session.in_transaction()
    assert user.email == _EMAIL


# --- 2. no other dependency takes the session ----------------------------


def _session_holders(dependant: Dependant) -> list[str]:
    """Each dependency below ``dependant``, except the user's, that resolves the session."""
    found = []
    for dep in dependant.dependencies:
        if dep.call in (get_db_session, get_dashboard_user):
            continue
        if get_db_session in set(_calls(dep)):
            found.append(getattr(dep.call, "__qualname__", repr(dep.call)))
        found.extend(_session_holders(dep))
    return found


def _calls(dependant: Dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def _dashboard_routes(target: FastAPI) -> list[APIRoute]:
    return [r for r in target.routes if isinstance(r, APIRoute) and not r.path.startswith("/api/")]


def session_holding_routes(target: FastAPI) -> list[str]:
    """``path: dependency`` for each dashboard dependency that could open a transaction."""
    return sorted(
        f"{r.path}: {name}"
        for r in _dashboard_routes(target)
        for name in _session_holders(r.dependant)
    )


def test_no_dashboard_dependency_but_the_users_takes_the_session():
    routes = _dashboard_routes(app)
    # Non-vacuity: a walk that finds no routes is broken, not passing.
    assert len(routes) >= 89, f"only {len(routes)} dashboard routes found - is the walk broken?"

    holders = session_holding_routes(app)
    assert not holders, (
        "A dashboard dependency resolves the DB session, so its read opens a transaction "
        "before the route body, and nothing ends it before an outbound wait (#405). Read "
        "in the route body, or end the read as get_dashboard_user does:\n  " + "\n  ".join(holders)
    )


def test_the_walk_catches_a_seeded_session_dependency():
    """Proof the tripwire fires: direct, nested, and the user's own are told apart."""
    seeded = FastAPI()
    router = APIRouter(prefix="/dashboard/seeded")

    async def reads_first(session=Depends(get_db_session)) -> None: ...

    async def wraps_it(_=Depends(reads_first)) -> None: ...

    @router.get("/fine")
    async def _fine(user=Depends(get_dashboard_user), session=Depends(get_db_session)) -> None: ...

    @router.get("/direct")
    async def _direct(_=Depends(reads_first)) -> None: ...

    @router.get("/nested")
    async def _nested(_=Depends(wraps_it)) -> None: ...

    seeded.include_router(router)

    assert session_holding_routes(seeded) == [
        "/dashboard/seeded/direct: test_the_walk_catches_a_seeded_session_dependency."
        "<locals>.reads_first",
        "/dashboard/seeded/nested: test_the_walk_catches_a_seeded_session_dependency."
        "<locals>.reads_first",
        "/dashboard/seeded/nested: test_the_walk_catches_a_seeded_session_dependency."
        "<locals>.wraps_it",
    ]


# --- 3. each outbound wait -----------------------------------------------


class _WatchingPowerMap(FakePowerMap):
    def __init__(self, session) -> None:
        super().__init__(org())
        self.session = session
        self.held: list[bool] = []

    async def get_org(self, pm_org_id, etag=None):
        self.held.append(self.session.in_transaction())
        return await super().get_org(pm_org_id, etag)

    async def search_orgs(self, q, limit=10):
        self.held.append(self.session.in_transaction())
        return await super().search_orgs(q, limit)


class _WatchingNotifier(FakeNotifier):
    def __init__(self, session) -> None:
        super().__init__(DEV_SINK)
        self.session = session
        self.held: list[bool] = []

    async def list_channels(self):
        self.held.append(self.session.in_transaction())
        return await super().list_channels()

    async def dispatch_composed(self, **kwargs):
        self.held.append(self.session.in_transaction())
        return await super().dispatch_composed(**kwargs)


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


async def test_power_map_search_waits_with_no_transaction(client, session):
    await _known_user(session)
    await _cold(session)
    pm = _WatchingPowerMap(session)
    _override(get_power_map, pm)

    r = await client.get("/dashboard/power-map/orgs", params={"q": "wslcb"}, headers=_HEADERS)

    assert r.status_code == 200
    assert pm.held == [False]


async def test_linking_an_org_waits_on_power_map_with_no_transaction(client, session):
    """The route reads the item, then ``link_org`` asks Power Map: read, then wait."""
    await _known_user(session)
    item = InfoItem(name="Txn Item", rep_fields={})
    session.add(item)
    await session.flush()
    item_id = item.info_item_id
    await _cold(session)
    pm = _WatchingPowerMap(session)
    _override(get_power_map, pm)

    r = await client.put(
        f"/dashboard/info-items/{item_id}/org", headers=_HEADERS, data={"pm_org_id": WSLCB_ID}
    )

    assert r.status_code == 200, r.text
    assert pm.held == [False]
    assert (await session.get(InfoItem, item_id)).pm_org_id == WSLCB_ID


async def test_the_register_preview_fetches_with_no_transaction(client, session):
    await _known_user(session)
    await _cold(session)
    fetcher = _WatchingFetcher(session)
    original = app.state.fetch_driver
    app.state.fetch_driver = fetcher
    try:
        r = await client.post(
            "/dashboard/register/preview",
            headers=_HEADERS,
            data={
                "url": "https://example.com/page",
                "source_specs": (
                    '[{"schema_version":1,"extraction":{"algorithm":"full_page"},"fingerprint":{}}]'
                ),
            },
        )
    finally:
        app.state.fetch_driver = original

    assert r.status_code == 200
    assert fetcher.held == [False]


async def test_the_redis_badge_pings_with_no_transaction(client, session):
    await _known_user(session)
    await _cold(session)
    redis = _WatchingRedis(session)
    _override(get_redis_client, redis)

    r = await client.get("/dashboard/health/redis", headers=_HEADERS)

    assert r.status_code == 200
    assert redis.held == [False]


async def test_the_consumers_lag_probe_runs_with_no_transaction(client, session, monkeypatch):
    await _known_user(session)
    await _cold(session)
    held: list[bool] = []

    async def watching_lag(_redis):
        held.append(session.in_transaction())
        return []

    monkeypatch.setenv("ARCHIVER_BUS_CONSUMER", "1")
    monkeypatch.setattr(index_routes, "collect_group_lag", watching_lag)
    _override(get_redis_client, fakeredis_aio.FakeRedis())

    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)

    assert r.status_code == 200
    assert held == [False]


async def test_the_bus_triage_page_lists_dlqs_with_no_transaction(client, session):
    """The page reads the outbox first, then the broker: read, then wait."""
    await _known_user(session)
    session.add(ChangesOutboxRow(topic="info.changes", payload={"schema_version": 2}))
    await session.flush()
    await _cold(session)
    redis = _WatchingRedis(session)
    _override(get_redis_client, redis)

    r = await client.get("/dashboard/bus-triage", headers=_HEADERS)

    assert r.status_code == 200
    assert redis.held and not any(redis.held), redis.held


async def test_a_dlq_section_lists_with_no_transaction(client, session):
    await _known_user(session)
    await _cold(session)
    redis = _WatchingRedis(session)
    _override(get_redis_client, redis)

    r = await client.get("/dashboard/bus-triage/dlq/content.revisions.dlq", headers=_HEADERS)

    assert r.status_code == 200
    assert redis.held and not any(redis.held), redis.held


async def test_the_notifier_card_lists_channels_with_no_transaction(client, session):
    await _known_user(session)
    await _cold(session)
    notifier = _WatchingNotifier(session)
    _override(get_notifier, notifier)

    r = await client.get("/dashboard/settings/notifier", headers=_HEADERS)

    assert r.status_code == 200
    assert notifier.held == [False]


async def test_a_test_send_composes_and_dispatches_with_no_transaction(
    client, session, monkeypatch
):
    """The route reads the subscription, then composes off-loop and dispatches (30 s)."""
    await _known_user(session)
    sub = NotificationSubscription(
        title="Txn", scope="global", events=["change_detected"], remote_channel_id=DEV_SINK.id
    )
    session.add(sub)
    await session.flush()
    sub_id = sub.id
    await _cold(session)
    notifier = _WatchingNotifier(session)
    _override(get_notifier, notifier)
    composed_held: list[bool] = []
    compose = notification_routes.compose

    def watching_compose(*args, **kwargs):
        composed_held.append(session.in_transaction())
        return compose(*args, **kwargs)

    monkeypatch.setattr(notification_routes, "compose", watching_compose)

    r = await client.post(f"/dashboard/notifications/{sub_id}/test-send", headers=_HEADERS)

    assert r.status_code == 200, r.text
    assert composed_held == [False]
    assert notifier.held == [False]
