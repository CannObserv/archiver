"""Detect drift between the committed watcher-openapi.json snapshot and LIVE Watcher.

Layer C of the generated-client drift defense (see
``docs/plans/2026-06-23-detect-generated-client-drift.md`` and CannObserv/archiver#70).

``clients/watcher-python/watcher-openapi.json`` is the contract-of-record the
vendored ``watcher_client`` is generated from. The hermetic CI gate
(``scripts/check_client_drift.py``, #68) proves ``generated/`` ==
regen-from-snapshot, but it CANNOT see the snapshot itself going stale relative
to the live Watcher service — that is the #66 failure mode (an upstream
response-shape change nobody regenerated for, surfacing only as a runtime
``KeyError``).

This detector closes that gap. It fetches Watcher's live ``/openapi.json``,
canonicalizes it EXACTLY as ``clients/watcher-python/scripts/regen.sh`` does
(``json.dumps(indent=2)`` + trailing newline, order-preserving — NOT
``sort_keys``), and byte-compares against the committed snapshot. Any difference
is real upstream drift. Because ``canonicalize`` mirrors ``regen.sh``, the
committed snapshot is a fixed point of it; that parity is what makes the
byte-compare meaningful rather than perpetually red.

It is meant to run ON THE VM, not on a GitHub runner: ``regen.sh`` already
targets ``http://localhost:8000`` and on-VM localhost sidesteps the
hairpin-NAT / public-URL / Watcher-uptime coupling that makes a blocking PR
check impossible (see #70). Stdlib-only, so it needs no project sync. The
remediation arm — regen + open a PR on drift — lives in the systemd-timer
wrapper ``scripts/watcher_live_drift_pr.sh``; this module only DETECTS.

Exit codes:
  0  no drift — committed snapshot matches live Watcher
  1  drift — snapshot is stale vs live; also prints ``SPEC_SHA256=<hex>`` (stdout)
  2  could-not-check — internal error (e.g. missing snapshot, unexpected crash);
     kept distinct from 1 so the wrapper never mistakes a failure for drift
  3  could-not-check — Watcher unreachable or served a non-JSON body (non-blocking
     skip; a down dev Watcher must not be reported as drift)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = REPO_ROOT / "clients" / "watcher-python" / "watcher-openapi.json"
# Same endpoint clients/watcher-python/scripts/regen.sh fetches — keep the two in
# sync if Watcher's local port ever moves (both are intentionally localhost: the
# detector and the regen it triggers must read the same live Watcher).
DEFAULT_URL = "http://localhost:8000/openapi.json"

# Live Watcher is on the same VM; a short bound turns a hung server into a skip.
_FETCH_TIMEOUT = 30

# Exit 1 is reserved for *drift* (conventional, like ``diff``/``grep``); the
# remediation wrapper acts only on it. So a non-drift failure (missing snapshot,
# unexpected crash) must NOT also exit 1 — it returns EXIT_ERROR so the wrapper
# can tell "could not check" apart from "the client is stale".
EXIT_NO_DRIFT = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2
EXIT_UNREACHABLE = 3


class SpecFetchError(RuntimeError):
    """Live Watcher ``/openapi.json`` could not be fetched or parsed as JSON.

    Distinct from detected drift: an unreachable or misbehaving Watcher is a
    skip (exit 3), never a false drift signal.
    """


def canonicalize(raw: bytes) -> bytes:
    """Canonicalize an OpenAPI document EXACTLY as ``regen.sh`` writes the snapshot.

    Mirror of ``clients/watcher-python/scripts/regen.sh``: pretty-print at
    ``indent=2`` with a trailing newline, order-preserving (NOT ``sort_keys`` —
    ``openapi-python-client`` emits model fields in spec property order, so
    sorting would reshape the generated tree, not just reformat). The committed
    snapshot is a fixed point of this function; that parity is the load-bearing
    invariant behind the byte-compare.
    """
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SpecFetchError(f"live spec is not valid JSON: {e}") from e
    return (json.dumps(doc, indent=2) + "\n").encode("utf-8")


def fetch_spec(url: str, *, timeout: float = _FETCH_TIMEOUT) -> bytes:
    """Fetch the raw bytes of Watcher's live ``/openapi.json``.

    ``/openapi.json`` is public (per ``regen.sh``) so no API key is sent. Any
    transport-level failure is wrapped as ``SpecFetchError`` so the caller can
    treat an unreachable Watcher as a skip, not as drift.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise SpecFetchError(f"could not reach Watcher at {url}: {e}") from e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"live Watcher OpenAPI URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_SNAPSHOT,
        help="committed OpenAPI snapshot to compare against",
    )
    args = parser.parse_args(argv)

    try:
        committed = args.snapshot.read_bytes()
    except OSError as e:
        print(f"ERROR: cannot read snapshot {args.snapshot}: {e}", file=sys.stderr)
        return EXIT_ERROR

    try:
        live_raw = fetch_spec(args.url)
        # Canonicalize once: this both parse-validates the live body (a bad body
        # raises SpecFetchError -> skip) and yields the bytes used for the
        # compare and the SHA, so the ~185 KB doc is processed a single time.
        live_canonical = canonicalize(live_raw)
    except SpecFetchError as e:
        print(f"SKIP: {e} — not reporting as drift", file=sys.stderr)
        return EXIT_UNREACHABLE

    if live_canonical == committed:
        print(f"OK: committed snapshot matches live Watcher at {args.url}")
        return EXIT_NO_DRIFT

    snapshot_rel = args.snapshot.relative_to(REPO_ROOT)
    print(
        f"DRIFT: {snapshot_rel} is stale vs live Watcher at {args.url}\n"
        "  → refresh snapshot + tree from live and open a PR:\n"
        "      bash clients/watcher-python/scripts/regen.sh",
        file=sys.stderr,
    )
    # Machine-readable handle for the remediation wrapper (branch keying / dedup).
    print(f"SPEC_SHA256={hashlib.sha256(live_canonical).hexdigest()}")
    return EXIT_DRIFT


if __name__ == "__main__":
    # Last-resort guard: an unexpected crash must not exit 1 (== drift) and trip
    # the remediation wrapper into acting on a non-existent drift.
    try:
        sys.exit(main())
    except Exception as e:
        # Deliberately broad: surface ANY unexpected bug as EXIT_ERROR (2), never
        # as exit 1 (drift). SystemExit/KeyboardInterrupt are BaseException, so
        # the normal sys.exit path and Ctrl-C still propagate.
        print(f"ERROR: unexpected failure: {e}", file=sys.stderr)
        sys.exit(EXIT_ERROR)
