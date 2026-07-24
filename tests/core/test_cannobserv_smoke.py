"""Phase-0 adoption smoke test for the cannobserv substrate (archiver#72).

Proves the ``co-core`` dependency resolves, imports, and is behaviourally
correct against archiver's own code — the end-to-end toolchain check that
Phase 0 exists to validate (#72 sequencing table). ``co_core.pure.util.hashing``
is the chosen trivial pure util: it sits squarely on archiver's fingerprint
path (``SourceRevision`` identity is ``sha256:<hex>``), so this doubles as the
Phase-1 anchor — when fingerprint logic moves into co-core, this parity is the
contract it must keep.
"""

import hashlib

from co_core.pure.util.hashing import sha256


def test_co_core_sha256_matches_stdlib_hexdigest() -> None:
    """co-core's sha256 returns a bare hex digest identical to hashlib's."""
    data = b"cannabis observer"
    assert sha256(data) == hashlib.sha256(data).hexdigest()


def test_co_core_sha256_matches_archiver_fingerprint_body() -> None:
    """The digest co-core computes is the body archiver prefixes with ``sha256:``.

    Mirrors ``src/core/tools/preview_extraction._compute_fingerprint`` and
    ``src/core/extractors/base`` (both ``hashlib.sha256(text.encode()).hexdigest()``),
    so a future swap to the co-core impl is a no-op on the wire.
    """
    text = "Some extracted content.\n"
    assert f"sha256:{sha256(text.encode('utf-8'))}" == (
        f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
    )
