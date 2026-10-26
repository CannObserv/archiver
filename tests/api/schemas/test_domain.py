"""Domain schema descriptions say where each policy field takes effect (archiver#438)."""

import pytest

from src.api.schemas.domain import DomainOut, DomainPatch


@pytest.mark.parametrize("model", [DomainOut, DomainPatch])
def test_min_interval_reads_live_since_f1(model) -> None:
    """F1 made Archiver the content.fetch-policy producer; the field is no longer dark."""
    text = model.model_fields["min_interval_seconds"].description

    assert "content.fetch-policy" in text
    assert "Dark until" not in text
    assert "Watcher" not in text


@pytest.mark.parametrize("model", [DomainOut, DomainPatch])
def test_default_watch_spec_stays_dark_until_f2(model) -> None:
    text = model.model_fields["default_watch_spec"].description

    assert "Dark until cadence resolution (#364, flip F2)" in text
