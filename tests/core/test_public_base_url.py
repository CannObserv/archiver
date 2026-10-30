"""``ARCHIVER_PUBLIC_BASE_URL`` is the origin, and every item link is built from it one way.

archiver#367 Q1 (operator, 2026-10-30): the base is the origin
(``https://co-registrar.exe.xyz``), and the item page is ``/dashboard/info-items/{id}``
under it. The API's ``dashboard_url`` and a notification's links share the rule.
Unset or unusable means no link, never a guessed host.
"""

import pytest

from src.core.public_base_url import PUBLIC_BASE_URL_ENV, item_page_url, public_base_url

ITEM = "01HV0000000000000000000001"


def test_unset_is_none() -> None:
    assert public_base_url({}) is None
    assert public_base_url({PUBLIC_BASE_URL_ENV: "  "}) is None


@pytest.mark.parametrize(
    "value",
    ["https://co-registrar.exe.xyz", "https://co-registrar.exe.xyz/", " http://localhost:8001 "],
)
def test_an_origin_is_kept_without_its_trailing_slash(value: str) -> None:
    assert public_base_url({PUBLIC_BASE_URL_ENV: value}) == value.strip().rstrip("/")


@pytest.mark.parametrize(
    "value",
    [
        "co-registrar.exe.xyz",
        "ftp://co-registrar.exe.xyz",
        "https://co-registrar.exe.xyz/dashboard",
        "https://co-registrar.exe.xyz?x=1",
        "https://user@co-registrar.exe.xyz",
        "https://",
        "https://[co-registrar",
    ],
)
def test_anything_but_an_origin_is_none(value: str) -> None:
    """A path would double up with ``/dashboard``; a bad value must not guess a host."""
    assert public_base_url({PUBLIC_BASE_URL_ENV: value}) is None


def test_the_item_page_is_under_the_dashboard() -> None:
    assert (
        item_page_url("https://co-registrar.exe.xyz", ITEM)
        == f"https://co-registrar.exe.xyz/dashboard/info-items/{ITEM}"
    )
