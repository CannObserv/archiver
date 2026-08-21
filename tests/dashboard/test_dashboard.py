"""Dashboard foundation tests - index route, auth redirect, user upsert."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.api.deps import get_db_session
from src.api.main import app
from src.core.models import AppUser


@pytest.mark.asyncio
async def test_dashboard_index_no_headers_redirects(client):
    response = await client.get("/dashboard/", follow_redirects=False)
    assert response.status_code == 307
    assert "/__exe.dev/login" in response.headers["location"]
    assert "redirect" in response.headers["location"]


@pytest.mark.asyncio
async def test_dashboard_index_missing_email_redirects(client):
    response = await client.get(
        "/dashboard/",
        headers={"X-ExeDev-UserID": "ext-001"},
        follow_redirects=False,
    )
    assert response.status_code == 307


@pytest.mark.asyncio
async def test_dashboard_index_authenticated_returns_200(client):
    response = await client.get(
        "/dashboard/",
        headers={
            "X-ExeDev-UserID": "ext-001",
            "X-ExeDev-Email": "alice@example.com",
        },
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_dashboard_index_creates_app_user(client, session):
    await client.get(
        "/dashboard/",
        headers={
            "X-ExeDev-UserID": "ext-newuser",
            "X-ExeDev-Email": "newuser@example.com",
        },
    )

    result = await session.execute(select(AppUser).where(AppUser.external_id == "ext-newuser"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.email == "newuser@example.com"


@pytest.mark.asyncio
async def test_dashboard_index_updates_email_on_change(client, session):
    # First request - creates user
    await client.get(
        "/dashboard/",
        headers={
            "X-ExeDev-UserID": "ext-emailchange",
            "X-ExeDev-Email": "old@example.com",
        },
    )

    # Second request - email changed on proxy side
    await client.get(
        "/dashboard/",
        headers={
            "X-ExeDev-UserID": "ext-emailchange",
            "X-ExeDev-Email": "new@example.com",
        },
    )

    result = await session.execute(select(AppUser).where(AppUser.external_id == "ext-emailchange"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.email == "new@example.com"


@pytest.mark.asyncio
async def test_dashboard_repeat_login_same_email_returns_200(client, session):
    # The common production path: a known external_id whose email has not
    # moved resolves on the SELECT and never reaches the upsert at all (#180).
    # It stayed a repeat-login regression test through that change (#177).
    headers = {
        "X-ExeDev-UserID": "ext-repeat",
        "X-ExeDev-Email": "repeat@example.com",
    }
    first = await client.get("/dashboard/", headers=headers)
    second = await client.get("/dashboard/", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    # The rendered identity, not just the status: a dependency that returned
    # None still 200s, because Jinja renders `None.email` as an empty string.
    assert "repeat@example.com" in second.text
    result = await session.execute(select(AppUser).where(AppUser.external_id == "ext-repeat"))
    users = result.scalars().all()
    assert len(users) == 1


@pytest.mark.asyncio
async def test_dashboard_new_user_with_existing_email_returns_200(client, session):
    # #177 path 1: new external_id, email already held by another row.
    await client.get(
        "/dashboard/",
        headers={
            "X-ExeDev-UserID": "ext-shared-1",
            "X-ExeDev-Email": "shared@example.com",
        },
    )

    response = await client.get(
        "/dashboard/",
        headers={
            "X-ExeDev-UserID": "ext-shared-2",
            "X-ExeDev-Email": "shared@example.com",
        },
    )

    assert response.status_code == 200
    result = await session.execute(select(AppUser).where(AppUser.email == "shared@example.com"))
    assert len(result.scalars().all()) == 2


@pytest.mark.asyncio
async def test_dashboard_email_change_onto_existing_email_returns_200(client, session):
    # #177 path 2: known external_id whose email changes to one another row holds.
    await client.get(
        "/dashboard/",
        headers={
            "X-ExeDev-UserID": "ext-holder",
            "X-ExeDev-Email": "held@example.com",
        },
    )
    await client.get(
        "/dashboard/",
        headers={
            "X-ExeDev-UserID": "ext-mover",
            "X-ExeDev-Email": "moving@example.com",
        },
    )

    response = await client.get(
        "/dashboard/",
        headers={
            "X-ExeDev-UserID": "ext-mover",
            "X-ExeDev-Email": "held@example.com",
        },
    )

    assert response.status_code == 200
    result = await session.execute(select(AppUser).where(AppUser.external_id == "ext-mover"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.email == "held@example.com"


@pytest.mark.asyncio
async def test_dashboard_repeat_visit_emits_no_app_user_write(client, session, test_engine):
    # #180: the identity upsert is a write on the read path. Worse than its
    # cost: ON CONFLICT DO UPDATE locks the conflicting row even when the
    # update is skipped, and the dependency holds it for the whole request,
    # so an operator's concurrent partials queue on their own app_users row.
    headers = {"X-ExeDev-UserID": "ext-noop", "X-ExeDev-Email": "noop@example.com"}
    await client.get("/dashboard/", headers=headers)

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _record)
    try:
        response = await client.get("/dashboard/", headers=headers)
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _record)

    assert response.status_code == 200
    writes = [s for s in statements if "app_users" in s and "SELECT" not in s.split("\n")[0]]
    assert writes == []


@pytest.mark.asyncio
async def test_dashboard_read_only_visit_persists_app_user(test_engine, committed_rows):
    # #180: get_db_session never commits and read-only routes don't either, so
    # before the fix this row was inserted and rolled back on every page view.
    # Needs real per-request sessions - the shared-SAVEPOINT `session` fixture
    # keeps one uncommitted session across requests and hides the rollback.
    factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def _real_session():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db_session] = _real_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.get(
                "/dashboard/health",
                headers={"X-ExeDev-UserID": "ext-persist", "X-ExeDev-Email": "persist@example.com"},
            )
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 200
    async with factory() as db:
        result = await db.execute(select(AppUser).where(AppUser.external_id == "ext-persist"))
        user = result.scalar_one_or_none()
        assert user is not None
        committed_rows.append((AppUser, user.id))
