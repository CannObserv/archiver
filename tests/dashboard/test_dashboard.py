"""Dashboard foundation tests — index route, auth redirect, user upsert."""

import pytest


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
    from sqlalchemy import select

    from src.core.models import AppUser

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
    from sqlalchemy import select

    from src.core.models import AppUser

    # First request — creates user
    await client.get(
        "/dashboard/",
        headers={
            "X-ExeDev-UserID": "ext-emailchange",
            "X-ExeDev-Email": "old@example.com",
        },
    )

    # Second request — email changed on proxy side
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
