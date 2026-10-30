"""The Notifier adapter (archiver#368, #367): it lists channels and makes one kind of dispatch.

Notifier is respx here, for every test: never the network, never a real key.
The adapter's calls are ``GET /api/v1/channels`` and, since #367,
``POST /api/v1/dispatch`` through ``dispatch_composed`` alone. Everything that
is not the answer asked for (a rejected key, a 5xx, a refused connection, a
body that is not channels) raises ``NotifierUnavailable``, whose text never
carries the key.
"""

import json
import logging

import httpx
import jinja2
import pytest

from src.core.notifier.client import (
    Channel,
    Dispatched,
    Notifier,
    NotifierUnavailable,
    announce,
)
from src.core.notifier.gate import NotifierConfig

BASE = "http://notifier.test:9001"
KEY = "nk_test-0123456789abcdef"
CHANNELS = f"{BASE}/api/v1/channels"
DISPATCH = f"{BASE}/api/v1/dispatch"
CHANNEL_ID = "01M5APS9R7A0QEDB9522MRA4CT"


def _channel(cid: str, name: str, masked: str, **extra) -> dict:
    return {
        "id": cid,
        "name": name,
        "tenant_id": "01M5APS4GQBN671G050RD82Y44",
        "apprise_url_masked": masked,
        "channel_hint": None,
        "created_at": "2026-10-19T00:00:00Z",
        "updated_at": "2026-10-19T00:00:00Z",
        **extra,
    }


@pytest.fixture
async def notifier():
    client = Notifier(NotifierConfig(base_url=BASE, api_key=KEY, key_source="environment"))
    yield client
    await client.aclose()


async def test_lists_the_tenants_channels_by_name(respx_mock, notifier) -> None:
    route = respx_mock.get(CHANNELS).mock(
        return_value=httpx.Response(
            200,
            json=[
                _channel("01M5APS9R7A0QEDB9522MRA4CV", "dev-sink-failing", "sink://***"),
                _channel("01M5APS9R7A0QEDB9522MRA4CT", "dev-sink", "syslog://***"),
            ],
        )
    )
    channels = await notifier.list_channels()
    assert channels == [
        Channel(id="01M5APS9R7A0QEDB9522MRA4CT", name="dev-sink", kind="syslog"),
        Channel(id="01M5APS9R7A0QEDB9522MRA4CV", name="dev-sink-failing", kind="sink"),
    ]
    assert route.calls.last.request.headers["X-API-Key"] == KEY


@pytest.mark.parametrize(
    ("masked", "kind"),
    [("slack://***", "slack"), ("mailgun://***", "mailgun"), ("***", "unknown"), ("", "unknown")],
)
async def test_the_kind_is_the_masked_urls_scheme(respx_mock, notifier, masked, kind) -> None:
    respx_mock.get(CHANNELS).mock(
        return_value=httpx.Response(200, json=[_channel("01A", "c", masked)])
    )
    (channel,) = await notifier.list_channels()
    assert channel.kind == kind


async def test_the_masked_url_itself_is_not_kept(respx_mock, notifier) -> None:
    respx_mock.get(CHANNELS).mock(
        return_value=httpx.Response(200, json=[_channel("01A", "c", "slack://T0***")])
    )
    (channel,) = await notifier.list_channels()
    assert "T0" not in repr(channel)


@pytest.mark.parametrize("status", [401, 403])
async def test_a_rejected_key_is_unavailable(respx_mock, notifier, status, caplog) -> None:
    respx_mock.get(CHANNELS).mock(
        return_value=httpx.Response(status, json={"detail": "Invalid API key"})
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(NotifierUnavailable) as excinfo:
        await notifier.list_channels()
    assert str(excinfo.value) == f"Notifier rejected archiver's key (HTTP {status})"
    assert KEY not in caplog.text


async def test_a_server_error_is_one_attempt_then_unavailable(respx_mock, notifier) -> None:
    """One attempt: an operator reloads the page. Retrying is the dispatch path's
    concern (archiver#369), not a person waiting on Settings."""
    route = respx_mock.get(CHANNELS).mock(return_value=httpx.Response(503))
    with pytest.raises(NotifierUnavailable, match="HTTP 503"):
        await notifier.list_channels()
    assert route.call_count == 1


async def test_a_transport_error_is_unavailable_by_type(respx_mock, notifier) -> None:
    respx_mock.get(CHANNELS).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(NotifierUnavailable, match="ConnectError"):
        await notifier.list_channels()


@pytest.mark.parametrize("body", [{"not": "a list"}, [{"id": "only"}], "text"])
async def test_a_body_that_is_not_channels_is_unavailable(respx_mock, notifier, body) -> None:
    respx_mock.get(CHANNELS).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(NotifierUnavailable, match="unreadable"):
        await notifier.list_channels()


async def test_no_message_names_the_key(respx_mock, notifier) -> None:
    respx_mock.get(CHANNELS).mock(
        return_value=httpx.Response(401, json={"detail": f"bad key {KEY}"})
    )
    with pytest.raises(NotifierUnavailable) as excinfo:
        await notifier.list_channels()
    assert KEY not in str(excinfo.value)


async def test_the_client_never_shows_its_key(notifier) -> None:
    assert KEY not in repr(notifier)
    assert notifier.base_url == BASE
    assert notifier.key_source == "environment"


def test_dormant_says_so(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="src.core.notifier.client"):
        announce(None)
    assert "Notifier not configured" in caplog.text


def test_configured_names_the_url_and_the_key_source_never_the_key(caplog) -> None:
    config = NotifierConfig(base_url=BASE, api_key=KEY, key_source="environment")
    with caplog.at_level(logging.INFO, logger="src.core.notifier.client"):
        announce(config)
    assert f"Notifier configured at {BASE} (key: environment)" in caplog.text
    assert KEY not in caplog.text


# --- dispatch_composed (archiver#367, D3) ------------------------------------


def _dispatch_out(status: str = "succeeded", **extra) -> dict:
    return {
        "id": "01M5DISPATCH0000000000000A",
        "tenant_id": "01M5APS4GQBN671G050RD82Y44",
        "template_id": None,
        "idempotency_key": "archiver:test:x:y",
        "metadata": {"test": True},
        "rendered_title": "t",
        "rendered_body": "b",
        "status": status,
        "attempts": [],
        "created_at": "2026-10-30T00:00:00Z",
        **extra,
    }


async def _dispatch(notifier, **overrides) -> Dispatched:
    kwargs = {
        "channel_id": CHANNEL_ID,
        "title": "[Test] title",
        "body": "body",
        "idempotency_key": "archiver:test:x:y",
        "metadata": {"test": True},
    } | overrides
    return await notifier.dispatch_composed(**kwargs)


async def test_composed_text_reaches_notifier_as_variables_never_as_the_template(
    respx_mock, notifier
) -> None:
    """D3: Notifier renders both ``*_template`` fields as Jinja, so text holding
    ``{{`` or ``{%`` (a watched page's diff can) must travel as a variable."""
    route = respx_mock.post(DISPATCH).mock(return_value=httpx.Response(201, json=_dispatch_out()))
    title = "[Test] {{ x }}"
    body = "a page said {{ x }} and {% if %} and {#"
    await _dispatch(notifier, title=title, body=body)
    sent = json.loads(route.calls.last.request.content)
    assert sent["title_template"] == "{{ title }}"
    assert sent["body_template"] == "{{ body }}"
    assert sent["variables"] == {"title": title, "body": body}
    assert sent["channel_ids"] == [CHANNEL_ID]
    assert sent["idempotency_key"] == "archiver:test:x:y"
    assert sent["metadata"] == {"test": True}
    assert "template_id" not in sent


async def test_the_variables_render_back_to_the_text_under_notifiers_rules() -> None:
    """Notifier's renderer (notifier 2450bc8 render.py): StrictUndefined, no escaping."""
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)
    text = "{{ x }} {% if %} <b>&amp;</b>\n\n```diff\n+ y\n```"
    assert env.from_string("{{ body }}").render(body=text) == text


async def test_a_dispatch_returns_its_id_and_status(respx_mock, notifier) -> None:
    respx_mock.post(DISPATCH).mock(return_value=httpx.Response(201, json=_dispatch_out("failed")))
    assert await _dispatch(notifier) == Dispatched(id="01M5DISPATCH0000000000000A", status="failed")


async def test_a_dispatch_is_one_attempt(respx_mock, notifier) -> None:
    route = respx_mock.post(DISPATCH).mock(return_value=httpx.Response(503))
    with pytest.raises(NotifierUnavailable, match="HTTP 503"):
        await _dispatch(notifier)
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "Notifier rejected archiver's key (HTTP 401)"),
        (404, "Notifier has no such channel in this tenant (HTTP 404)"),
        (422, "Notifier refused the dispatch (HTTP 422)"),
    ],
)
async def test_a_refused_dispatch_says_why(respx_mock, notifier, status, message) -> None:
    respx_mock.post(DISPATCH).mock(
        return_value=httpx.Response(status, json={"detail": f"no {KEY}"})
    )
    with pytest.raises(NotifierUnavailable) as excinfo:
        await _dispatch(notifier)
    assert str(excinfo.value) == message


async def test_a_dispatch_transport_error_is_unavailable_by_type(respx_mock, notifier) -> None:
    respx_mock.post(DISPATCH).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(NotifierUnavailable, match="ReadTimeout"):
        await _dispatch(notifier)
