"""Cadence resolution: profile, then item, then domain (archiver#364, design C-e).

Pure: transient ``InfoItem``/``Domain`` objects, no database.
"""

import logging

import pytest

from src.core.models import InfoItem
from src.core.models.domain import Domain
from src.core.services.cadence_resolution import (
    ResolvedInterval,
    domain_interval,
    item_interval,
    resolve_interval,
)
from src.core.watch_spec_schema.validator import validate_watch_spec


def _item(watch_spec) -> InfoItem:
    return InfoItem(name="i", watch_spec=watch_spec)


def _domain(spec) -> Domain:
    return Domain(name="host.example.test", default_watch_spec=spec)


SIX_HOURS = {"schema_version": 1, "interval": "6h"}


@pytest.mark.parametrize(
    ("item_spec", "domain", "expected"),
    [
        ({"schema_version": 1, "interval": "1h"}, _domain(SIX_HOURS), ("1h", "item")),
        ({"schema_version": 1}, _domain(SIX_HOURS), ("6h", "domain")),
        ({"schema_version": 1}, _domain(None), (None, None)),
        ({"schema_version": 1}, None, (None, None)),
        ({"schema_version": 1, "interval": "1h"}, None, ("1h", "item")),
    ],
)
def test_the_item_tier_wins_then_the_domain_then_nothing(item_spec, domain, expected):
    resolved = resolve_interval(profile=None, item=_item(item_spec), domain=domain)

    assert (resolved.interval, resolved.tier) == expected


@pytest.mark.parametrize(
    "resolved",
    [
        ResolvedInterval("6h", "domain"),
        ResolvedInterval("1h", "item"),
        ResolvedInterval(None, None),
    ],
)
def test_the_announced_document_is_always_watch_spec_v1(resolved):
    doc = resolved.watch_spec()

    assert validate_watch_spec(doc) == (True, [])
    assert doc.get("interval") == resolved.interval


def test_no_tier_announces_no_interval_so_the_consumer_default_applies():
    assert ResolvedInterval(None, None).watch_spec() == {"schema_version": 1}


@pytest.mark.parametrize(
    "spec",
    [
        "6h",  # not an object (CR 18 of #360)
        {"interval": "6h"},  # Watcher's shape, no schema_version
        {"schema_version": 1, "interval": "six hours"},
        {"schema_version": 1},  # no interval: says nothing a NULL does not
    ],
)
def test_a_malformed_domain_default_is_skipped_and_named(spec, caplog):
    domain = Domain(name="bad.example.test", default_watch_spec=spec)

    with caplog.at_level(logging.WARNING):
        resolved = resolve_interval(profile=None, item=_item({"schema_version": 1}), domain=domain)

    assert resolved == ResolvedInterval(None, None)
    assert [getattr(r, "domain", None) for r in caplog.records] == ["bad.example.test"]


@pytest.mark.parametrize(
    "spec",
    [
        None,
        ["1h"],
        {"schema_version": 1, "interval": 6},
        {"schema_version": 1, "interval": "1h", "active": False},
    ],
)
def test_a_malformed_item_document_falls_through_to_the_domain(spec, caplog):
    item = _item(spec)

    with caplog.at_level(logging.WARNING):
        resolved = resolve_interval(profile=None, item=item, domain=_domain(SIX_HOURS))

    assert resolved == ResolvedInterval("6h", "domain")
    assert "malformed" in caplog.text


def test_an_item_document_without_an_interval_is_not_malformed(caplog):
    with caplog.at_level(logging.WARNING):
        assert item_interval({"schema_version": 1}, info_item_id="x") is None

    assert caplog.text == ""


def test_no_domain_row_and_a_null_default_are_both_no_tier(caplog):
    with caplog.at_level(logging.WARNING):
        assert domain_interval(None) is None
        assert domain_interval(_domain(None)) is None

    assert caplog.text == ""
