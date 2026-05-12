"""Guard the SDK public surface — Page* types must re-export from the package root (archiver#14)."""

from __future__ import annotations

import archiver_client
from archiver_client.generated.models.page_info_item_out import (
    PageInfoItemOut as _SourcePageInfoItemOut,
)
from archiver_client.generated.models.page_info_source_out import (
    PageInfoSourceOut as _SourcePageInfoSourceOut,
)
from archiver_client.generated.models.page_rep_spec_out import (
    PageRepSpecOut as _SourcePageRepSpecOut,
)


def test_page_types_are_the_generated_models():
    from archiver_client import PageInfoItemOut, PageInfoSourceOut, PageRepSpecOut

    assert PageInfoItemOut is _SourcePageInfoItemOut
    assert PageInfoSourceOut is _SourcePageInfoSourceOut
    assert PageRepSpecOut is _SourcePageRepSpecOut


def test_page_types_in_dunder_all():
    assert "PageInfoItemOut" in archiver_client.__all__
    assert "PageInfoSourceOut" in archiver_client.__all__
    assert "PageRepSpecOut" in archiver_client.__all__


def test_all_dunder_entries_are_module_attributes():
    """Every name in __all__ must resolve — catches typos and dropped imports."""
    missing = [n for n in archiver_client.__all__ if not hasattr(archiver_client, n)]
    assert not missing, f"__all__ lists names not on the module: {missing}"
