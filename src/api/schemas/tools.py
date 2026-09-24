"""Pydantic request/response schemas for /api/v1/tools/* endpoints."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import Path
from pydantic import AfterValidator, BaseModel, Field, HttpUrl

from src.api.errors import FieldError
from src.api.schemas.types import ULIDStr
from src.core.changes.dlq_triage import (
    STREAM_ID_PATTERN,
    TRIAGE_DLQS,
    ParkedAs,
    ReprocessOutcome,
    is_exact_stream_id,
)
from src.core.changes.outbox_triage import RearmOutcome

# ---------------------------------------------------------------------------
# validate-source-spec
# ---------------------------------------------------------------------------


class ValidateSourceSpecRequest(BaseModel):
    """Request body for POST /api/v1/tools/validate-source-spec."""

    document: dict[str, Any] = Field(
        description="The SourceSpec document to validate against the v1 JSON Schema."
    )


class ValidateSourceSpecResponse(BaseModel):
    """Response body for POST /api/v1/tools/validate-source-spec."""

    valid: bool = Field(description="True iff the document passed schema validation.")
    errors: list[FieldError] = Field(
        default_factory=list,
        description="Per-field validation issues; empty when ``valid`` is True.",
    )


# ---------------------------------------------------------------------------
# validate-rep-spec
# ---------------------------------------------------------------------------


class ValidateRepSpecRequest(BaseModel):
    """Request body for POST /api/v1/tools/validate-rep-spec."""

    document: dict[str, Any] = Field(
        description="The RepSpec document to validate against the v1 JSON Schema."
    )


class ValidateRepSpecResponse(BaseModel):
    """Response body for POST /api/v1/tools/validate-rep-spec."""

    valid: bool = Field(description="True iff the document passed schema validation.")
    errors: list[FieldError] = Field(
        default_factory=list,
        description="Per-field validation issues; empty when ``valid`` is True.",
    )


# ---------------------------------------------------------------------------
# validate-watch-spec
# ---------------------------------------------------------------------------


class ValidateWatchSpecRequest(BaseModel):
    """Request body for POST /api/v1/tools/validate-watch-spec."""

    document: dict[str, Any] = Field(
        description="The WatchSpec document to validate against the v1 JSON Schema."
    )


class ValidateWatchSpecResponse(BaseModel):
    """Response body for POST /api/v1/tools/validate-watch-spec."""

    valid: bool = Field(description="True iff the document passed schema validation.")
    errors: list[FieldError] = Field(
        default_factory=list,
        description="Per-field validation issues; empty when ``valid`` is True.",
    )


# ---------------------------------------------------------------------------
# validate-rep-fields
# ---------------------------------------------------------------------------


class ValidateRepFieldsRequest(BaseModel):
    """Request body for POST /api/v1/tools/validate-rep-fields."""

    bag: dict[str, Any] = Field(description="The rep_fields bag to validate.")
    required_fields: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of 'ns.key' paths that must be present and non-null. "
            "When omitted, only the bag's shape is validated."
        ),
    )


class ValidateRepFieldsResponse(BaseModel):
    """Response body for POST /api/v1/tools/validate-rep-fields."""

    valid: bool = Field(description="True iff the bag passed validation.")
    errors: list[FieldError] = Field(
        default_factory=list,
        description="Per-field validation issues; empty when ``valid`` is True.",
    )


# ---------------------------------------------------------------------------
# resolve-rep-fields
# ---------------------------------------------------------------------------


class ResolveRepFieldsRequest(BaseModel):
    """Request body for POST /api/v1/tools/resolve-rep-fields."""

    bag: dict[str, Any] = Field(description="Raw rep_fields bag to enrich with slug companions.")


class ResolveRepFieldsResponse(BaseModel):
    """Response body for POST /api/v1/tools/resolve-rep-fields."""

    bag: dict[str, Any] = Field(description="The slug-enriched bag after resolution.")


# ---------------------------------------------------------------------------
# fetch-and-render
# ---------------------------------------------------------------------------


class FetchAndRenderRequest(BaseModel):
    """Request body for POST /api/v1/tools/fetch-and-render."""

    url: HttpUrl = Field(description="Target URL to fetch (http/https only).")
    render: bool = Field(
        default=False,
        description=(
            "If True, render the page via Playwright before returning. v1 returns "
            "501 — wired in once the Playwright fetcher (#3) lands."
        ),
    )


class FetchAndRenderResult(BaseModel):
    """Response body for POST /api/v1/tools/fetch-and-render."""

    url: str = Field(description="Echo of the requested URL.")
    status_code: int = Field(description="HTTP status code from the target.")
    headers: dict[str, str] = Field(description="Response headers from the target.")
    body: str = Field(
        description=(
            "Decoded response body, truncated at 5 MiB. ``truncated`` is True when "
            "the original payload exceeded the cap."
        )
    )
    body_bytes_total: int = Field(
        description="Original byte count before any truncation; useful for size sanity checks."
    )
    truncated: bool = Field(description="True when ``body`` was truncated to the 5 MiB cap.")
    screenshot_url: str | None = Field(
        default=None,
        description=(
            "Reserved for the Playwright fetcher path; always None in v1 since "
            "screenshot capture isn't wired."
        ),
    )


# ---------------------------------------------------------------------------
# preview-extraction
# ---------------------------------------------------------------------------


class PreviewExtractionRequest(BaseModel):
    """Request body for POST /api/v1/tools/preview-extraction."""

    url: str = Field(description="URL to fetch.")
    source_spec: dict[str, Any] = Field(
        description=(
            "Candidate SourceSpec document (schema_version, extraction, fingerprint). "
            "Validated against the v1 schema before any fetch is attempted; a validation "
            "failure returns 422 with the per-field issue list."
        )
    )


class ChunkPreviewOut(BaseModel):
    """One chunk in the preview response."""

    index: int = Field(description="Position of the chunk in extraction order.")
    chunk_type: str = Field(description="Algorithm-specific type tag (e.g. 'page', 'section').")
    label: str = Field(description="Operator-readable chunk identifier.")
    text: str = Field(description="Extracted chunk text.")
    char_count: int = Field(description="Character count of ``text``.")


class PreviewExtractionResult(BaseModel):
    """Response body for POST /api/v1/tools/preview-extraction."""

    chunks: list[ChunkPreviewOut] = Field(
        description="Extracted chunks in order; empty when extraction yields nothing."
    )
    total_chars: int = Field(description="Sum of ``char_count`` across all chunks.")
    fingerprint_algorithm: str = Field(
        description="Algorithm used for ``computed_fingerprint`` (mirrors the spec)."
    )
    computed_fingerprint: str = Field(
        description=(
            "Fingerprint of the joined extracted text under the spec's algorithm. "
            "sha256 → 64-char hex; simhash → decimal int as a string."
        )
    )
    page_title: str = Field(
        description=(
            "Value of the HTML <title> element extracted from the full document "
            "before any CSS/XPath selector narrows scope. Empty string when absent."
        )
    )


# ---------------------------------------------------------------------------
# propose-selectors
# ---------------------------------------------------------------------------


class ProposeSelectorsRequest(BaseModel):
    """Request body for POST /api/v1/tools/propose-selectors."""

    url: HttpUrl = Field(description="Target URL to fetch and search.")
    description: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Plain-language description of the content the operator wants to "
            "extract. Matched against element text via case-insensitive "
            "substring search."
        ),
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=25,
        description="Maximum candidates to return; ranked by stability score (highest first).",
    )


class SelectorCandidateOut(BaseModel):
    """One ranked selector candidate."""

    selector: str = Field(description="CSS selector for the proposed element.")
    sample_text: str = Field(
        description="Visible text from the matched element (truncated to 200 chars)."
    )
    stability_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Heuristic score in [0, 1]: higher == more stable. Combines id/class "
            "structure, text-length proximity to the description, and a volatility "
            "penalty for hash-looking class names."
        ),
    )


class RepublishRegistryResponse(BaseModel):
    """Response body for POST /api/v1/tools/republish-registry-announcements."""

    triggered: bool = Field(
        description="True — the snapshot loop was signalled; the publish itself "
        "happens asynchronously on the loop's task (202 semantics)."
    )


# ---------------------------------------------------------------------------
# dead-letters (archiver#238)
# ---------------------------------------------------------------------------


def _validate_triage_dlq(value: str) -> str:
    """Path validator: a queue outside ``TRIAGE_DLQS`` is a 422, never a read."""
    if value not in TRIAGE_DLQS:
        raise ValueError(f"not a dead-letter queue archiver triages; expected one of {TRIAGE_DLQS}")
    return value


def _validate_stream_id(value: str) -> str:
    """Item validator: the uint64 bound ``pattern`` cannot state (a 422, not a 503)."""
    if not is_exact_stream_id(value):
        raise ValueError("not an exact stream id: each half of <ms>-<seq> is a uint64")
    return value


TriageDlqStr = Annotated[
    str,
    AfterValidator(_validate_triage_dlq),
    Path(
        description="The dead-letter queue, by its key as broker names it: "
        + " or ".join(f"`{dlq}`" for dlq in TRIAGE_DLQS)
        + ". Any other key is a 422."
    ),
]
"""A path segment naming one of ``TRIAGE_DLQS``. The ``Path`` description is how
OpenAPI, and so the SDK, learns the two legal values."""


class DeadLetterProvenanceOut(BaseModel):
    """What `dead_letter` recorded about an entry (co-core >= 0.19.1, cannobserv#474).

    Every field is null on an entry written before that.
    """

    source_id: str | None = Field(description="The original entry's id on the source stream.")
    group: str | None = Field(description="The consumer group that parked it.")
    consumer: str | None = Field(description="The consumer within that group.")
    reason: str | None = Field(
        description="Why it was parked. Archiver's own start `handler poison: ` or "
        "`undecodable: `, then the error; capped at 2000 characters."
    )


class DeadLetterOut(BaseModel):
    """One entry of a dead-letter queue, described for triage."""

    entry_id: str = Field(description="The entry's stream id in the DLQ; what discard takes.")
    dead_lettered_at: datetime = Field(
        description="When the entry was dead-lettered, from its stream id. On an entry with "
        "no provenance, the way back to the journald line that says why."
    )
    fields: dict[str, str] = Field(
        description="The raw entry: the wire fields `dead_letter` copied, plus its `dlq.*` "
        "provenance fields."
    )
    event_type: str | None = Field(description="The frame's `event_type` field, if it has one.")
    decodes: bool = Field(
        description="Whether the frame decodes against the running co-core. True on an entry "
        "that failed to decode when it was parked is the version-skew case."
    )
    decode_error: str | None = Field(description="Why it does not decode; null when it does.")
    provenance: DeadLetterProvenanceOut
    parked_as: ParkedAs | None = Field(
        description="Which quarantine path parked it, read off the reason's prefix. "
        "`handler_poison` decoded and still failed: discard. `undecodable` with `decodes` "
        "true is version skew: reprocess. Null with no reason, or one archiver did not write."
    )
    owned: bool = Field(
        description="Whether archiver's own group for this queue's topic parked it. A fact "
        "stream's DLQ is shared by every consuming service; only owned entries are archiver's "
        "to reprocess."
    )


StreamIdList = Annotated[
    list[Annotated[str, Field(pattern=STREAM_ID_PATTERN), AfterValidator(_validate_stream_id)]],
    Field(min_length=1, max_length=500),
]
"""1-500 exact stream ids. Each request names what its route does with them."""


class DiscardDeadLettersRequest(BaseModel):
    """Request body for POST /api/v1/tools/dead-letters/{dlq}/discard."""

    entry_ids: StreamIdList = Field(
        description="Exact stream ids (`<ms>-<seq>`, each half a uint64) to delete. A range or "
        "bare timestamp is refused: XRANGE would read it as more entries than were named.",
    )


class ReprocessDeadLettersRequest(BaseModel):
    """Request body for POST /api/v1/tools/dead-letters/{dlq}/reprocess."""

    entry_ids: StreamIdList = Field(
        description="Exact stream ids (`<ms>-<seq>`, each half a uint64) to reprocess. Each "
        "owned entry runs through the queue's own handler, and only one the handler settles "
        "is removed. A range or bare timestamp is refused: XRANGE would read it as more "
        "entries than were named.",
    )


class ReprocessResultOut(BaseModel):
    """What happened to one requested entry. Only `reprocessed` removed it."""

    entry_id: str
    outcome: ReprocessOutcome = Field(
        description="`reprocessed`: the handler settled it and it was deleted. `not_owned`: "
        "another group parked it, or it has no provenance. `undecodable`: still does not "
        "decode. `rejected`: the handler's poison - discard it. `failed`: any other handler "
        "error, e.g. the database down - retry. `deferred`: the handler asked for redelivery."
    )
    detail: str | None = Field(
        description="Why it stayed: the parking group, or the error. Null when it did not."
    )


class ReprocessDeadLettersResponse(BaseModel):
    """Response body for POST /api/v1/tools/dead-letters/{dlq}/reprocess."""

    results: list[ReprocessResultOut] = Field(description="One per distinct id, in request order.")


class DiscardDeadLettersResponse(BaseModel):
    """Response body for POST /api/v1/tools/dead-letters/{dlq}/discard."""

    discarded: list[str] = Field(description="Ids deleted, each logged in full to journald first.")
    not_found: list[str] = Field(description="Ids that were not in the queue.")


# ---------------------------------------------------------------------------
# outbox/dead-lettered (archiver#191)
# ---------------------------------------------------------------------------


class DeadLetteredOutboxRowOut(BaseModel):
    """One dead-lettered ``changes_outbox`` row, described for triage."""

    row_id: str = Field(description="The outbox row's ULID; what discard and rearm take.")
    topic: str = Field(description="The stream the row was bound for.")
    event_type: str | None = Field(description="The payload's `event_type`, if it has one.")
    payload: Any = Field(
        description="The stored payload, as the publisher saw it. Usually an object, but a "
        "non-object payload is one of the poison cases, so it is returned as stored."
    )
    last_error: str | None = Field(
        description="Why it was dead-lettered, capped at 1000 characters. The full "
        "traceback is on the journald line `Dead-lettering outbox row`, while retention lasts."
    )
    publish_attempts: int = Field(description="Failed attempts before it was dead-lettered.")
    created_at: datetime
    dead_lettered_at: datetime
    rearmable: bool = Field(
        description="Whether its topic may go back to the drain. Only `info.changes` does: "
        "`info.registry` is repaired by the hourly snapshot, and a late `content.replicate` "
        "command may already be abandoned. Discard the rest."
    )


RowIdList = Annotated[list[ULIDStr], Field(min_length=1, max_length=500)]
"""1-500 outbox row ULIDs. Each request names what its route does with them."""


class DiscardOutboxRowsRequest(BaseModel):
    """Request body for POST /api/v1/tools/outbox/dead-lettered/discard."""

    row_ids: RowIdList = Field(
        description="Dead-lettered row ids to delete. A live or published row is never "
        "deleted; it comes back in `not_found`."
    )


class DiscardOutboxRowsResponse(BaseModel):
    """Response body for POST /api/v1/tools/outbox/dead-lettered/discard."""

    discarded: list[str] = Field(description="Ids deleted, each logged in full to journald first.")
    not_found: list[str] = Field(
        description="Ids that are not a dead-lettered row: unknown, live, or published."
    )


class RearmOutboxRowsRequest(BaseModel):
    """Request body for POST /api/v1/tools/outbox/dead-lettered/rearm."""

    row_ids: RowIdList = Field(
        description="Dead-lettered row ids to return to the drain's queue. Fix the cause first: "
        "a rearmed row that fails the same way dead-letters again."
    )


class RearmResultOut(BaseModel):
    """What happened to one requested row. Only `rearmed` changed it."""

    row_id: str
    outcome: RearmOutcome = Field(
        description="`rearmed`: back in the drain's queue, attempts reset. `not_found`: not a "
        "dead-lettered row. `refused`: its topic is not rearmable - discard it. `rejected`: "
        "its payload still does not build against the running co-core - discard it."
    )
    detail: str | None = Field(description="Why it stayed; null when it did not.")


class RearmOutboxRowsResponse(BaseModel):
    """Response body for POST /api/v1/tools/outbox/dead-lettered/rearm."""

    results: list[RearmResultOut] = Field(description="One per distinct id, in request order.")
