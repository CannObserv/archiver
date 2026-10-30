"""GET /dashboard/settings/notifier — the read-only Notifier card (archiver#368, D4).

It proves the credential end to end with zero sends: one ``list_channels`` call,
and the tenant's channels (name, type, id) or why there are none. Dormant and
unavailable are 200s with a status (``data-notifier-status``), never an error
page. The key is never on the page; the masked Apprise URL isn't either.
"""

import pytest

from src.api.deps import get_notifier
from src.api.main import app
from src.core.notifier.client import NotifierUnavailable
from tests.core.notifier.fake import DEV_SINK, DEV_SINK_FAILING, FakeNotifier

_HEADERS = {"X-ExeDev-UserID": "ext-notifier", "X-ExeDev-Email": "notifier@example.com"}
_URL = "/dashboard/settings/notifier"


def _use(notifier) -> None:
    app.dependency_overrides[get_notifier] = lambda: notifier


async def test_no_auth_redirects(client) -> None:
    response = await client.get(_URL, follow_redirects=False)
    assert response.status_code == 307


async def test_dormant_says_so_and_calls_nothing(client) -> None:
    _use(None)
    response = await client.get(_URL, headers=_HEADERS)
    assert response.status_code == 200
    assert 'data-notifier-status="dormant"' in response.text
    assert "not configured in this process" in response.text


async def test_lists_the_tenants_channels(client) -> None:
    notifier = FakeNotifier(DEV_SINK, DEV_SINK_FAILING)
    _use(notifier)
    response = await client.get(_URL, headers=_HEADERS)
    assert response.status_code == 200
    assert 'data-notifier-status="ok"' in response.text
    for channel in (DEV_SINK, DEV_SINK_FAILING):
        assert channel.name in response.text
        assert channel.id in response.text
    assert "syslog" in response.text
    assert "http://notifier.test:9001" in response.text
    assert notifier.calls == ["list_channels"]


async def test_a_tenant_with_no_channels(client) -> None:
    _use(FakeNotifier())
    response = await client.get(_URL, headers=_HEADERS)
    assert 'data-notifier-status="ok"' in response.text
    assert "no channels" in response.text


async def test_unavailable_is_a_200_with_the_reason(client) -> None:
    _use(
        FakeNotifier(unavailable=NotifierUnavailable("Notifier rejected archiver's key (HTTP 401)"))
    )
    response = await client.get(_URL, headers=_HEADERS)
    assert response.status_code == 200
    assert 'data-notifier-status="unavailable"' in response.text
    assert "rejected archiver&#39;s key (HTTP 401)" in response.text


async def test_the_page_has_no_send_control(client) -> None:
    """D4: no send, no test send. #367 owns the first send, as an operator action."""
    _use(FakeNotifier(DEV_SINK))
    response = await client.get(_URL, headers=_HEADERS)
    main = response.text.lower().split('id="main-content"', 1)[1]
    for control in ("<form", "<button", "hx-post", "hx-put", "hx-patch", "hx-delete"):
        assert control not in main


async def test_the_sidebar_links_both_settings_pages(client) -> None:
    _use(None)
    response = await client.get(_URL, headers=_HEADERS)
    assert 'href="/dashboard/settings/notifier"' in response.text
    assert 'href="/dashboard/settings/api-keys"' in response.text
    # Only this page's link is current.
    current = [ln for ln in response.text.splitlines() if 'aria-current="page"' in ln]
    assert len(current) == 1


@pytest.mark.parametrize("path", ["/dashboard/settings/api-keys"])
async def test_the_api_keys_link_stays_current_on_its_own_page(client, path) -> None:
    response = await client.get(path, headers=_HEADERS)
    current = [ln for ln in response.text.splitlines() if 'aria-current="page"' in ln]
    assert len(current) == 1
