"""Unit tests for src/core/tools/preview_extraction.py."""

import hashlib

import httpx
import pytest
from co_core.effects.fetch import FetchResult

from src.core.tools.preview_extraction import (
    PreviewExtractionResult,
    SourceSpecValidationError,
    TargetUnreachableError,
    preview_extraction,
)

HTML_FIXTURE = (
    b"<html><body><div class='target'>kept content</div><div>dropped content</div></body></html>"
)

HTML_WITH_TITLE = (
    b"<html><head><title>My Test Page</title></head>"
    b"<body><div class='target'>kept content</div></body></html>"
)

VALID_FULL_PAGE_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "full_page"},
    "fingerprint": {},
}

VALID_CSS_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "css", "selector": ".target"},
    "fingerprint": {},
}

DEFAULT_URL = "https://example.com"


def _stub_fetcher(content: bytes = HTML_FIXTURE, *, raise_exc: Exception | None = None):
    """Return a minimal fetch-driver stub."""

    class _Stub:
        async def execute(self, effect) -> FetchResult:
            if raise_exc is not None:
                raise raise_exc
            return FetchResult(
                content=content,
                status_code=200,
                headers={"content-type": "text/html"},
                duration_ms=5,
                fetcher_used="http",
            )

    return _Stub()


class TestPreviewExtractionFullPage:
    @pytest.mark.asyncio
    async def test_returns_preview_extraction_result(self):
        result = await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_FULL_PAGE_SPEC)
        assert isinstance(result, PreviewExtractionResult)

    @pytest.mark.asyncio
    async def test_chunks_contain_html_text(self):
        result = await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_FULL_PAGE_SPEC)
        assert len(result.chunks) >= 1
        joined = " ".join(c.text for c in result.chunks)
        assert "kept content" in joined

    @pytest.mark.asyncio
    async def test_total_chars_positive(self):
        result = await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_FULL_PAGE_SPEC)
        assert result.total_chars > 0

    @pytest.mark.asyncio
    async def test_fingerprint_has_sha256_prefix(self):
        result = await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_FULL_PAGE_SPEC)
        assert result.computed_fingerprint.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_fingerprint_algorithm_field_is_sha256(self):
        result = await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_FULL_PAGE_SPEC)
        assert result.fingerprint_algorithm == "sha256"

    @pytest.mark.asyncio
    async def test_fingerprint_value_matches_sha256_of_joined_text(self):
        result = await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_FULL_PAGE_SPEC)
        joined = "\n".join(c.text for c in result.chunks)
        expected_hex = hashlib.sha256(joined.encode("utf-8")).hexdigest()
        assert result.computed_fingerprint == f"sha256:{expected_hex}"


class TestPreviewExtractionCssSelector:
    @pytest.mark.asyncio
    async def test_css_filters_to_selector(self):
        result = await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_CSS_SPEC)
        joined = " ".join(c.text for c in result.chunks)
        assert "kept content" in joined
        assert "dropped content" not in joined

    @pytest.mark.asyncio
    async def test_fingerprint_has_sha256_prefix(self):
        result = await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_CSS_SPEC)
        assert result.computed_fingerprint.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_fingerprint_hex_part_is_64_chars(self):
        result = await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_CSS_SPEC)
        hex_part = result.computed_fingerprint[len("sha256:") :]
        assert len(hex_part) == 64


class TestPreviewExtractionValidation:
    @pytest.mark.asyncio
    async def test_missing_required_field_raises_source_spec_validation_error(self):
        bad_spec = {"schema_version": 1, "fingerprint": {}}  # missing extraction
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(_stub_fetcher(), DEFAULT_URL, bad_spec)
        assert len(exc_info.value.errors) >= 1

    @pytest.mark.asyncio
    async def test_target_field_rejected_by_schema(self):
        """target is no longer part of the spec schema."""
        bad_spec = {
            "schema_version": 1,
            "target": {"url": "https://example.com"},
            "extraction": {"algorithm": "full_page"},
            "fingerprint": {},
        }
        with pytest.raises(SourceSpecValidationError):
            await preview_extraction(_stub_fetcher(), DEFAULT_URL, bad_spec)

    @pytest.mark.asyncio
    async def test_empty_doc_raises_source_spec_validation_error(self):
        with pytest.raises(SourceSpecValidationError):
            await preview_extraction(_stub_fetcher(), DEFAULT_URL, {})


class TestPreviewExtractionFetchFailure:
    @pytest.mark.asyncio
    async def test_connect_error_raises_target_unreachable_error(self):
        with pytest.raises(TargetUnreachableError):
            await preview_extraction(
                _stub_fetcher(raise_exc=httpx.ConnectError("nope")),
                DEFAULT_URL,
                VALID_FULL_PAGE_SPEC,
            )

    @pytest.mark.asyncio
    async def test_http_error_raises_target_unreachable_error(self):
        with pytest.raises(TargetUnreachableError):
            await preview_extraction(
                _stub_fetcher(raise_exc=httpx.TimeoutException("timeout")),
                DEFAULT_URL,
                VALID_FULL_PAGE_SPEC,
            )


class TestPreviewExtractionUrlFromSpec:
    @pytest.mark.asyncio
    async def test_url_is_passed_explicitly(self):
        """Fetcher receives the URL passed as the explicit url parameter."""
        received_urls = []

        class _CaptureFetcher:
            async def execute(self, effect) -> FetchResult:
                received_urls.append(effect.url)
                return FetchResult(
                    content=HTML_FIXTURE,
                    status_code=200,
                    headers={"content-type": "text/html"},
                    duration_ms=5,
                    fetcher_used="http",
                )

        await preview_extraction(
            _CaptureFetcher(), "https://specific.example.com/path", VALID_FULL_PAGE_SPEC
        )
        assert received_urls == ["https://specific.example.com/path"]


class TestPreviewExtractionPageTitle:
    @pytest.mark.asyncio
    async def test_page_title_populated_from_title_tag(self):
        result = await preview_extraction(
            _stub_fetcher(HTML_WITH_TITLE), DEFAULT_URL, VALID_FULL_PAGE_SPEC
        )
        assert result.page_title == "My Test Page"

    @pytest.mark.asyncio
    async def test_page_title_empty_when_no_title_tag(self):
        result = await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_FULL_PAGE_SPEC)
        assert result.page_title == ""
