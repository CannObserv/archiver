"""HTTP-layer tests for POST /info-items/{id}/info-sources.

Covers role validation, shape consistency, fragment-shares-root, and existence.
Mirrors the cases in tests/core/tools/test_bind_info_source.py at the HTTP level
to confirm error translation.
"""

import pytest

from src.core.models import InfoItem, InfoItemSource, InfoSource

HEADERS = {"X-API-Key": "test-secret-key"}


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ARCHIVER_API_KEY", "test-secret-key")


def _root_doc(url: str) -> dict:
    return {
        "schema_version": 1,
        "target": {"url": url},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


def _fragment_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": "#agenda"},
        "fingerprint": {},
    }


@pytest.fixture
async def item(session):
    obj = InfoItem(name="t")
    session.add(obj)
    await session.flush()
    return obj


async def _make_source(session, *, url=None, parent_id=None):
    if url is not None:
        src = InfoSource(source_spec=_root_doc(url), schema_version=1)
    else:
        src = InfoSource(
            source_spec=_fragment_doc(),
            schema_version=1,
            parent_info_source_id=parent_id,
        )
    session.add(src)
    await session.flush()
    return src


@pytest.mark.asyncio
async def test_bind_root_with_omitted_role_201(client, session, item):
    src = await _make_source(session, url="https://example.com/a")
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id)},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] is None


@pytest.mark.asyncio
async def test_bind_fragment_with_cross_check_201(client, session, item):
    root = await _make_source(session, url="https://example.com/a")
    frag = await _make_source(session, parent_id=root.info_source_id)
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=root.info_source_id, role=None
        )
    )
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(frag.info_source_id), "role": "cross_check"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "cross_check"


@pytest.mark.asyncio
async def test_legacy_primary_role_rejected_422(client, session, item):
    src = await _make_source(session, url="https://example.com/a")
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id), "role": "primary"},
    )
    # Pydantic Literal rejects this before reaching the route handler
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "body"


@pytest.mark.asyncio
async def test_root_with_role_returns_422_domain(client, session, item):
    src = await _make_source(session, url="https://example.com/a")
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id), "role": "sub_aspect"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["errors"][0]["code"] == "role_shape_mismatch"


@pytest.mark.asyncio
async def test_fragment_with_null_role_returns_422_domain(client, session, item):
    root = await _make_source(session, url="https://example.com/a")
    frag = await _make_source(session, parent_id=root.info_source_id)
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=root.info_source_id, role=None
        )
    )
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(frag.info_source_id)},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["errors"][0]["code"] == "role_shape_mismatch"


@pytest.mark.asyncio
async def test_fragment_without_active_root_returns_422_domain(client, session, item):
    root = await _make_source(session, url="https://example.com/a")
    frag = await _make_source(session, parent_id=root.info_source_id)
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(frag.info_source_id), "role": "cross_check"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["errors"][0]["code"] == "active_root_missing"


@pytest.mark.asyncio
async def test_fragment_under_different_root_returns_422_domain(client, session, item):
    root_a = await _make_source(session, url="https://example.com/a")
    root_b = await _make_source(session, url="https://example.com/b")
    frag_of_b = await _make_source(session, parent_id=root_b.info_source_id)
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=root_a.info_source_id, role=None
        )
    )
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(frag_of_b.info_source_id), "role": "sub_aspect"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["errors"][0]["code"] == "fragment_parent_mismatch"


@pytest.mark.asyncio
async def test_unknown_info_source_returns_404(client, item):
    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": "01JZZZZZZZZZZZZZZZZZZZZZZZ"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unknown_info_item_returns_404(client, session):
    src = await _make_source(session, url="https://example.com/a")
    await session.commit()
    resp = await client.post(
        "/api/v1/info-items/01JZZZZZZZZZZZZZZZZZZZZZZZ/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id)},
    )
    assert resp.status_code == 404
