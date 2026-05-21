"""Tests for GET/POST/DELETE/PATCH /dashboard/settings/api-keys."""

import pytest
from sqlalchemy import select

from src.core.models import ApiKey, AppUser
from src.dashboard.deps import generate_api_key

_HEADERS = {"X-ExeDev-UserID": "ext-settings", "X-ExeDev-Email": "settings@example.com"}
_URL = "/dashboard/settings/api-keys"


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_api_keys_no_auth_redirects(client):
    response = await client.get(_URL, follow_redirects=False)
    assert response.status_code == 307


@pytest.mark.asyncio
async def test_get_api_keys_empty_list_returns_200(client):
    response = await client.get(_URL, headers=_HEADERS)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_get_api_keys_lists_users_keys(client, session):
    user = AppUser(external_id="ext-settings", email="settings@example.com")
    session.add(user)
    await session.flush()
    raw_key, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        user_id=user.id, label="My listed key", key_prefix=key_prefix, key_hash=key_hash
    )
    session.add(api_key)
    await session.flush()

    response = await client.get(_URL, headers=_HEADERS)
    assert response.status_code == 200
    assert "My listed key" in response.text
    assert key_prefix in response.text


# ---------------------------------------------------------------------------
# POST (create)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_create_key_no_auth_redirects(client):
    response = await client.post(_URL, data={"label": "x"}, follow_redirects=False)
    assert response.status_code == 307


@pytest.mark.asyncio
async def test_post_create_key_returns_200_with_raw_key(client, session):
    response = await client.post(
        _URL,
        data={"label": "New key"},
        headers=_HEADERS,
    )
    assert response.status_code == 200
    assert "co_" in response.text  # raw key in one-time reveal

    result = await session.execute(select(ApiKey).where(ApiKey.label == "New key"))
    api_key = result.scalar_one_or_none()
    assert api_key is not None


@pytest.mark.asyncio
async def test_post_create_key_empty_label_returns_422(client):
    response = await client.post(
        _URL,
        data={"label": ""},
        headers=_HEADERS,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_key_removes_it(client, session):
    user = AppUser(external_id="ext-settings", email="settings@example.com")
    session.add(user)
    await session.flush()
    _, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(user_id=user.id, label="To delete", key_prefix=key_prefix, key_hash=key_hash)
    session.add(api_key)
    await session.flush()
    key_id = str(api_key.id)

    response = await client.delete(f"{_URL}/{key_id}", headers=_HEADERS)
    assert response.status_code == 200

    # Re-query to confirm the row is gone (deleted instance can't be refreshed).
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == api_key.id).execution_options(populate_existing=True)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_other_users_key_returns_404(client, session):
    other = AppUser(external_id="ext-other", email="other@example.com")
    session.add(other)
    await session.flush()
    _, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        user_id=other.id, label="Other's key", key_prefix=key_prefix, key_hash=key_hash
    )
    session.add(api_key)
    await session.flush()

    # Request as _HEADERS user (different user)
    response = await client.delete(f"{_URL}/{str(api_key.id)}", headers=_HEADERS)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PATCH (rename)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_renames_label(client, session):
    user = AppUser(external_id="ext-settings", email="settings@example.com")
    session.add(user)
    await session.flush()
    _, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(user_id=user.id, label="Old label", key_prefix=key_prefix, key_hash=key_hash)
    session.add(api_key)
    await session.flush()

    response = await client.patch(
        f"{_URL}/{str(api_key.id)}",
        data={"label": "New label"},
        headers=_HEADERS,
    )
    assert response.status_code == 200
    assert "New label" in response.text

    await session.refresh(api_key)
    assert api_key.label == "New label"


@pytest.mark.asyncio
async def test_patch_other_users_key_returns_404(client, session):
    other = AppUser(external_id="ext-other", email="other@example.com")
    session.add(other)
    await session.flush()
    _, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        user_id=other.id, label="Other's key", key_prefix=key_prefix, key_hash=key_hash
    )
    session.add(api_key)
    await session.flush()

    response = await client.patch(
        f"{_URL}/{str(api_key.id)}",
        data={"label": "Hijacked"},
        headers=_HEADERS,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Issue #37 — UX improvements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_keys_header_has_add_key_button(client):
    """Header shows toggle button; create form is not always open."""
    response = await client.get(_URL, headers=_HEADERS)
    assert response.status_code == 200
    assert "Add key" in response.text
    # The form is inside a toggleable container driven by apiKeyCreate
    assert 'x-data="apiKeyCreate"' in response.text


@pytest.mark.asyncio
async def test_thead_label_column_before_prefix(client, session):
    """Column order is Label, Prefix, Last Used, Actions."""
    user = AppUser(external_id="ext-settings", email="settings@example.com")
    session.add(user)
    await session.flush()
    _, prefix, key_hash = generate_api_key()
    session.add(ApiKey(user_id=user.id, label="Order test", key_prefix=prefix, key_hash=key_hash))
    await session.flush()

    response = await client.get(_URL, headers=_HEADERS)
    thead = response.text[response.text.index("<thead>") : response.text.index("</thead>")]
    assert thead.index("Label") < thead.index("Prefix")


@pytest.mark.asyncio
async def test_row_uses_api_key_row_component(client, session):
    """Each key row uses the apiKeyRow Alpine component (starts in view mode)."""
    user = AppUser(external_id="ext-settings", email="settings@example.com")
    session.add(user)
    await session.flush()
    _, prefix, key_hash = generate_api_key()
    session.add(
        ApiKey(user_id=user.id, label="Row component test", key_prefix=prefix, key_hash=key_hash)
    )
    await session.flush()

    response = await client.get(_URL, headers=_HEADERS)
    assert 'x-data="apiKeyRow"' in response.text


@pytest.mark.asyncio
async def test_reveal_copy_button_is_secondary_not_ghost(client):
    """Copy button in the new-key reveal uses btn--secondary (visible on light bg)."""
    response = await client.post(_URL, data={"label": "Copy style test"}, headers=_HEADERS)
    assert response.status_code == 200
    # Locate the reveal alert block and check button class within it
    start = response.text.index("alert--success")
    snippet = response.text[start : start + 600]
    assert "btn--secondary" in snippet
    assert "btn--ghost" not in snippet
