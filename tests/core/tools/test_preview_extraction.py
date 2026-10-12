"""Unit tests for src/core/tools/preview_extraction.py."""

import hashlib

import httpx
import pytest
from co_core.effects.fetch import FetchResult
from co_core.pure.extract import canonical_text_fingerprint
from co_core.pure.extract.base import ExtractionResult
from co_core.pure.extract.pdf import PdfExtractor

from src.core.tools.preview_extraction import (
    ExtractionFailedError,
    PreviewExtractionResult,
    SourceSpecValidationError,
    TargetUnreachableError,
    preview_extraction,
)

HTML_FIXTURE = (
    b"<html><body><div class='target'>kept content</div><div>dropped content</div></body></html>"
)

RSS_FIXTURE = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>Security Bulletins</title>'
    b"<link>https://example.com/</link>"
    b"<item><guid>ts-1</guid><title>First</title><link>https://example.com/1</link>"
    b"<pubDate>Mon, 05 Oct 2026 12:00:00 GMT</pubDate></item>"
    b"<item><guid>ts-2</guid><title>Second</title><link>https://example.com/2</link></item>"
    b"</channel></rss>"
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


def _stub_fetcher(
    content: bytes = HTML_FIXTURE,
    *,
    raise_exc: Exception | None = None,
    content_type: str | None = "text/html",
):
    """Return a minimal fetch-driver stub."""
    headers = {"Content-Type": content_type} if content_type is not None else {}

    class _Stub:
        async def execute(self, effect) -> FetchResult:
            if raise_exc is not None:
                raise raise_exc
            return FetchResult(
                content=content,
                status_code=200,
                headers=headers,
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


class TestPreviewExtractionRefusedAlgorithm:
    """co-core 0.32 refuses a spec no extractor honours (cannobserv#523, #317)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("algorithm", "selector"),
        [("xpath", "//div"), ("regex", "kept"), ("jsonpath", "$.a")],
    )
    async def test_refused_spec_raises_source_spec_validation_error(self, algorithm, selector):
        spec = {
            "schema_version": 1,
            "extraction": {"algorithm": algorithm, "selector": selector},
            "fingerprint": {},
        }
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(_stub_fetcher(), DEFAULT_URL, spec)
        assert [e["path"] for e in exc_info.value.errors] == ["/extraction/algorithm"]
        assert exc_info.value.errors[0]["message"]


class TestPreviewExtractionDispatch:
    """The preview extracts as Processor does: essence -> extractor (#317)."""

    @pytest.mark.asyncio
    async def test_rss_full_page_gives_one_chunk_per_item(self):
        result = await preview_extraction(
            _stub_fetcher(RSS_FIXTURE, content_type="application/rss+xml"),
            DEFAULT_URL,
            VALID_FULL_PAGE_SPEC,
        )
        assert [c.text for c in result.chunks] == [
            "ts-1\t2026-10-05T12:00:00Z\tFirst\thttps://example.com/1",
            "ts-2\t\tSecond\thttps://example.com/2",
        ]

    @pytest.mark.asyncio
    async def test_ambiguous_content_type_falls_back_to_url_extension(self):
        result = await preview_extraction(
            _stub_fetcher(RSS_FIXTURE, content_type="text/plain"),
            "https://example.com/security-bulletins/index.xml",
            VALID_FULL_PAGE_SPEC,
        )
        assert result.chunks[0].text.startswith("ts-1\t")

    @pytest.mark.asyncio
    async def test_xpath_honoured_on_xml(self):
        spec = {
            "schema_version": 1,
            "extraction": {"algorithm": "xpath", "selector": "//item/title"},
            "fingerprint": {},
        }
        result = await preview_extraction(
            _stub_fetcher(RSS_FIXTURE, content_type="text/xml"), DEFAULT_URL, spec
        )
        assert [c.text for c in result.chunks] == ["First", "Second"]

    @pytest.mark.asyncio
    async def test_css_on_xml_refused_as_validation_error(self):
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(
                _stub_fetcher(RSS_FIXTURE, content_type="application/xml"),
                DEFAULT_URL,
                VALID_CSS_SPEC,
            )
        assert [e["path"] for e in exc_info.value.errors] == ["/extraction/algorithm"]

    @pytest.mark.asyncio
    async def test_missing_content_type_dispatches_html(self):
        result = await preview_extraction(
            _stub_fetcher(content_type=None), DEFAULT_URL, VALID_CSS_SPEC
        )
        assert [c.text for c in result.chunks] == ["kept content"]

    @pytest.mark.asyncio
    async def test_fingerprint_is_canonical_text_fingerprint(self):
        result = await preview_extraction(
            _stub_fetcher(RSS_FIXTURE, content_type="application/rss+xml"),
            DEFAULT_URL,
            VALID_FULL_PAGE_SPEC,
        )
        chunks = [type("C", (), {"text": c.text})() for c in result.chunks]
        assert result.computed_fingerprint == canonical_text_fingerprint(chunks)

    @pytest.mark.asyncio
    async def test_feed_title_is_channel_title(self):
        result = await preview_extraction(
            _stub_fetcher(RSS_FIXTURE, content_type="application/rss+xml"),
            DEFAULT_URL,
            VALID_FULL_PAGE_SPEC,
        )
        assert result.page_title == "Security Bulletins"

    @pytest.mark.asyncio
    async def test_unparseable_body_raises_extraction_failed(self):
        with pytest.raises(ExtractionFailedError):
            await preview_extraction(
                _stub_fetcher(b"<rss><unclosed>", content_type="application/rss+xml"),
                DEFAULT_URL,
                VALID_FULL_PAGE_SPEC,
            )

    @pytest.mark.asyncio
    async def test_atom_title_is_feed_title(self):
        atom = (
            b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
            b"<title>Atom Feed</title><entry><id>a-1</id><title>One</title></entry></feed>"
        )
        result = await preview_extraction(
            _stub_fetcher(atom, content_type="application/atom+xml"),
            DEFAULT_URL,
            VALID_FULL_PAGE_SPEC,
        )
        assert result.page_title == "Atom Feed"

    @pytest.mark.asyncio
    async def test_pdf_has_no_page_title(self, monkeypatch):
        monkeypatch.setattr(
            PdfExtractor,
            "extract",
            lambda self, content, config=None: ExtractionResult(chunks=[]),
        )
        result = await preview_extraction(
            _stub_fetcher(b"<title>not a title</title>", content_type="application/pdf"),
            DEFAULT_URL,
            VALID_FULL_PAGE_SPEC,
        )
        assert result.page_title == ""
