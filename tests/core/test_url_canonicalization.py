import pytest

from src.core.url_canonicalization import (
    canonicalize_url,
    is_canonical_hostname,
    source_hostname,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://Example.COM/path#frag", "https://example.com/path"),
        ("HTTPS://example.com/", "https://example.com/"),
        ("https://example.com/path?b=2&a=1", "https://example.com/path?b=2&a=1"),
        ("https://example.com/p%2Fath", "https://example.com/p%2Fath"),
        ("https://example.com//double//slash", "https://example.com/double/slash"),
    ],
)
def test_canonicalize_basic(raw, expected):
    assert canonicalize_url(raw) == expected


def test_strip_query_keys():
    raw = "https://example.com/p?utm_source=x&id=42&utm_medium=y"
    out = canonicalize_url(raw, strip_query_keys=["utm_source", "utm_medium"])
    assert out == "https://example.com/p?id=42"


def test_strip_query_keys_preserves_order():
    raw = "https://example.com/p?b=2&utm_x=z&a=1"
    out = canonicalize_url(raw, strip_query_keys=["utm_x"])
    assert out == "https://example.com/p?b=2&a=1"


def test_invalid_url_raises():
    with pytest.raises(ValueError):
        canonicalize_url("not a url")


# --- The host a source is filed under (archiver#360, CR 22) ---


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://LCB.wa.gov/x", "lcb.wa.gov"),
        ("https://example.com:8080/x", "example.com"),
        ("https://user@example.com/", "example.com"),
    ],
)
def test_source_hostname_is_what_create_info_source_files_a_source_under(url, host):
    assert source_hostname(url) == host


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("lcb.wa.gov", True),
        ("bücher.de", True),
        ("Example.com", False),
        ("example.com:8080", False),
        ("user@example.com", False),
        ("example.com/path", False),
        ("", False),
    ],
)
def test_a_domain_name_is_canonical_only_if_a_source_could_carry_it(name, ok):
    assert is_canonical_hostname(name) is ok
