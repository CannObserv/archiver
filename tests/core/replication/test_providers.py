"""One list of providers Replicator cannot write yet, for API and dashboard (archiver#153)."""

import pytest

from src.core.replication import providers
from src.core.replication.providers import (
    UNWRITABLE_PROVIDERS,
    ProviderUnwritableError,
    check_provider_writable,
)
from src.dashboard import rep_spec_picker
from src.dashboard.routes import info_items as dashboard_info_items
from src.dashboard.routes import rep_specs as dashboard_rep_specs


def test_gdrive_and_ia_are_unwritable_gcs_is_not():
    assert set(UNWRITABLE_PROVIDERS) == {"gdrive", "ia"}


@pytest.mark.parametrize("provider", ["gdrive", "ia"])
def test_check_refuses_an_unwritable_provider_with_its_reason(provider):
    with pytest.raises(ProviderUnwritableError) as exc:
        check_provider_writable(provider)
    assert exc.value.provider == provider
    assert exc.value.reason == UNWRITABLE_PROVIDERS[provider]


def test_check_passes_gcs():
    check_provider_writable("gcs")


def test_dashboard_reads_the_same_list():
    """Lifting an entry when a writer lands is one change, not two (archiver#153)."""
    for module in (rep_spec_picker, dashboard_info_items, dashboard_rep_specs):
        assert module.UNWRITABLE_PROVIDERS is providers.UNWRITABLE_PROVIDERS
