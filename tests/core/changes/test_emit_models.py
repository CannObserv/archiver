"""Lock the change-bus emit sites to the strict ``*Emit`` (``extra="forbid"``) models.

The emit sites construct events with ``SourceRevisionCapturedEmit`` /
``InfoItemPrimaryChangedEmit`` so a typo'd field is caught at *emit* time. A
regression to the canonical (``extra="ignore"``) classes would silently swallow
such a typo — these tests fail if an emit site rebinds those names to a
non-forbidding model (or drops them entirely).

Referencing the models *through the emitting module's namespace* (not importing
them straight from co-core) is deliberate: it ties the guard to what the emit
sites actually bind. The two live in different layers — archiver#139 moved the
SourceRevision emit into ``src.core.services`` so the bus consumer emits through
the same code as the route, and archiver#45 moved the InfoItem one into
``src.core.tools.bind_info_source`` so the POST route and the swap share it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.core.services import source_revision
from src.core.tools import bind_info_source


def test_source_revision_emit_model_forbids_extra_fields():
    """The SourceRevision write path emits via a forbid-configured model."""
    model = source_revision.SourceRevisionCapturedEmit
    assert model.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        model(
            occurred_at=datetime.now(UTC),
            info_source_id="01HZZ000000000000000000001",
            source_revision_id="01HZZ000000000000000000002",
            content_fingerprint="sha256:" + "a" * 64,
            bindings=[],
            typo_field=True,  # unexpected field must be rejected at emit
        )


def test_info_item_primary_changed_emit_model_forbids_extra_fields():
    """bind_info_source emits via a forbid-configured model."""
    model = bind_info_source.InfoItemPrimaryChangedEmit
    assert model.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        model(
            occurred_at=datetime.now(UTC),
            info_item_id="01HZZ000000000000000000003",
            old_info_source_id=None,
            new_info_source_id="01HZZ000000000000000000004",
            typo_field=True,  # unexpected field must be rejected at emit
        )
