"""Compare an observed ``spec_fingerprint`` against the registry's ``source_specs``.

The flag half of archiver#139's **record and flag, never reject**. The recording
half shipped alone because co-core constrained the value only to be *stable for a
given spec*: Archiver held the authoritative specs with no way to derive the same
string the producer had, and reimplementing the producer's derivation would drift
into flagging a mismatch on a spec that never changed. cannobserv#309 moved the
derivation into co-core (``co_core.pure.extract``), so both sides now run one
function rather than two readings of an algorithm.

**Every uncertain branch resolves to ``incomparable``, never to ``superseded``.**
That asymmetry is the whole design: a false mismatch reads exactly like the real
condition the field exists to detect, so "cannot compare" and "compared, and it
differs" must never collapse into one answer.

Comparison is *not* rejection. Nothing here fails a write — archiver#140 makes
spec delivery eventually consistent, so a producer extracting under a superseded
spec is an expected transient state, and the revision it observed is real either
way.
"""

from __future__ import annotations

from dataclasses import dataclass

from co_core.pure.extract import (
    SpecFingerprintError,
    UnknownDerivationError,
    derivation_of,
    spec_fingerprint_index,
)

from src.core.logging import get_logger

logger = get_logger(__name__)

# The ``spec_match`` vocabulary. Stored as text rather than an enum type so the
# set can grow without a migration; the column is documented in docs/SCHEMA.md.
CURRENT = "current"
SUPERSEDED = "superseded"
INCOMPARABLE = "incomparable"


@dataclass(frozen=True, slots=True)
class SpecComparison:
    """The outcome of comparing one observation against the registry's specs.

    ``match`` is ``None`` when there was nothing to compare — the observation
    carried no ``spec_fingerprint``. That is distinct from ``INCOMPARABLE``,
    which means a value arrived and could not be evaluated.

    ``position`` is set only for ``CURRENT``: the index in ``source_specs`` the
    producer actually extracted under.
    """

    match: str | None
    position: int | None

    @property
    def is_fallback(self) -> bool:
        """Whether extraction used a spec *other than* the primary.

        ``source_specs[0]`` is the primary strategy and the rest are cross-check
        alternatives, so a match past position 0 means the primary stopped
        working and the producer's fallback loop moved on — selector rot in
        progress, and arguably a more actionable signal than a mismatch.
        """
        return self.match == CURRENT and self.position is not None and self.position > 0


def compare_spec_fingerprint(observed: str | None, specs: list[dict]) -> SpecComparison:
    """Locate ``observed`` among ``specs``, or say why it could not be located.

    Never raises: a comparison that cannot be made is an outcome, not an error.
    The caller records the result alongside the revision and carries on.
    """
    if observed is None:
        # Not a mismatch. The field is optional and absence means the producer
        # had no spec identity to report — including a producer that has not
        # adopted it yet, which is every producer during a rollout.
        return SpecComparison(match=None, position=None)

    derivation = derivation_of(observed)
    if derivation is None:
        logger.warning(
            "Malformed spec_fingerprint on an observation; not comparing",
            extra={"spec_fingerprint": observed},
        )
        return SpecComparison(match=INCOMPARABLE, position=None)

    try:
        index = spec_fingerprint_index(specs, derivation=derivation)
    except UnknownDerivationError:
        # A derivation this co-core cannot compute. Skipping is mandated by the
        # contract, not chosen here: flagging against a derivation you cannot
        # reproduce is precisely the false positive the tag exists to prevent.
        logger.info(
            "spec_fingerprint uses a derivation this co-core cannot compute; not comparing",
            extra={"derivation": derivation, "spec_fingerprint": observed},
        )
        return SpecComparison(match=INCOMPARABLE, position=None)
    except SpecFingerprintError:
        # The registry's own specs have no canonical form. co-core aborts the
        # whole index rather than returning a partial one, because a partial
        # index turns a spec we *do* hold into a miss. Unreachable for
        # schema-valid specs, so this is "these specs are broken" — an operator
        # signal, logged at ERROR — and never a comparison outcome.
        logger.error(
            "InfoSource source_specs are not fingerprintable; cannot compare",
            extra={"spec_fingerprint": observed},
            exc_info=True,
        )
        return SpecComparison(match=INCOMPARABLE, position=None)

    positions = index.get(observed)
    if not positions:
        return SpecComparison(match=SUPERSEDED, position=None)
    # Positions is a list because a source_specs list may legitimately repeat a
    # spec; the first index is the one the fallback loop would have reached.
    return SpecComparison(match=CURRENT, position=positions[0])
