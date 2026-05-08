"""Dry-run extraction against a target URL with a candidate SourceSpec document.

Composes ``fetch_and_render`` + ``HtmlExtractor`` + ``extraction_config_from_spec``
+ a SHA-256 fingerprint. Returns chunks + total chars + the computed fingerprint
so an authoring agent can verify the spec yields the expected content before
persisting.

The URL is taken from ``source_spec["target"]["url"]`` — callers no longer pass
it separately.
"""

import hashlib
from dataclasses import dataclass
from typing import Any

import httpx

from src.core.extraction_defaults import extraction_config_from_spec
from src.core.extractors import HtmlExtractor
from src.core.source_spec_schema.validator import (
    ValidationError,
    validate_root_source_spec,
)
from src.core.tools.fetch_and_render import HttpFetcherProtocol


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


class TargetUnreachableError(Exception):
    """Raised when the fetch leg of preview_extraction can't reach the target."""


class SourceSpecValidationError(Exception):
    """Raised when the SourceSpec document fails validation.

    ``errors`` carries the structured per-field issue list from
    ``validate_root_source_spec``.
    """

    def __init__(self, errors: list[ValidationError]) -> None:
        super().__init__(f"SourceSpec validation failed: {errors}")
        self.errors = errors


def _compute_fingerprint(text: str) -> str:
    """Compute SHA-256 over ``text`` and return as ``sha256:<hex>``."""
    hex_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{hex_digest}"


async def preview_extraction(
    fetcher: HttpFetcherProtocol,
    source_spec: dict[str, Any],
) -> PreviewExtractionResult:
    """Validate the SourceSpec, fetch its target URL, extract, and fingerprint.

    The URL is read from ``source_spec["target"]["url"]``.

    Raises:
        SourceSpecValidationError: if the document fails ``validate_root_source_spec``.
        TargetUnreachableError: if the HTTP fetch fails (route layer → 422).
    """
    ok, errors = validate_root_source_spec(source_spec)
    if not ok:
        raise SourceSpecValidationError(errors)

    url = source_spec["target"]["url"]

    try:
        fetch_result = await fetcher.fetch(url)
    except httpx.HTTPError as e:
        raise TargetUnreachableError(str(e)) from e

    config = extraction_config_from_spec(source_spec)
    extractor = HtmlExtractor()
    extraction = await extractor.extract(fetch_result.content, config=config)

    joined_text = "\n".join(c.text for c in extraction.chunks)
    computed_fingerprint = _compute_fingerprint(joined_text)

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
        computed_fingerprint=computed_fingerprint,
    )
