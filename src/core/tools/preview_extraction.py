"""Dry-run extraction against a target URL with a candidate SourceSpec document.

Extracts as Processor does (#317): ``resolve_dispatch_essence`` picks the media
type from the response's ``Content-Type`` (the URL's extension breaking an
ambiguous one), ``extractor_for_essence`` picks the parser, and
``canonical_text_fingerprint`` hashes the chunks. So a feed previews one line per
item, a PDF previews through the PDF extractor, and the fingerprint is the one
Processor will store. Returns chunks + total chars + the computed fingerprint so
an authoring agent can verify the spec yields the expected content before
persisting.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup
from co_core.effects.fetch import FetchContent
from co_core.pure.extract import (
    UnsupportedExtractionError,
    canonical_text_fingerprint,
    extraction_config_from_spec,
    extraction_overrides_for_essence,
    resolve_dispatch_essence,
)
from co_core.pure.extract.dispatch import extractor_for_essence
from co_core.pure.extract.html import HtmlExtractor
from co_core.pure.extract.xml_feed import XmlExtractor
from co_core_aio.fetch import AsyncFetchDriver
from soupsieve import SelectorSyntaxError

from src.core.source_spec_schema.validator import ValidationError, validate_source_spec


@dataclass(frozen=True)
class ChunkPreview:
    """Per-chunk preview for the response — keeps the contract explicit."""

    index: int
    chunk_type: str
    label: str
    text: str
    char_count: int


@dataclass(frozen=True)
class PreviewExtractionResult:
    """Result of a dry-run extraction preview."""

    chunks: list[ChunkPreview]
    total_chars: int
    fingerprint_algorithm: str
    computed_fingerprint: str
    page_title: str


class TargetUnreachableError(Exception):
    """Raised when the fetch leg of preview_extraction can't reach the target."""


class ExtractionFailedError(Exception):
    """Raised when the dispatched extractor can't parse the fetched body."""


class SourceSpecValidationError(Exception):
    """Raised when the SourceSpec document fails validation."""

    def __init__(self, errors: list[ValidationError]) -> None:
        super().__init__(f"SourceSpec validation failed: {errors}")
        self.errors = errors


def _content_type(headers: Mapping[str, str]) -> str | None:
    """The response's ``Content-Type``, whatever the header name's case."""
    return next((v for k, v in headers.items() if k.lower() == "content-type"), None)


def _page_title(content: bytes, extractor: object) -> str:
    """The first ``<title>`` of an HTML page or XML document (a feed's channel title).

    Empty for a PDF or spreadsheet, whose bytes the HTML parser would only misread.
    """
    if isinstance(extractor, XmlExtractor):
        parser = "lxml-xml"
    elif isinstance(extractor, HtmlExtractor):
        parser = "lxml"
    else:
        return ""
    title_tag = BeautifulSoup(content, parser).find("title")
    return title_tag.get_text(strip=True) if title_tag else ""


async def preview_extraction(
    driver: AsyncFetchDriver,
    url: str,
    source_spec: dict[str, Any],
) -> PreviewExtractionResult:
    """Validate the SourceSpec, fetch ``url``, extract as Processor does, and fingerprint.

    Raises:
        SourceSpecValidationError: if the document fails schema validation, or
            co-core refuses it for this body (``UnsupportedExtractionError``:
            ``css`` on XML, ``xpath`` on HTML, cannobserv#523), or its CSS
            selector doesn't parse.
        TargetUnreachableError: if the HTTP fetch fails (route layer → 422).
        ExtractionFailedError: if the extractor can't parse the body (route layer → 422).
    """
    ok, errors = validate_source_spec(source_spec)
    if not ok:
        raise SourceSpecValidationError(errors)

    try:
        fetch_result = await driver.execute(FetchContent(url))
    except httpx.HTTPError as e:
        raise TargetUnreachableError(str(e)) from e

    essence = resolve_dispatch_essence(_content_type(fetch_result.headers), url)
    extractor = extractor_for_essence(essence)
    try:
        config = extraction_config_from_spec(source_spec) | extraction_overrides_for_essence(
            essence
        )
        extraction = extractor.extract(fetch_result.content, config=config)
    except UnsupportedExtractionError as e:
        raise SourceSpecValidationError(
            [{"path": "/extraction/algorithm", "message": str(e)}]
        ) from e
    except SelectorSyntaxError as e:
        raise SourceSpecValidationError(
            [{"path": "/extraction/selector", "message": str(e)}]
        ) from e
    except ValueError as e:
        raise ExtractionFailedError(str(e)) from e

    return PreviewExtractionResult(
        chunks=[
            ChunkPreview(
                index=c.index,
                chunk_type=c.chunk_type,
                label=c.label,
                text=c.text,
                char_count=c.char_count,
            )
            for c in extraction.chunks
        ],
        total_chars=extraction.total_chars,
        fingerprint_algorithm="sha256",
        computed_fingerprint=canonical_text_fingerprint(extraction.chunks),
        page_title=_page_title(fetch_result.content, extractor),
    )
