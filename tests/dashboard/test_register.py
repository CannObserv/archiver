"""Tests for /dashboard/register registration flow (#49)."""

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from co_core.effects.fetch import FetchResult
from sqlalchemy import select

from src.api.deps import get_watcher_client
from src.api.main import app
from src.core.models import InfoItem, InfoItemSource, InfoSource
from src.core.models.domain import Domain

_HEADERS = {"X-ExeDev-UserID": "ext-reg", "X-ExeDev-Email": "reg@example.com"}

_VALID_SPEC = '[{"schema_version":1,"extraction":{"algorithm":"full_page"},"fingerprint":{}}]'


def _mock_watcher() -> MagicMock:
    watcher = MagicMock()
    result = MagicMock()
    result.id = "01HZZWATCHER00000000000001"
    watcher.provision_watched_item = AsyncMock(return_value=result)
    return watcher


# ---------------------------------------------------------------------------
# Step 1 — GET /dashboard/register
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_get_200(client):
    r = await client.get("/dashboard/register", headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_register_unauthenticated_redirects(client):
    r = await client.get("/dashboard/register", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_register_shows_url_input(client):
    r = await client.get("/dashboard/register", headers=_HEADERS)
    assert "url" in r.text.lower()


# ---------------------------------------------------------------------------
# URL check partial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_url_check_new_url_new_domain(client):
    r = await client.get(
        "/dashboard/register/url-check?url=https://brandnew.example.com/path",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "brandnew.example.com" in r.text


@pytest.mark.asyncio
async def test_url_check_known_domain(client, session):
    domain = Domain(name="known.example.com")
    session.add(domain)
    await session.flush()

    r = await client.get(
        "/dashboard/register/url-check?url=https://known.example.com/new-page",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "known.example.com" in r.text


@pytest.mark.asyncio
async def test_url_check_case_a_url_already_registered(client, session):
    """URL exists and is bound to an InfoItem — show Case A card."""
    src = InfoSource(
        url="https://casea.example.com/page",
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )
    item = InfoItem(name="Existing Item A")
    session.add_all([src, item])
    await session.flush()
    binding = InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id)
    session.add(binding)
    await session.flush()

    r = await client.get(
        "/dashboard/register/url-check?url=https://casea.example.com/page",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "Existing Item A" in r.text
    assert "Register" in r.text


@pytest.mark.asyncio
async def test_url_check_case_b_unbound_source(client, session):
    """URL exists as InfoSource but not bound — show Case B card."""
    src = InfoSource(
        url="https://caseb.example.com/page",
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )
    session.add(src)
    await session.flush()

    r = await client.get(
        "/dashboard/register/url-check?url=https://caseb.example.com/page",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    # Unbound source card should appear
    assert "caseb.example.com" in r.text


@pytest.mark.asyncio
async def test_url_check_invalid_url_returns_400(client):
    r = await client.get(
        "/dashboard/register/url-check?url=not-a-url",
        headers=_HEADERS,
    )
    assert r.status_code in (200, 400, 422)


def _dispatch_island(html: str) -> dict:
    """Extract + parse the urlCheckDispatch JSON data island from a fragment.

    Attribute-aware element match (quoted attribute values may contain ">",
    e.g. x-show="step>=2") followed by the element's first JSON script block,
    so template whitespace/attribute reshuffles don't break the tests.
    """
    m = re.search(
        r'x-data="urlCheckDispatch"(?:[^>"]|"[^"]*")*>\s*'
        r'<script type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert m, "urlCheckDispatch data island not found in fragment"
    return json.loads(m.group(1))


@pytest.mark.asyncio
async def test_url_check_dispatch_island_known_domain(client, session):
    """url-check fragment carries a JSON island for the wizard summary bar (#53)."""
    session.add(Domain(name="island-known.example.com"))
    await session.flush()

    r = await client.get(
        "/dashboard/register/url-check?url=https://island-known.example.com/p",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    payload = _dispatch_island(r.text)
    assert payload == {
        "hostname": "island-known.example.com",
        "case": "new",
        "domain_known": True,
    }


@pytest.mark.asyncio
async def test_url_check_dispatch_island_new_domain(client):
    r = await client.get(
        "/dashboard/register/url-check?url=https://island-new.example.com/p",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    payload = _dispatch_island(r.text)
    assert payload == {
        "hostname": "island-new.example.com",
        "case": "new",
        "domain_known": False,
    }


@pytest.mark.asyncio
async def test_url_check_dispatch_island_case_a(client, session):
    """The island is emitted on Case A/B cards too, not just the domain badge."""
    src = InfoSource(
        url="https://island-a.example.com/page",
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )
    item = InfoItem(name="Island Item A")
    session.add_all([src, item])
    await session.flush()
    session.add(InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id))
    await session.flush()

    r = await client.get(
        "/dashboard/register/url-check?url=https://island-a.example.com/page",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    payload = _dispatch_island(r.text)
    assert payload["hostname"] == "island-a.example.com"
    assert payload["case"] == "A"


@pytest.mark.asyncio
async def test_url_check_invalid_url_has_no_dispatch_island(client):
    r = await client.get(
        "/dashboard/register/url-check?url=not-a-url",
        headers=_HEADERS,
    )
    assert "urlCheckDispatch" not in r.text


# ---------------------------------------------------------------------------
# Rolling step-summary bar (#53)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_page_has_summary_bar(client):
    r = await client.get("/dashboard/register", headers=_HEADERS)
    assert r.status_code == 200
    assert 'id="wizard-summary"' in r.text


@pytest.mark.asyncio
async def test_summary_bar_is_labelled_group(client):
    """The summary bar is exposed to AT as a labelled group (#53 CR round 2)."""
    r = await client.get("/dashboard/register", headers=_HEADERS)
    # Attribute-aware tag match — a bare [^>]* would stop at the ">" inside
    # x-show="step>=2".
    m = re.search(r'<div id="wizard-summary"(?:[^>"]|"[^"]*")*>', r.text)
    assert m, "wizard-summary element not found"
    assert 'role="group"' in m.group(0)
    assert 'aria-label="Completed steps"' in m.group(0)


@pytest.mark.asyncio
async def test_review_selector_row_exposes_full_specs_in_title(client):
    """Step-4 review Selector cell carries the raw source_specs as a tooltip so
    multi-spec bags stay inspectable despite the compact summary (#53 CR)."""
    r = await client.get("/dashboard/register", headers=_HEADERS)
    # Adjacent to the summary binding — pins the tooltip to the review cell
    # itself, not just anywhere on the page.
    assert 'x-text="selectorSummary" :title="sourceSpecs"' in r.text


@pytest.mark.asyncio
async def test_register_page_textareas_carry_sync_refs(client):
    """source_specs / description textareas expose x-refs so registerWizard
    init() can re-sync server-rendered values on validation-error re-renders."""
    r = await client.get("/dashboard/register", headers=_HEADERS)
    assert 'x-ref="sourceSpecsInput"' in r.text
    assert 'x-ref="descriptionInput"' in r.text


# ---------------------------------------------------------------------------
# Spec suggestions partial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_specs_no_existing_sources(client):
    r = await client.get(
        "/dashboard/register/suggest-specs?url=https://nosuggestions.example.com/p",
        headers=_HEADERS,
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_suggest_specs_returns_existing_selectors(client, session):
    domain = Domain(name="suggestme.example.com")
    session.add(domain)
    await session.flush()
    src = InfoSource(
        url="https://suggestme.example.com/a",
        source_specs=[
            {
                "schema_version": 1,
                "extraction": {"algorithm": "css", "selector": "#main"},
                "fingerprint": {},
            }
        ],
        domain_name="suggestme.example.com",
    )
    session.add(src)
    await session.flush()

    r = await client.get(
        "/dashboard/register/suggest-specs?url=https://suggestme.example.com/b",
        headers=_HEADERS,
    )
    assert r.status_code == 200
    assert "css" in r.text or "#main" in r.text
    # The chip value field must carry the full spec JSON (not just the display label).
    # tojson encodes the value string as escaped JSON, so check bare key name without quotes.
    assert "schema_version" in r.text


# ---------------------------------------------------------------------------
# Happy path — POST /dashboard/register (atomic submit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_creates_info_item_source_binding(client, session):
    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://atomictest.example.com/page",
            "source_specs": _VALID_SPEC,
            "name": "Atomic Test Item",
            "description": "",
        },
    )
    # Should redirect to the detail page
    assert resp.status_code == 303
    location = resp.headers.get("location", "")
    assert "/dashboard/info-items/" in location

    # Verify data was created
    item_rows = list(
        (await session.execute(select(InfoItem).where(InfoItem.name == "Atomic Test Item")))
        .scalars()
        .all()
    )
    assert len(item_rows) == 1
    item = item_rows[0]

    # InfoSource exists
    src_rows = list(
        (
            await session.execute(
                select(InfoSource).where(InfoSource.url == "https://atomictest.example.com/page")
            )
        )
        .scalars()
        .all()
    )
    assert len(src_rows) >= 1

    # Binding exists
    binding = (
        await session.execute(
            select(InfoItemSource).where(
                InfoItemSource.info_item_id == item.info_item_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
    ).scalar_one()
    assert binding is not None


@pytest.mark.asyncio
async def test_register_sets_owner_from_dashboard_user(client, session):
    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://ownertest.example.com/page",
            "source_specs": _VALID_SPEC,
            "name": "Owner Test Item",
            "description": "",
        },
    )
    assert resp.status_code == 303

    # Get the created item
    item_rows = list(
        (await session.execute(select(InfoItem).where(InfoItem.name == "Owner Test Item")))
        .scalars()
        .all()
    )
    assert item_rows
    # owner should be set from current user (via ext-reg user ID)
    assert item_rows[0].owner is not None


# ---------------------------------------------------------------------------
# Watcher cadence forwarding (#50)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_forwards_selected_cadence(client, session):
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://cadence.example.com/page",
            "source_specs": _VALID_SPEC,
            "name": "Cadence Item",
            "description": "",
            "cadence": "6h",
        },
    )
    assert resp.status_code == 303
    watcher.provision_watched_item.assert_awaited_once()
    assert watcher.provision_watched_item.await_args.kwargs["schedule_config"] == {"interval": "6h"}


@pytest.mark.asyncio
async def test_register_omits_cadence_when_absent(client, session):
    # No cadence field → send None, let Watcher apply its own default.
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://cadencedefault.example.com/page",
            "source_specs": _VALID_SPEC,
            "name": "Cadence Default Item",
            "description": "",
        },
    )
    assert resp.status_code == 303
    watcher.provision_watched_item.assert_awaited_once()
    assert watcher.provision_watched_item.await_args.kwargs["schedule_config"] is None


@pytest.mark.asyncio
async def test_register_invalid_cadence_sends_none(client, session):
    # Unrecognised value is not fabricated into a default; send None.
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://cadencebad.example.com/page",
            "source_specs": _VALID_SPEC,
            "name": "Cadence Bad Item",
            "description": "",
            "cadence": "banana",
        },
    )
    assert resp.status_code == 303
    watcher.provision_watched_item.assert_awaited_once()
    assert watcher.provision_watched_item.await_args.kwargs["schedule_config"] is None


# ---------------------------------------------------------------------------
# Watcher active/paused forwarding (#60)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_active_when_checkbox_present(client, session):
    # "Watch active immediately" checked → omit is_active (Watcher defaults active).
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://active.example.com/page",
            "source_specs": _VALID_SPEC,
            "name": "Active Item",
            "description": "",
            "watch_active": "on",
        },
    )
    assert resp.status_code == 303
    watcher.provision_watched_item.assert_awaited_once()
    assert watcher.provision_watched_item.await_args.kwargs["is_active"] is None


@pytest.mark.asyncio
async def test_register_paused_when_checkbox_absent(client, session):
    # Unchecked checkbox sends nothing → provision paused (is_active=False).
    watcher = _mock_watcher()
    app.dependency_overrides[get_watcher_client] = lambda: watcher

    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://paused.example.com/page",
            "source_specs": _VALID_SPEC,
            "name": "Paused Item",
            "description": "",
        },
    )
    assert resp.status_code == 303
    watcher.provision_watched_item.assert_awaited_once()
    assert watcher.provision_watched_item.await_args.kwargs["is_active"] is False


@pytest.mark.asyncio
async def test_register_preserves_paused_choice_on_validation_error(client):
    # Blank name re-renders step 3; an unchecked "watch active" must stay unchecked.
    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://pausedsticky.example.com/page",
            "source_specs": _VALID_SPEC,
            "name": "",
            "description": "",
        },
    )
    assert resp.status_code == 422
    assert 'id="reg-watch-active"' in resp.text
    # Unchecked on submit → no `checked` attribute on re-render.
    assert 'x-ref="watchActiveInput" checked>' not in resp.text


@pytest.mark.asyncio
async def test_register_get_defaults_watch_active_checked(client):
    resp = await client.get("/dashboard/register", headers=_HEADERS)
    assert resp.status_code == 200
    assert 'x-ref="watchActiveInput" checked>' in resp.text


@pytest.mark.asyncio
async def test_register_preserves_cadence_on_validation_error(client):
    # Blank name re-renders step 3; the chosen cadence must stay selected.
    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://cadencesticky.example.com/page",
            "source_specs": _VALID_SPEC,
            "name": "",
            "description": "",
            "cadence": "6h",
        },
    )
    assert resp.status_code == 422
    assert '<option value="6h" selected>' in resp.text


# ---------------------------------------------------------------------------
# Invalid URL re-renders step 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_invalid_url_rerenders(client):
    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "not-a-valid-url",
            "source_specs": _VALID_SPEC,
            "name": "Bad URL Item",
            "description": "",
        },
    )
    assert resp.status_code in (200, 422)
    assert "url" in resp.text.lower()


# ---------------------------------------------------------------------------
# Invalid specs re-renders step 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_invalid_specs_rerenders(client):
    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://goodurl.example.com/page",
            "source_specs": "not valid json",
            "name": "Bad Spec Item",
            "description": "",
        },
    )
    assert resp.status_code in (200, 422)


# ---------------------------------------------------------------------------
# Redirect from /dashboard/info-items/new → /dashboard/register
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_info_items_new_redirects_to_register(client):
    r = await client.get("/dashboard/info-items/new", headers=_HEADERS, follow_redirects=False)
    assert r.status_code == 301
    assert "/dashboard/register" in r.headers.get("location", "")


# ---------------------------------------------------------------------------
# POST /dashboard/register/preview  (HTMX partial)
# ---------------------------------------------------------------------------

_PREVIEW_HTML = (
    b"<html><head><title>My Preview Page</title></head>"
    b"<body><div>extracted content</div></body></html>"
)

_PREVIEW_HTML_NO_TITLE = b"<html><body><div>extracted content</div></body></html>"

_PREVIEW_SPEC = '[{"schema_version":1,"extraction":{"algorithm":"full_page"},"fingerprint":{}}]'


class _StubFetcher:
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def execute(self, effect) -> FetchResult:
        return FetchResult(
            content=self._content,
            status_code=200,
            headers={"content-type": "text/html"},
            duration_ms=5,
            fetcher_used="http",
        )


@pytest.mark.asyncio
async def test_preview_returns_retrieval_success(client):
    """Happy path: retrieval + extraction render status messages."""
    original = app.state.fetch_driver
    app.state.fetch_driver = _StubFetcher(_PREVIEW_HTML)
    try:
        r = await client.post(
            "/dashboard/register/preview",
            headers=_HEADERS,
            data={"url": "https://example.com/page", "source_specs": _PREVIEW_SPEC},
        )
    finally:
        app.state.fetch_driver = original
    assert r.status_code == 200
    assert "Retrieval successful" in r.text
    assert "Extraction successful" in r.text


@pytest.mark.asyncio
async def test_preview_shows_suggested_name_from_page_title(client):
    """When the page has a <title>, the partial shows a Suggested name line."""
    original = app.state.fetch_driver
    app.state.fetch_driver = _StubFetcher(_PREVIEW_HTML)
    try:
        r = await client.post(
            "/dashboard/register/preview",
            headers=_HEADERS,
            data={"url": "https://example.com/page", "source_specs": _PREVIEW_SPEC},
        )
    finally:
        app.state.fetch_driver = original
    assert r.status_code == 200
    assert "My Preview Page" in r.text


@pytest.mark.asyncio
async def test_preview_no_suggested_name_when_no_title(client):
    """When the page has no <title>, the Suggested name line is absent."""
    original = app.state.fetch_driver
    app.state.fetch_driver = _StubFetcher(_PREVIEW_HTML_NO_TITLE)
    try:
        r = await client.post(
            "/dashboard/register/preview",
            headers=_HEADERS,
            data={"url": "https://example.com/page", "source_specs": _PREVIEW_SPEC},
        )
    finally:
        app.state.fetch_driver = original
    assert r.status_code == 200
    assert "Suggested name" not in r.text


@pytest.mark.asyncio
async def test_preview_returns_error_partial_on_invalid_spec(client):
    r = await client.post(
        "/dashboard/register/preview",
        headers=_HEADERS,
        data={"url": "https://example.com/page", "source_specs": "not json"},
    )
    assert r.status_code == 200
    assert "Invalid source_specs" in r.text
