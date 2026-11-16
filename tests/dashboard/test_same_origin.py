"""The same-origin check on dashboard writes (#404).

Every dashboard write authenticates on the exe.dev login cookie alone, and the
cookie rides a cross-*port* request from this VM (measured on 8001, 2026-11-16:
a form and a ``no-cors`` fetch from ``:8002`` both arrived logged in, with
``Sec-Fetch-Site: same-site``). So the check is same-*origin*, never same-site.

Two layers of test: the pure verdict over header combinations, then the
dependency mounted on real routes through the app.
"""

import logging

import pytest
from starlette.datastructures import URL, Headers

from src.api.deps import get_db_session
from src.api.main import app
from src.dashboard.deps import same_origin_refusal

_ORIGIN = "https://co-registrar.exe.xyz:8001"
# What the exe.dev proxy sent on a dashboard POST on 8001 [measured].
_PROXIED = {
    "host": "co-registrar.exe.xyz:8001",
    "x-forwarded-proto": "https",
    "x-forwarded-host": "co-registrar.exe.xyz:8001",
}
_URL = URL("https://co-registrar.exe.xyz:8001/dashboard/settings/api-keys")


def _verdict(method: str = "POST", url: URL = _URL, **headers: str) -> str | None:
    merged = {**_PROXIED, **{k.replace("_", "-"): v for k, v in headers.items()}}
    return same_origin_refusal(method, Headers(merged), url)


# --- the pure verdict -------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_a_safe_method_is_never_refused(method):
    assert _verdict(method, sec_fetch_site="cross-site", origin="https://evil.example") is None


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_same_origin_write_passes(method):
    assert _verdict(method, sec_fetch_site="same-origin", origin=_ORIGIN) is None


@pytest.mark.parametrize("site", ["same-site", "cross-site", "none"])
def test_any_other_sec_fetch_site_is_refused(site):
    """``same-site`` is the cross-port case; ``none`` a typed or bookmarked request."""
    assert _verdict(sec_fetch_site=site, origin=_ORIGIN) is not None


def test_sec_fetch_site_decides_alone_when_present():
    """The browser sets it from the URL it requested: no origin to reconstruct.

    An ``Origin`` that disagrees with our reconstruction cannot veto it, and one
    that agrees cannot rescue a ``same-site``.
    """
    assert _verdict(sec_fetch_site="same-origin", origin="https://elsewhere.example") is None
    assert _verdict(sec_fetch_site="same-site", origin=_ORIGIN) is not None


def test_sec_fetch_site_is_read_case_insensitively():
    assert _verdict(sec_fetch_site="Same-Origin") is None


def test_without_sec_fetch_site_a_matching_origin_passes():
    assert _verdict(origin=_ORIGIN) is None


@pytest.mark.parametrize(
    "origin",
    [
        "https://co-registrar.exe.xyz:8002",  # another port of this VM
        "https://co-registrar.exe.xyz",  # 8000, the bare hostname
        "http://co-registrar.exe.xyz:8001",  # scheme differs
        "https://other-vm.exe.xyz:8001",  # another exe.dev VM
        "null",  # opaque: sandboxed frame, data: URL
        "not a url",
        "https://co-registrar.exe.xyz:notaport",
        # Not serialized origins, though urlsplit reads ours out of each (CR 3).
        "https://x@co-registrar.exe.xyz:8001",
        "https://co-registrar.exe.xyz:8001?",
        "https://co-registrar.exe.xyz:8001#",
    ],
)
def test_without_sec_fetch_site_any_other_origin_is_refused(origin):
    assert _verdict(origin=origin) is not None


def test_a_request_with_neither_header_passes():
    """Operator decision (2026-11-16): allow; curl, scripts and TestClient send neither.

    A known limit, not a CSRF vector: every browser that carries the cookie
    sends ``Sec-Fetch-Site`` or ``Origin`` on a POST.
    """
    assert _verdict() is None


@pytest.mark.parametrize(
    ("forwarded_host", "origin"),
    [
        ("co-registrar.exe.xyz", "https://co-registrar.exe.xyz"),
        ("co-registrar.exe.xyz:443", "https://co-registrar.exe.xyz"),
        ("co-registrar.exe.xyz", "https://co-registrar.exe.xyz:443"),
        ("CO-Registrar.exe.xyz:8001", "https://co-registrar.exe.xyz:8001"),
    ],
)
def test_default_ports_and_host_case_are_normalized(forwarded_host, origin):
    """The bare hostname maps to 8000: ``Origin`` then carries no port."""
    assert _verdict(x_forwarded_host=forwarded_host, origin=origin) is None


def test_forwarded_headers_win_over_the_request_url():
    """The proxy's ``X-Forwarded-*`` name the origin the browser asked for."""
    inner = URL("http://127.0.0.1:8001/dashboard/register")
    assert _verdict(url=inner, origin=_ORIGIN) is None


def test_without_forwarded_headers_the_request_url_is_ours():
    url = URL("http://test/dashboard/register")
    verdict = same_origin_refusal("POST", Headers({"host": "test", "origin": "http://test"}), url)
    assert verdict is None
    refused = same_origin_refusal(
        "POST", Headers({"host": "test", "origin": "http://test:8002"}), url
    )
    assert refused is not None


def test_only_the_first_forwarded_host_counts():
    """A chained proxy appends; the first entry is the host the client asked for."""
    assert (
        _verdict(x_forwarded_host="co-registrar.exe.xyz:8001, inner:9000", origin=_ORIGIN) is None
    )


def test_a_forwarded_proto_without_a_forwarded_host_falls_back_whole():
    """Never splice our scheme onto a host from somewhere else."""
    url = URL("http://test/dashboard/register")
    headers = Headers({"host": "test", "x-forwarded-proto": "https", "origin": "http://test"})
    assert same_origin_refusal("POST", headers, url) is None


# --- mounted on the app -----------------------------------------------------

# A write that needs nothing in the database: with the guard ahead of auth, a
# pass shows up as the login redirect and a refusal as the 403.
_WRITE = "/dashboard/settings/api-keys"
_PASSED = 307


@pytest.mark.asyncio
async def test_a_cross_port_post_is_refused_with_an_html_403(client, caplog):
    caplog.set_level(logging.WARNING)
    response = await client.post(
        _WRITE,
        data={"label": "x"},
        headers={
            **_PROXIED,
            "origin": "https://co-registrar.exe.xyz:8002",
            "sec-fetch-site": "same-site",
        },
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("text/html")
    assert "same origin" in response.text.lower()

    [record] = [
        r for r in caplog.records if r.getMessage() == "Dashboard write refused: not same-origin"
    ]
    assert record.levelno == logging.WARNING
    assert record.sec_fetch_site == "same-site"
    assert record.origin == "https://co-registrar.exe.xyz:8002"
    assert record.path == _WRITE


@pytest.mark.asyncio
async def test_the_refusal_runs_before_auth_and_the_database(client):
    """Logged-in headers do not help a cross-site write: no session is opened."""

    async def _no_session():
        raise AssertionError("the guard let a refused request reach the database")
        yield  # pragma: no cover

    app.dependency_overrides[get_db_session] = _no_session
    response = await client.post(
        _WRITE,
        data={"label": "x"},
        headers={
            "x-exedev-userid": "ext-404",
            "x-exedev-email": "csrf@example.com",
            "sec-fetch-site": "cross-site",
            "origin": "https://evil.example",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_same_origin_post_reaches_the_route(client):
    response = await client.post(
        _WRITE,
        data={"label": "x"},
        headers={**_PROXIED, "origin": _ORIGIN, "sec-fetch-site": "same-origin"},
    )
    assert response.status_code == _PASSED


@pytest.mark.asyncio
async def test_a_get_is_not_checked(client):
    response = await client.get(
        "/dashboard/", headers={"sec-fetch-site": "cross-site", "origin": "https://evil.example"}
    )
    assert response.status_code == _PASSED


@pytest.mark.asyncio
async def test_a_malformed_host_cannot_pass_as_ours(client):
    """starlette ignores an invalid ``Host`` for ``scope["server"]`` (#420 note).

    With no forwarded headers, the reconstructed origin is then the socket's -
    never the attacker's half of a poisoned authority.
    """
    response = await client.post(
        _WRITE,
        data={"label": "x"},
        headers={"host": "evil.example/x?", "origin": "http://evil.example"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_malformed_host_behind_the_proxy_still_reads_the_forwarded_origin(client):
    response = await client.post(
        _WRITE,
        data={"label": "x"},
        headers={**_PROXIED, "host": "evil.example/x?", "origin": _ORIGIN},
    )
    assert response.status_code == _PASSED
