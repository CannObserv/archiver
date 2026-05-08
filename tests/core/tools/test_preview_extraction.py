"""Unit tests for src/core/tools/preview_extraction.py — SourceSpec variant."""

import hashlib

import httpx
import pytest

from src.core.fetchers.base import FetchResult
from src.core.tools.preview_extraction import (
    PreviewExtractionResult,
    SourceSpecValidationError,
    TargetUnreachableError,
    preview_extraction,
)

HTML_FIXTURE = (
    b"<html><body>"
    b"<div class='target'>kept content</div>"
    b"<div>dropped content</div>"
    b"</body></html>"
)

VALID_FULL_PAGE_SOURCE_SPEC = {
    "schema_version": 1,
    "target": {"url": "https://example.com"},
    "extraction": {"algorithm": "full_page"},
    "fingerprint": {},
}

VALID_CSS_SOURCE_SPEC = {
    "schema_version": 1,
    "target": {"url": "https://example.com"},
    "extraction": {"algorithm": "css", "selector": ".target"},
    "fingerprint": {},
}


def _stub_fetcher(content: bytes = HTML_FIXTURE, *, raise_exc: Exception | None = None):
    """Return a minimal HttpFetcherProtocol stub."""

    class _Stub:
        async def fetch(self, url: str, config: dict | None = None) -> FetchResult:
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
        result = await preview_extraction(_stub_fetcher(), VALID_FULL_PAGE_SOURCE_SPEC)
        assert isinstance(result, PreviewExtractionResult)

    @pytest.mark.asyncio
    async def test_chunks_contain_html_text(self):
        result = await preview_extraction(_stub_fetcher(), VALID_FULL_PAGE_SOURCE_SPEC)
        assert len(result.chunks) >= 1
        joined = " ".join(c.text for c in result.chunks)
        assert "kept content" in joined

    @pytest.mark.asyncio
    async def test_total_chars_positive(self):
        result = await preview_extraction(_stub_fetcher(), VALID_FULL_PAGE_SOURCE_SPEC)
        assert result.total_chars > 0

    @pytest.mark.asyncio
    async def test_fingerprint_has_sha256_prefix(self):
        result = await preview_extraction(_stub_fetcher(), VALID_FULL_PAGE_SOURCE_SPEC)
        assert result.computed_fingerprint.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_fingerprint_algorithm_field_is_sha256(self):
        result = await preview_extraction(_stub_fetcher(), VALID_FULL_PAGE_SOURCE_SPEC)
        assert result.fingerprint_algorithm == "sha256"

    @pytest.mark.asyncio
    async def test_fingerprint_value_matches_sha256_of_joined_text(self):
        result = await preview_extraction(_stub_fetcher(), VALID_FULL_PAGE_SOURCE_SPEC)
        joined = "\n".join(c.text for c in result.chunks)
        expected_hex = hashlib.sha256(joined.encode("utf-8")).hexdigest()
        assert result.computed_fingerprint == f"sha256:{expected_hex}"


class TestPreviewExtractionCssSelector:
    @pytest.mark.asyncio
    async def test_css_filters_to_selector(self):
        result = await preview_extraction(_stub_fetcher(), VALID_CSS_SOURCE_SPEC)
        joined = " ".join(c.text for c in result.chunks)
        assert "kept content" in joined
        assert "dropped content" not in joined

    @pytest.mark.asyncio
    async def test_fingerprint_has_sha256_prefix(self):
        result = await preview_extraction(_stub_fetcher(), VALID_CSS_SOURCE_SPEC)
        assert result.computed_fingerprint.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_fingerprint_hex_part_is_64_chars(self):
        result = await preview_extraction(_stub_fetcher(), VALID_CSS_SOURCE_SPEC)
        hex_part = result.computed_fingerprint[len("sha256:"):]
        assert len(hex_part) == 64


class TestPreviewExtractionValidation:
    @pytest.mark.asyncio
    async def test_missing_required_field_raises_source_spec_validation_error(self):
        # extraction is required; dropping it triggers schema validation failure
        bad_spec = {
            "schema_version": 1,
            "target": {"url": "https://example.com"},
            "fingerprint": {},
        }
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(_stub_fetcher(), bad_spec)
        assert len(exc_info.value.errors) >= 1

    @pytest.mark.asyncio
    async def test_missing_target_url_raises_source_spec_validation_error(self):
        bad_spec = {
            "schema_version": 1,
            "target": {},
            "extraction": {"algorithm": "full_page"},
            "fingerprint": {"algorithm": "sha256"},
        }
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(_stub_fetcher(), bad_spec)
        assert any("url" in e["message"] or "url" in e["path"] for e in exc_info.value.errors)

    @pytest.mark.asyncio
    async def test_empty_doc_raises_source_spec_validation_error(self):
        with pytest.raises(SourceSpecValidationError):
            await preview_extraction(_stub_fetcher(), {})


class TestPreviewExtractionFetchFailure:
    @pytest.mark.asyncio
    async def test_connect_error_raises_target_unreachable_error(self):
        with pytest.raises(TargetUnreachableError):
            await preview_extraction(
                _stub_fetcher(raise_exc=httpx.ConnectError("nope")),
                VALID_FULL_PAGE_SOURCE_SPEC,
            )

    @pytest.mark.asyncio
    async def test_http_error_raises_target_unreachable_error(self):
        with pytest.raises(TargetUnreachableError):
            await preview_extraction(
                _stub_fetcher(raise_exc=httpx.TimeoutException("timeout")),
                VALID_FULL_PAGE_SOURCE_SPEC,
            )


class TestPreviewExtractionUrlFromSpec:
    @pytest.mark.asyncio
    async def test_url_is_pulled_from_source_spec_target(self):
        """Fetcher receives the URL from source_spec.target.url."""
        received_urls = []

        class _CaptureFetcher:
            async def fetch(self, url: str, config: dict | None = None) -> FetchResult:
                received_urls.append(url)
                return FetchResult(
                    content=HTML_FIXTURE,
                    status_code=200,
                    headers={"content-type": "text/html"},
                    duration_ms=5,
                    fetcher_used="http",
                )

        spec = {**VALID_FULL_PAGE_SOURCE_SPEC, "target": {"url": "https://specific.example.com/path"}}
        await preview_extraction(_CaptureFetcher(), spec)
        assert received_urls == ["https://specific.example.com/path"]
