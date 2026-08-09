"""The content-fingerprint spelling rule.

Mirrors ``src/core/fingerprints.py`` (CR round 2, finding 19). The rule had only
indirect coverage — through HTTP 422 cases and one consumer quarantine case —
which tests the two call sites rather than the rule they share.

Why the rule is strict rather than advisory: Archiver's uniqueness key is
``(info_source_id, content_fingerprint)``, so a fingerprint that differs only in
spelling for identical content inserts a *second* row instead of colliding with
the first. The failure is a silent duplicate, not a rejected write.
"""

import pytest

from src.core.fingerprints import is_valid_fingerprint

VALID = "sha256:" + "a" * 64


def test_canonical_spelling_is_valid():
    assert is_valid_fingerprint(VALID)


def test_all_hex_digits_are_accepted():
    assert is_valid_fingerprint("sha256:" + "0123456789abcdef" * 4)


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("a" * 64, "no algorithm prefix"),
        ("sha256:" + "A" * 64, "uppercase hex — a second spelling of one digest"),
        ("SHA256:" + "a" * 64, "uppercase algorithm prefix"),
        ("sha256:" + "a" * 63, "too short"),
        ("sha256:" + "a" * 65, "too long"),
        ("sha512:" + "a" * 64, "wrong algorithm"),
        ("sha256:" + "g" * 64, "non-hex characters"),
        ("sha256:", "prefix only"),
        ("", "empty"),
        (" sha256:" + "a" * 64, "leading whitespace"),
        ("sha256:" + "a" * 64 + " ", "trailing whitespace"),
        ("sha256:" + "a" * 64 + "\n", "trailing newline — $ alone would accept this"),
    ],
)
def test_rejected_spellings(value, why):
    assert not is_valid_fingerprint(value), why
