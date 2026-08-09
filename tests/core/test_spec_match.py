"""Comparing an observed ``spec_fingerprint`` against the registry's specs.

archiver#139 settled **record and flag, never reject**, and could only ship the
recording half: co-core constrained the value to be *stable for a given spec*
without saying how it was derived, so Archiver held the authoritative
`source_specs` with no way to produce the same string Watcher had. cannobserv#309
supplies the derivation, and this module is the flag half.

Everything here is about **not** flagging when we cannot compare. A false
mismatch on a perfectly current spec is indistinguishable from the real
condition the field exists to detect, so every uncertain branch resolves to
`incomparable` rather than to `superseded`.
"""

import pytest
from co_core.pure.extract import spec_fingerprint

from src.core.spec_match import (
    INCOMPARABLE,
    SUPERSEDED,
    SpecComparison,
    compare_spec_fingerprint,
)

PRIMARY = {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
FALLBACK = {
    "schema_version": 1,
    "extraction": {"algorithm": "css", "selector": "#main"},
    "fingerprint": {},
}
SPECS = [PRIMARY, FALLBACK]


def test_no_observed_fingerprint_is_not_a_mismatch():
    """The field is optional; absence means the producer had no identity to report.

    Including a producer that has not adopted it yet — flagging that would fire
    on every revision during the rollout.
    """
    assert compare_spec_fingerprint(None, SPECS) == SpecComparison(match=None, position=None)


def test_primary_spec_matches_at_position_zero():
    result = compare_spec_fingerprint(spec_fingerprint(PRIMARY), SPECS)

    assert result == SpecComparison(match="current", position=0)


def test_fallback_spec_matches_at_its_position():
    """Position is the actionable half: extraction under spec[1] is selector rot.

    The primary selector stopped matching and Watcher's fallback loop moved on —
    visible here before anyone notices the content is coming from elsewhere.
    """
    result = compare_spec_fingerprint(spec_fingerprint(FALLBACK), SPECS)

    assert result == SpecComparison(match="current", position=1)


def test_spec_the_registry_no_longer_holds_is_the_flag():
    retired = {"schema_version": 1, "extraction": {"algorithm": "css", "selector": ".gone"}}

    result = compare_spec_fingerprint(spec_fingerprint(retired), SPECS)

    assert result == SpecComparison(match=SUPERSEDED, position=None)


def test_duplicate_specs_report_the_first_position():
    """A source_specs list may legitimately repeat a spec — one fingerprint, two indices."""
    result = compare_spec_fingerprint(spec_fingerprint(PRIMARY), [PRIMARY, FALLBACK, PRIMARY])

    assert result == SpecComparison(match="current", position=0)


def test_unknown_derivation_tag_is_incomparable_never_a_flag():
    """A tag this co-core cannot compute must skip, not flag (cannobserv#309, rule 2)."""
    result = compare_spec_fingerprint("spec99:sha256:" + "a" * 64, SPECS)

    assert result == SpecComparison(match=INCOMPARABLE, position=None)


@pytest.mark.parametrize(
    "value", ["garbage", "", "sha256:" + "a" * 64, "spec1:" + "a" * 64, "spec1:sha256:zzz"]
)
def test_malformed_fingerprints_are_incomparable(value):
    """Malformed is a producer bug, not evidence the spec changed."""
    result = compare_spec_fingerprint(value, SPECS)

    assert result == SpecComparison(match=INCOMPARABLE, position=None)


def test_unfingerprintable_registry_specs_are_incomparable():
    """One bad spec aborts co-core's index — that is a registry problem, not a mismatch.

    The index is all-or-nothing by design: a partial index turns a spec the
    registry *does* hold into a miss, which is the false flag by another route.
    """
    broken = [{"schema_version": 1, "extraction": {"threshold": float("nan")}}]

    result = compare_spec_fingerprint(spec_fingerprint(PRIMARY), broken)

    assert result == SpecComparison(match=INCOMPARABLE, position=None)


def test_empty_specs_list_is_superseded_not_incomparable():
    """An empty index is a computable answer: nothing the registry holds matches."""
    result = compare_spec_fingerprint(spec_fingerprint(PRIMARY), [])

    assert result == SpecComparison(match=SUPERSEDED, position=None)


def test_comparison_reports_whether_the_fallback_moved():
    """`is_fallback` is the selector-rot predicate the position exists to answer."""
    assert compare_spec_fingerprint(spec_fingerprint(PRIMARY), SPECS).is_fallback is False
    assert compare_spec_fingerprint(spec_fingerprint(FALLBACK), SPECS).is_fallback is True
    assert compare_spec_fingerprint(None, SPECS).is_fallback is False
    assert compare_spec_fingerprint("garbage", SPECS).is_fallback is False
