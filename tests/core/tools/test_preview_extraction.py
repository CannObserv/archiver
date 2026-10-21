"""Unit tests for src/core/tools/preview_extraction.py."""

import hashlib
import threading

import httpx
import pytest
from co_core.effects.fetch import FetchResult
from co_core.pure.extract.base import ExtractionResult
from co_core.pure.extract.html import HtmlExtractor
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
    """No extractor honours ``regex`` (cannobserv#523, #317)."""

    @pytest.mark.asyncio
    async def test_refused_algorithm_fails_schema(self):
        spec = {
            "schema_version": 1,
            "extraction": {"algorithm": "regex", "selector": "kept"},
            "fingerprint": {},
        }
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(_stub_fetcher(), DEFAULT_URL, spec)
        assert [e["path"] for e in exc_info.value.errors] == ["/extraction/algorithm"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("content", "content_type", "selector"),
        [
            (RSS_FIXTURE, "application/rss+xml", "//item["),  # an invalid expression
            (HTML_FIXTURE, "text/html", "//div["),  # on HTML too (cannobserv#557)
            (HTML_FIXTURE, "text/html", "//div | //div/@class"),  # elements mixed with others
        ],
    )
    async def test_extractor_refusal_reported_at_extraction(self, content, content_type, selector):
        """The refusal is the algorithm's or the selector's; ``/extraction`` fits both."""
        spec = {
            "schema_version": 1,
            "extraction": {"algorithm": "xpath", "selector": selector},
            "fingerprint": {},
        }
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(
                _stub_fetcher(content, content_type=content_type), DEFAULT_URL, spec
            )
        assert [e["path"] for e in exc_info.value.errors] == ["/extraction"]
        assert exc_info.value.errors[0]["message"]


class TestPreviewExtractionXpathOnHtml:
    """co-core 0.38 honours ``xpath`` on HTML (cannobserv#557, #355)."""

    @staticmethod
    def _spec(algorithm: str, selector: str) -> dict:
        return {
            "schema_version": 1,
            "extraction": {"algorithm": algorithm, "selector": selector},
            "fingerprint": {},
        }

    @pytest.mark.asyncio
    async def test_xpath_on_html_returns_its_matches(self):
        result = await preview_extraction(
            _stub_fetcher(), DEFAULT_URL, self._spec("xpath", "//div[@class='target']")
        )
        assert [c.text for c in result.chunks] == ["kept content"]

    @pytest.mark.asyncio
    async def test_xpath_and_css_picking_the_same_elements_fingerprint_identically(self):
        """Switching a spec between the two algorithms moves ``spec1:``, not the content."""
        by_xpath = await preview_extraction(
            _stub_fetcher(), DEFAULT_URL, self._spec("xpath", "//div[@class='target']")
        )
        by_css = await preview_extraction(
            _stub_fetcher(), DEFAULT_URL, self._spec("css", ".target")
        )
        assert by_xpath.computed_fingerprint == by_css.computed_fingerprint


IGNORE_FIXTURE = (
    b"<html><body><div class='target'><p>kept content</p>"
    b"<p class='stamp'>Last updated 2026-10-21</p></div><div>dropped content</div></body></html>"
)


class TestPreviewExtractionIgnoreSelectors:
    """``extraction.ignore_selectors`` strips noise before the selection (cannobserv#570, #378)."""

    @staticmethod
    def _spec(algorithm: str, selector: str | None = None, ignore=(".stamp",)) -> dict:
        extraction = {"algorithm": algorithm, "ignore_selectors": list(ignore)}
        if selector is not None:
            extraction["selector"] = selector
        return {"schema_version": 1, "extraction": extraction, "fingerprint": {}}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("algorithm", "selector"),
        [("css", ".target"), ("xpath", "//div[@class='target']"), ("full_page", None)],
    )
    async def test_removed_before_the_selection(self, algorithm, selector):
        result = await preview_extraction(
            _stub_fetcher(IGNORE_FIXTURE), DEFAULT_URL, self._spec(algorithm, selector)
        )
        text = " ".join(c.text for c in result.chunks)
        assert "kept content" in text
        assert "Last updated" not in text

    @pytest.mark.asyncio
    async def test_changes_the_fingerprint_of_the_same_bytes(self):
        """The extracted fingerprint moves with the spec: the discontinuity #378 names."""
        plain = await preview_extraction(_stub_fetcher(IGNORE_FIXTURE), DEFAULT_URL, VALID_CSS_SPEC)
        stripped = await preview_extraction(
            _stub_fetcher(IGNORE_FIXTURE), DEFAULT_URL, self._spec("css", ".target")
        )
        assert plain.computed_fingerprint != stripped.computed_fingerprint

    @pytest.mark.asyncio
    async def test_refused_on_a_feed_at_extraction(self):
        """Only HTML honours them; the schema can't see the media type, co-core can."""
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(
                _stub_fetcher(RSS_FIXTURE, content_type="application/rss+xml"),
                DEFAULT_URL,
                self._spec("full_page"),
            )
        assert [e["path"] for e in exc_info.value.errors] == ["/extraction"]
        # co-core's refusal, not the schema's "additional properties" one (CR 4).
        assert "cannot honour ignore_selectors" in exc_info.value.errors[0]["message"]

    @pytest.mark.asyncio
    async def test_uncompilable_one_refused_at_extraction(self):
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(
                _stub_fetcher(IGNORE_FIXTURE), DEFAULT_URL, self._spec("css", ".target", ["p[["])
            )
        assert [e["path"] for e in exc_info.value.errors] == ["/extraction"]
        assert "ignore_selectors CSS selector" in exc_info.value.errors[0]["message"]


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
        assert [e["path"] for e in exc_info.value.errors] == ["/extraction"]

    @pytest.mark.asyncio
    async def test_missing_content_type_dispatches_html(self):
        result = await preview_extraction(
            _stub_fetcher(content_type=None), DEFAULT_URL, VALID_CSS_SPEC
        )
        assert [c.text for c in result.chunks] == ["kept content"]

    @pytest.mark.asyncio
    async def test_feed_fingerprint_is_sha256_of_joined_lines(self):
        result = await preview_extraction(
            _stub_fetcher(RSS_FIXTURE, content_type="application/rss+xml"),
            DEFAULT_URL,
            VALID_FULL_PAGE_SPEC,
        )
        joined = "\n".join(c.text for c in result.chunks)
        expected_hex = hashlib.sha256(joined.encode("utf-8")).hexdigest()
        assert result.computed_fingerprint == f"sha256:{expected_hex}"

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


class TestPreviewExtractionBadSelector:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("selector", ["div[[", "div::before"])
    async def test_uncompilable_css_selector_raises_source_spec_validation_error(self, selector):
        """co-core 0.38 refuses a selector soupsieve can't compile, a pseudo-element included.

        Before it, a malformed one raised soupsieve's own error and a pseudo-element a
        bare ``NotImplementedError``, which escaped the preview as a 500 (cannobserv#570).
        """
        spec = {
            "schema_version": 1,
            "extraction": {"algorithm": "css", "selector": selector},
            "fingerprint": {},
        }
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(_stub_fetcher(), DEFAULT_URL, spec)
        assert [e["path"] for e in exc_info.value.errors] == ["/extraction"]
        assert "selectors CSS selector" in exc_info.value.errors[0]["message"]


class TestPreviewExtractionOffLoop:
    @pytest.mark.asyncio
    async def test_extraction_runs_off_the_event_loop_thread(self, monkeypatch):
        """A PDF or spreadsheet extract is CPU-bound; the loop also runs the bus (#317 CR 4)."""
        seen: list[int] = []
        original = HtmlExtractor.extract

        def _spy(self, content, config=None):
            seen.append(threading.get_ident())
            return original(self, content, config=config)

        monkeypatch.setattr(HtmlExtractor, "extract", _spy)
        await preview_extraction(_stub_fetcher(), DEFAULT_URL, VALID_FULL_PAGE_SPEC)
        assert seen and seen[0] != threading.get_ident()


JSON_FIXTURE = b'{"items": [{"title": "A  b"}, {"title": "C"}], "count": 2}'


class TestPreviewExtractionJson:
    """co-core 0.38 extracts JSON bodies (cannobserv#354, #356)."""

    @staticmethod
    def _spec(selector: str | None = None) -> dict:
        extraction = {"algorithm": "full_page"}
        if selector is not None:
            extraction = {"algorithm": "jsonpath", "selector": selector}
        return {"schema_version": 1, "extraction": extraction, "fingerprint": {}}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content_type", ["application/json", "application/ld+json", "application/vnd.api+json"]
    )
    async def test_jsonpath_previews_its_matches(self, content_type):
        """One chunk per node, labelled with its normalized path; strings whitespace-normalized."""
        result = await preview_extraction(
            _stub_fetcher(JSON_FIXTURE, content_type=content_type),
            DEFAULT_URL,
            self._spec("$.items[*].title"),
        )
        assert [(c.label, c.text) for c in result.chunks] == [
            ("$['items'][0]['title']", "A b"),
            ("$['items'][1]['title']", "C"),
        ]
        assert result.page_title == ""

    @pytest.mark.asyncio
    async def test_json_url_breaks_a_missing_content_type(self):
        result = await preview_extraction(
            _stub_fetcher(JSON_FIXTURE, content_type=None),
            "https://example.com/feed.json",
            self._spec("$.count"),
        )
        assert [c.text for c in result.chunks] == ["2"]

    @pytest.mark.asyncio
    async def test_full_page_on_json_is_one_canonical_chunk(self):
        """Canonical JSON keeps string whitespace: not the text ``jsonpath`` gives."""
        result = await preview_extraction(
            _stub_fetcher(JSON_FIXTURE, content_type="application/json"), DEFAULT_URL, self._spec()
        )
        [chunk] = result.chunks
        assert chunk.label == "$"
        assert '"A  b"' in chunk.text

    @pytest.mark.asyncio
    async def test_no_match_is_zero_chunks_not_an_error(self):
        """Processor publishes an empty extraction for it, not an error (processor#37)."""
        result = await preview_extraction(
            _stub_fetcher(JSON_FIXTURE, content_type="application/json"),
            DEFAULT_URL,
            self._spec("$.nope"),
        )
        assert result.chunks == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("content", "content_type", "spec"),
        [
            (HTML_FIXTURE, "text/html", {"algorithm": "jsonpath", "selector": "$.a"}),
            (JSON_FIXTURE, "application/json", {"algorithm": "css", "selector": ".a"}),
            (JSON_FIXTURE, "application/json", {"algorithm": "xpath", "selector": "//a"}),
            (JSON_FIXTURE, "application/json", {"algorithm": "jsonpath", "selector": "$.a | $.b"}),
            (
                JSON_FIXTURE,
                "application/json",
                {"algorithm": "full_page", "ignore_selectors": [".a"]},
            ),
        ],
        ids=["jsonpath-on-html", "css-on-json", "xpath-on-json", "not-rfc9535", "ignore-on-json"],
    )
    async def test_extractor_refusal_reported_at_extraction(self, content, content_type, spec):
        doc = {"schema_version": 1, "extraction": spec, "fingerprint": {}}
        with pytest.raises(SourceSpecValidationError) as exc_info:
            await preview_extraction(
                _stub_fetcher(content, content_type=content_type), DEFAULT_URL, doc
            )
        assert [e["path"] for e in exc_info.value.errors] == ["/extraction"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("content", [b"{nope", b'{"a": NaN}'])
    async def test_unparseable_json_fails_extraction(self, content):
        with pytest.raises(ExtractionFailedError, match="Failed to parse JSON"):
            await preview_extraction(
                _stub_fetcher(content, content_type="application/json"),
                DEFAULT_URL,
                self._spec("$.a"),
            )
