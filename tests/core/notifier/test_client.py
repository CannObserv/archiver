"""The read-only Notifier adapter (archiver#368): it lists channels, and nothing else.

Notifier is respx here, for every test: never the network, never a real key.
The adapter's one call is ``GET /api/v1/channels``. Everything that is not a
channel list (a rejected key, a 5xx, a refused connection, a body that is not
channels) raises ``NotifierUnavailable``, whose text never carries the key.
"""

import logging

import httpx
import pytest

from src.core.notifier.client import (
    Channel,
    Notifier,
    NotifierUnavailable,
    notifier_from_env,
)
from src.core.notifier.gate import (
    API_KEY_ENV,
    BASE_URL_ENV,
    ENABLED_ENV,
    NotifierConfig,
    NotifierNotEnabled,
)

BASE = "http://notifier.test:9001"
KEY = "nk_test-0123456789abcdef"
CHANNELS = f"{BASE}/api/v1/channels"


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


async def test_dormant_is_none_and_says_so(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="src.core.notifier.client"):
        assert notifier_from_env({}) is None
    assert "Notifier not configured" in caplog.text


async def test_configured_names_the_url_and_the_key_source_never_the_key(caplog) -> None:
    environ = {BASE_URL_ENV: BASE, ENABLED_ENV: "1", API_KEY_ENV: KEY}
    with caplog.at_level(logging.INFO, logger="src.core.notifier.client"):
        client = notifier_from_env(environ)
    assert client is not None
    await client.aclose()
    assert f"Notifier configured at {BASE} (key: environment)" in caplog.text
    assert KEY not in caplog.text


async def test_a_refusal_propagates() -> None:
    with pytest.raises(NotifierNotEnabled):
        notifier_from_env({BASE_URL_ENV: BASE})
