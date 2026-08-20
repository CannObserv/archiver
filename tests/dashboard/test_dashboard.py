"""Dashboard foundation tests — index route, auth redirect, user upsert."""

import pytest
from sqlalchemy import select

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
