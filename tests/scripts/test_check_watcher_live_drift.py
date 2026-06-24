"""Tests for ``scripts/check_watcher_live_drift.py`` (Layer C, #70).

This detector fetches Watcher's LIVE ``/openapi.json`` and byte-compares it
against the committed ``watcher-openapi.json`` snapshot to catch the snapshot
itself going stale vs upstream — the #66 failure mode the hermetic #68 gate
cannot see. The load-bearing invariant is that its ``canonicalize`` mirrors
``regen.sh`` exactly, so the committed snapshot is a fixed point and a
byte-compare is meaningful. The network fetch is stubbed here; ``canonicalize``
is exercised against the real committed snapshot.
"""

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check_watcher_live_drift.py"
_SNAPSHOT = _REPO_ROOT / "clients" / "watcher-python" / "watcher-openapi.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_watcher_live_drift", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


# --- canonicalize: parity with regen.sh is the whole game ---------------------


def test_canonicalize_is_a_fixed_point_of_the_committed_snapshot():
    """Round-tripping the committed snapshot must be a no-op.

    regen.sh writes the snapshot as ``json.dumps(indent=2) + "\\n"``; if this
    detector canonicalizes any differently it would report perpetual false
    drift. Pinning against the real committed bytes guarantees parity.
    """
    committed = _SNAPSHOT.read_bytes()
    assert mod.canonicalize(committed) == committed


def test_canonicalize_pretty_prints_with_trailing_newline():
    out = mod.canonicalize(b'{"a":1}')
    assert out == b'{\n  "a": 1\n}\n'


def test_canonicalize_preserves_key_order_not_sorted():
    # Sorting would reshape the generated tree (model field order follows spec
    # property order), so order MUST be preserved.
    out = mod.canonicalize(b'{"b": 1, "a": 2}')
    assert out.index(b'"b"') < out.index(b'"a"')


def test_canonicalize_raises_on_invalid_json():
    with pytest.raises(mod.SpecFetchError):
        mod.canonicalize(b"not json{")


# --- detect_drift / spec_sha256 ----------------------------------------------


def test_detect_drift_false_when_live_canonicalizes_to_committed():
    committed = _SNAPSHOT.read_bytes()
    # Live served compactly but semantically identical -> no drift after canon.
    compact = json.dumps(json.loads(committed), separators=(",", ":")).encode()
    assert mod.detect_drift(committed, compact) is False


def test_detect_drift_true_when_upstream_shape_changes():
    committed = _SNAPSHOT.read_bytes()
    doc = json.loads(committed)
    doc["info"]["version"] = "9.9.9-changed"
    assert mod.detect_drift(committed, json.dumps(doc).encode()) is True


def test_spec_sha256_is_hash_of_canonical_form():
    committed = _SNAPSHOT.read_bytes()
    compact = json.dumps(json.loads(committed), separators=(",", ":")).encode()
    # Same canonical bytes -> same hash regardless of wire formatting.
    assert mod.spec_sha256(compact) == mod.spec_sha256(committed)


# --- fetch_spec ---------------------------------------------------------------


def test_fetch_spec_wraps_network_failure_as_spec_fetch_error(monkeypatch):
    def boom(*_a, **_k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(mod.urllib.request, "urlopen", boom)
    with pytest.raises(mod.SpecFetchError):
        mod.fetch_spec("http://localhost:8000/openapi.json")


# --- main() exit-code orchestration (fetch stubbed; no network) ---------------


def test_main_returns_0_when_snapshot_matches_live(monkeypatch, capsys):
    committed = _SNAPSHOT.read_bytes()
    monkeypatch.setattr(mod, "fetch_spec", lambda url, **_k: committed)
    assert mod.main([]) == mod.EXIT_NO_DRIFT
    assert "OK:" in capsys.readouterr().out


def test_main_returns_1_and_prints_sha_on_drift(monkeypatch, capsys):
    committed = _SNAPSHOT.read_bytes()
    doc = json.loads(committed)
    doc["info"]["version"] = "9.9.9-changed"
    drifted = json.dumps(doc).encode()
    monkeypatch.setattr(mod, "fetch_spec", lambda url, **_k: drifted)

    assert mod.main([]) == mod.EXIT_DRIFT
    captured = capsys.readouterr()
    # The machine-readable handle for the remediation wrapper goes to stdout.
    assert f"SPEC_SHA256={mod.spec_sha256(drifted)}" in captured.out
    assert "DRIFT" in captured.err
    assert "regen.sh" in captured.err


def test_main_returns_3_when_watcher_unreachable(monkeypatch, capsys):
    def boom(url, **_k):
        raise mod.SpecFetchError("could not reach Watcher")

    monkeypatch.setattr(mod, "fetch_spec", boom)
    assert mod.main([]) == mod.EXIT_UNREACHABLE
    assert "SKIP" in capsys.readouterr().err


def test_main_returns_3_on_malformed_live_spec(monkeypatch, capsys):
    monkeypatch.setattr(mod, "fetch_spec", lambda url, **_k: b"<html>503</html>")
    assert mod.main([]) == mod.EXIT_UNREACHABLE
    assert "SKIP" in capsys.readouterr().err
