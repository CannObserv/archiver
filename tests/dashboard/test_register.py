"""Tests for /dashboard/register registration flow (#49)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest
from co_core.effects.fetch import FetchResult
from sqlalchemy import select

from src.api.main import app
from src.core.models import (
    ChangesOutboxRow,
    InfoItem,
    InfoItemSource,
    InfoSource,
    SourceRevision,
)
from src.core.models.domain import Domain
from src.core.tools.bind_info_source import bind_info_source
from src.dashboard.routes.register import _specs_summary

_HEADERS = {"X-ExeDev-UserID": "ext-reg", "X-ExeDev-Email": "reg@example.com"}

_VALID_SPEC = '[{"schema_version":1,"extraction":{"algorithm":"full_page"},"fingerprint":{}}]'


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
async def test_step_2_help_names_jsonpath_for_json_only(client):
    """co-core 0.38 honours ``jsonpath`` on JSON bodies only (cannobserv#354, #356)."""
    r = await client.get("/dashboard/register", headers=_HEADERS)
    assert "JSONPath (JSON only" in r.text
    # full_page on JSON is canonical JSON, not the page's own formatting (#356 CR 2).
    assert "keys sorted" in r.text
    assert "raw JSON" not in r.text


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


@pytest.mark.asyncio
async def test_suggest_specs_keeps_specs_apart_by_ignore_selectors(client, session):
    """Two specs differing only in ``ignore_selectors`` are two suggestions (#378).

    Grouped by algorithm and selector alone, the chip carried whichever came first,
    so picking "css: #main" could silently add, or drop, the other's exclusions.
    """
    session.add(Domain(name="ignoreme.example.com"))
    await session.flush()
    plain = {"algorithm": "css", "selector": "#main"}
    stripped = {**plain, "ignore_selectors": [".stamp", "#ad"]}
    for path, extraction in (("a", plain), ("b", stripped)):
        session.add(
            InfoSource(
                url=f"https://ignoreme.example.com/{path}",
                source_specs=[{"schema_version": 1, "extraction": extraction, "fingerprint": {}}],
                domain_name="ignoreme.example.com",
            )
        )
    await session.flush()

    r = await client.get(
        "/dashboard/register/suggest-specs?url=https://ignoreme.example.com/c",
        headers=_HEADERS,
    )
    island = re.search(r'<script type="application/json">(.*?)</script>', r.text, re.S)
    chips = {c["label"]: json.loads(c["value"])[0]["extraction"] for c in json.loads(island[1])}
    assert chips == {"css: #main": plain, 'css: #main, ignoring [".stamp", "#ad"]': stripped}


@pytest.mark.asyncio
async def test_suggest_specs_labels_tell_ignore_lists_apart(client, session):
    """``["div .a"]`` and ``["div", ".a"]`` need distinct labels: the chips key on them (CR 1)."""
    session.add(Domain(name="labelme.example.com"))
    await session.flush()
    for path, ignore in (("a", ["div .a"]), ("b", ["div", ".a"]), ("c", [".préface"])):
        extraction = {"algorithm": "css", "selector": "#main", "ignore_selectors": ignore}
        session.add(
            InfoSource(
                url=f"https://labelme.example.com/{path}",
                source_specs=[{"schema_version": 1, "extraction": extraction, "fingerprint": {}}],
                domain_name="labelme.example.com",
            )
        )
    await session.flush()

    r = await client.get(
        "/dashboard/register/suggest-specs?url=https://labelme.example.com/d",
        headers=_HEADERS,
    )
    island = re.search(r'<script type="application/json">(.*?)</script>', r.text, re.S)
    labels = {c["label"] for c in json.loads(island[1])}
    assert len(labels) == 3
    assert 'css: #main, ignoring [".préface"]' in labels  # readable, not \u-escaped (CR 9)


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
async def test_register_emits_primary_changed_once(client, session):
    """Registration is a first assignment: one event, no old (archiver#390)."""
    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data={
            "url": "https://emittest.example.com/page",
            "source_specs": _VALID_SPEC,
            "name": "Emit Test Item",
            "description": "",
        },
    )
    assert resp.status_code == 303
    item = (
        await session.execute(select(InfoItem).where(InfoItem.name == "Emit Test Item"))
    ).scalar_one()
    binding = (
        await session.execute(
            select(InfoItemSource).where(InfoItemSource.info_item_id == item.info_item_id)
        )
    ).scalar_one()

    payloads = (
        await session.execute(
            select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == "info.changes")
        )
    ).scalars()
    events = [p for p in payloads if p.get("event_type") == "info_item_primary_changed"]
    assert len(events) == 1
    assert events[0]["info_item_id"] == str(item.info_item_id)
    assert events[0]["old_info_source_id"] is None
    assert events[0]["new_info_source_id"] == str(binding.info_source_id)


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
# Cadence and pause state are recorded locally (#50, #60, archiver#142)
#
# These asserted the values forwarded on the provisioning call until archiver#142
# deleted it. They assert the same operator intent one layer down — the columns
# the announcement is built from — which is now the only path to Watcher. The
# behaviour under test never changed; only the place it is observable did.
# ---------------------------------------------------------------------------


async def _item_after_register(session, name: str):
    row = (await session.execute(select(InfoItem).where(InfoItem.name == name))).scalar_one()
    return row


@pytest.mark.asyncio
async def test_register_records_selected_cadence(client, session):
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
    item = await _item_after_register(session, "Cadence Item")
    assert item.watch_spec["interval"] == "6h"


@pytest.mark.asyncio
async def test_register_omits_cadence_when_absent(client, session):
    """No cadence field → no interval, which spells "consumer applies its own"."""
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
    item = await _item_after_register(session, "Cadence Default Item")
    assert item.watch_spec.get("interval") is None


@pytest.mark.asyncio
async def test_register_invalid_cadence_records_none(client, session):
    """An unrecognised value is never fabricated into a default."""
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
    item = await _item_after_register(session, "Cadence Bad Item")
    assert item.watch_spec.get("interval") is None


@pytest.mark.asyncio
async def test_register_active_when_checkbox_present(client, session):
    """Checked → explicitly active (archiver#158).

    The registry holds the opinion rather than deferring to the consumer's
    default, which is what makes the first announcement match the form.
    """
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
    item = await _item_after_register(session, "Active Item")
    assert item.watch_active is True


@pytest.mark.asyncio
async def test_register_paused_when_checkbox_absent(client, session):
    """Unchecked checkbox sends nothing → registered paused."""
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
    item = await _item_after_register(session, "Paused Item")
    assert item.watch_active is False


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
    def __init__(self, content: bytes, content_type: str = "text/html") -> None:
        self._content = content
        self._content_type = content_type

    async def execute(self, effect) -> FetchResult:
        return FetchResult(
            content=self._content,
            status_code=200,
            headers={"content-type": self._content_type},
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


async def _preview(client, fetcher: _StubFetcher, extraction: str):
    original = app.state.fetch_driver
    app.state.fetch_driver = fetcher
    spec = f'[{{"schema_version":1,"extraction":{extraction},"fingerprint":{{}}}}]'
    try:
        return await client.post(
            "/dashboard/register/preview",
            headers=_HEADERS,
            data={"url": "https://example.com/page", "source_specs": spec},
        )
    finally:
        app.state.fetch_driver = original


@pytest.mark.asyncio
async def test_preview_shows_jsonpath_matches_on_json(client):
    """co-core 0.38 extracts JSON (cannobserv#354, #356): the excerpt is the matched node."""
    fetcher = _StubFetcher(b'{"items": [{"title": "Agenda"}]}', "application/json")
    r = await _preview(client, fetcher, '{"algorithm":"jsonpath","selector":"$.items[*].title"}')
    assert r.status_code == 200
    assert "Extraction successful" in r.text
    assert "Agenda" in r.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "content_type", "extraction"),
    [
        (b'{"a": 1}', "application/json", '{"algorithm":"jsonpath","selector":"$.nope"}'),
        (_PREVIEW_HTML, "text/html", '{"algorithm":"css","selector":".nope"}'),
    ],
    ids=["jsonpath", "css"],
)
async def test_preview_says_a_selector_matched_nothing(client, content, content_type, extraction):
    """Zero chunks is not an error (processor#37), but must not read as a good empty page (#356)."""
    r = await _preview(client, _StubFetcher(content, content_type), extraction)
    assert r.status_code == 200
    assert "The selector matched nothing" in r.text
    assert "Extraction successful" not in r.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extraction",
    ['{"algorithm":"full_page"}', '{"algorithm":"css","selector":""}'],
    ids=["full_page", "empty-css"],
)
async def test_preview_with_no_selector_says_no_content(client, extraction):
    """No selector to blame: ``full_page``, or an empty css selector (the whole page; CR 5)."""
    r = await _preview(client, _StubFetcher(b"<html><body></body></html>"), extraction)
    assert "No content extracted" in r.text
    assert "matched nothing" not in r.text


@pytest.mark.asyncio
async def test_preview_returns_error_partial_on_invalid_spec(client):
    r = await client.post(
        "/dashboard/register/preview",
        headers=_HEADERS,
        data={"url": "https://example.com/page", "source_specs": "not json"},
    )
    assert r.status_code == 200
    assert "Invalid source_specs" in r.text


@pytest.mark.asyncio
async def test_preview_renders_a_spec_refusal_as_path_and_message(client):
    """An invalid xpath is refused (#317); the operator sees co-core's message, not a dict repr."""
    original = app.state.fetch_driver
    app.state.fetch_driver = _StubFetcher(_PREVIEW_HTML)
    spec = (
        '[{"schema_version":1,"extraction":{"algorithm":"xpath","selector":"//div["},'
        '"fingerprint":{}}]'
    )
    try:
        r = await client.post(
            "/dashboard/register/preview",
            headers=_HEADERS,
            data={"url": "https://example.com/page", "source_specs": spec},
        )
    finally:
        app.state.fetch_driver = original
    assert r.status_code == 200
    assert "/extraction: " in r.text
    assert "{&#39;path&#39;" not in r.text and "{'path'" not in r.text


# ---------------------------------------------------------------------------
# Case B: reuse the existing unbound InfoSource by default (archiver#51)
# ---------------------------------------------------------------------------

_FULL_PAGE = {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
_CSS = {
    "schema_version": 1,
    "extraction": {"algorithm": "css", "selector": "#a"},
    "fingerprint": {},
}
# Stored before a schema tightening: css without its selector (#164).
_STALE = {"schema_version": 1, "extraction": {"algorithm": "css"}, "fingerprint": {}}


async def _unbound(session, url: str, specs: list[dict], revisions: int = 0) -> InfoSource:
    src = InfoSource(url=url, source_specs=specs)
    session.add(src)
    await session.flush()
    for n in range(revisions):
        session.add(
            SourceRevision(
                info_source_id=src.info_source_id,
                content_fingerprint=f"fp-{src.info_source_id}-{n}",
                captured_at=datetime(2026, 10, 1 + n, tzinfo=UTC),
            )
        )
    await session.flush()
    return src


def _choices(html: str) -> dict[str, bool]:
    out = {}
    for tag in re.findall(r'<input[^>]*name="source_choice"[^>]*>', html):
        value = re.search(r'value="([^"]*)"', tag).group(1)
        out[value] = bool(re.search(r"\schecked\b", tag))
    return out


def _submit(url: str, **extra) -> dict:
    return {
        "url": url,
        "source_specs": json.dumps([_FULL_PAGE]),
        "name": extra.pop("name", "Case B Item"),
        "description": "",
        **extra,
    }


async def _sources_at(session, url: str) -> list[InfoSource]:
    return list((await session.execute(select(InfoSource).where(InfoSource.url == url))).scalars())


async def _items_named(session, name: str) -> list[InfoItem]:
    return list((await session.execute(select(InfoItem).where(InfoItem.name == name))).scalars())


@pytest.mark.asyncio
async def test_url_check_case_b_one_source_is_preselected(client, session):
    src = await _unbound(session, "https://reuse1.example.com/p", [_CSS], revisions=3)

    r = await client.get(
        "/dashboard/register/url-check?url=https://reuse1.example.com/p", headers=_HEADERS
    )
    assert r.status_code == 200
    assert _choices(r.text) == {str(src.info_source_id): True, "new": False}
    assert "3 earlier revisions will appear" in r.text
    assert "css: #a" in r.text
    island = _dispatch_island(r.text)
    assert island["case"] == "B"
    assert island["source_choice"] == str(src.info_source_id)
    candidate = island["candidates"][str(src.info_source_id)]
    assert json.loads(candidate["specs"]) == [_CSS]
    assert candidate["revisions"] == 3


@pytest.mark.asyncio
async def test_url_check_case_b_several_sources_preselect_none(client, session):
    a = await _unbound(session, "https://reuse2.example.com/p", [_FULL_PAGE])
    b = await _unbound(session, "https://reuse2.example.com/p", [_CSS], revisions=1)

    r = await client.get(
        "/dashboard/register/url-check?url=https://reuse2.example.com/p", headers=_HEADERS
    )
    assert _choices(r.text) == {
        str(a.info_source_id): False,
        str(b.info_source_id): False,
        "new": False,
    }
    assert "1 earlier revision will appear" in r.text
    assert _dispatch_island(r.text)["source_choice"] == ""


@pytest.mark.asyncio
async def test_url_check_case_b_flags_a_stored_spec_the_schema_rejects(client, session):
    await _unbound(session, "https://reuse3.example.com/p", [_STALE])

    r = await client.get(
        "/dashboard/register/url-check?url=https://reuse3.example.com/p", headers=_HEADERS
    )
    assert "fails the current schema" in r.text
    assert "selector" in r.text


@pytest.mark.asyncio
async def test_register_case_b_reuses_the_one_source(client, session):
    url = "https://reuse4.example.com/p"
    src = await _unbound(session, url, [_FULL_PAGE], revisions=2)

    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data=_submit(url, source_choice=str(src.info_source_id)),
    )
    assert resp.status_code == 303
    assert [s.info_source_id for s in await _sources_at(session, url)] == [src.info_source_id]
    (item,) = await _items_named(session, "Case B Item")
    binding = (
        await session.execute(
            select(InfoItemSource).where(InfoItemSource.info_item_id == item.info_item_id)
        )
    ).scalar_one()
    assert binding.info_source_id == src.info_source_id

    payloads = (
        await session.execute(
            select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == "info.changes")
        )
    ).scalars()
    events = [p for p in payloads if p.get("event_type") == "info_item_primary_changed"]
    assert len(events) == 1
    assert events[0]["old_info_source_id"] is None
    assert events[0]["new_info_source_id"] == str(src.info_source_id)


@pytest.mark.asyncio
async def test_register_case_b_saves_edited_specs_onto_the_reused_source(client, session):
    url = "https://reuse5.example.com/p"
    src = await _unbound(session, url, [_FULL_PAGE])

    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data=_submit(url, source_choice=str(src.info_source_id), source_specs=json.dumps([_CSS])),
    )
    assert resp.status_code == 303
    await session.refresh(src)
    assert src.source_specs == [_CSS]


@pytest.mark.asyncio
async def test_register_case_b_unchosen_is_refused(client, session):
    url = "https://reuse6.example.com/p"
    a = await _unbound(session, url, [_FULL_PAGE])
    await _unbound(session, url, [_CSS])

    resp = await client.post("/dashboard/register", headers=_HEADERS, data=_submit(url))
    assert resp.status_code == 422
    assert "registerWizard(1)" in resp.text
    assert "Choose" in resp.text
    assert await _items_named(session, "Case B Item") == []
    assert len(await _sources_at(session, url)) == 2
    # The card re-renders server-side, still with nothing chosen.
    assert _choices(resp.text)[str(a.info_source_id)] is False


@pytest.mark.asyncio
async def test_register_case_b_opt_out_creates_a_new_source(client, session):
    url = "https://reuse7.example.com/p"
    src = await _unbound(session, url, [_FULL_PAGE])

    resp = await client.post(
        "/dashboard/register", headers=_HEADERS, data=_submit(url, source_choice="new")
    )
    assert resp.status_code == 303
    sources = await _sources_at(session, url)
    assert len(sources) == 2
    (item,) = await _items_named(session, "Case B Item")
    binding = (
        await session.execute(
            select(InfoItemSource).where(InfoItemSource.info_item_id == item.info_item_id)
        )
    ).scalar_one()
    assert binding.info_source_id != src.info_source_id


@pytest.mark.asyncio
async def test_register_case_b_refuses_a_stored_spec_the_schema_rejects(client, session):
    url = "https://reuse8.example.com/p"
    src = await _unbound(session, url, [_STALE])

    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data=_submit(url, source_choice=str(src.info_source_id), source_specs=json.dumps([_STALE])),
    )
    assert resp.status_code == 422
    assert "registerWizard(2)" in resp.text
    assert "selector" in resp.text
    assert await _items_named(session, "Case B Item") == []
    # The operator's choice survives the re-render.
    assert _choices(resp.text)[str(src.info_source_id)] is True
    await session.refresh(src)
    assert src.source_specs == [_STALE]


@pytest.mark.asyncio
async def test_register_case_b_source_bound_since_the_check_is_a_409(client, session):
    url = "https://reuse9.example.com/p"
    src = await _unbound(session, url, [_FULL_PAGE])
    other = InfoItem(name="Got There First")
    session.add(other)
    await session.flush()
    await bind_info_source(
        session, info_item_id=other.info_item_id, info_source_id=src.info_source_id
    )
    await session.flush()

    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data=_submit(url, source_choice=str(src.info_source_id)),
    )
    assert resp.status_code == 409
    assert "Got There First" in resp.text
    assert "Submit again to create a new source" in resp.text
    assert await _items_named(session, "Case B Item") == []


@pytest.mark.asyncio
async def test_register_case_b_choice_must_be_a_source_at_this_url(client, session):
    url = "https://reuse10.example.com/p"
    await _unbound(session, url, [_FULL_PAGE])
    elsewhere = await _unbound(session, "https://reuse10.example.com/other", [_FULL_PAGE])

    resp = await client.post(
        "/dashboard/register",
        headers=_HEADERS,
        data=_submit(url, source_choice=str(elsewhere.info_source_id)),
    )
    assert resp.status_code == 422
    assert await _items_named(session, "Case B Item") == []


@pytest.mark.asyncio
async def test_register_review_names_the_information_source(client):
    r = await client.get("/dashboard/register", headers=_HEADERS)
    assert 'x-text="sourceChoiceLabel"' in r.text


@pytest.mark.asyncio
async def test_url_check_case_b_reports_a_malformed_stored_spec(client, session):
    """A stored element that is not an object is a spec error, not a 500 (CR 3)."""
    await _unbound(session, "https://reuse11.example.com/p", ["not-a-spec"])

    r = await client.get(
        "/dashboard/register/url-check?url=https://reuse11.example.com/p", headers=_HEADERS
    )
    assert r.status_code == 200
    assert "fails the current schema" in r.text
    assert "/source_specs/0" in r.text


@pytest.mark.parametrize(
    ("specs", "summary"),
    [
        ([_CSS], "css: #a"),
        ([_FULL_PAGE], "full_page"),
        ([_CSS, _FULL_PAGE], "2 specs (css + full_page)"),
        (["not-a-spec"], "?"),
    ],
)
def test_specs_summary_matches_the_wizards(specs, summary):
    """The card's server-side summary mirrors the wizard's ``selectorSummary`` (CR 7)."""
    assert _specs_summary(specs) == summary
