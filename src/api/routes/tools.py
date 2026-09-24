"""Authoring tool endpoints under /api/v1/tools/*.

Non-mutating helpers that an LLM agent (or human operator) calls while
composing Information Items + SourceSpecs. Mutating CRUD lives on the existing
/api/v1/info-items and sub-resource routes. The exceptions are operator bus
controls: the registry republish trigger, and DLQ triage (archiver#238).
"""

import os
from typing import TYPE_CHECKING

from co_core_aio.fetch import AsyncFetchDriver
from fastapi import APIRouter, Depends, Query, Request
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.api.deps import (
    get_db_session,
    get_db_session_factory,
    get_fetch_driver,
    get_redis_client,
)
from src.api.errors import FieldError, raise_422, raise_envelope
from src.api.schemas.info_item import InfoItemOut
from src.api.schemas.pagination import Page
from src.api.schemas.tools import (
    ChunkPreviewOut,
    DeadLetterOut,
    DiscardDeadLettersRequest,
    DiscardDeadLettersResponse,
    FetchAndRenderRequest,
    FetchAndRenderResult,
    PreviewExtractionRequest,
    PreviewExtractionResult,
    ProposeSelectorsRequest,
    ReprocessDeadLettersRequest,
    ReprocessDeadLettersResponse,
    ReprocessResultOut,
    RepublishRegistryResponse,
    ResolveRepFieldsRequest,
    ResolveRepFieldsResponse,
    SelectorCandidateOut,
    TriageDlqStr,
    ValidateRepFieldsRequest,
    ValidateRepFieldsResponse,
    ValidateRepSpecRequest,
    ValidateRepSpecResponse,
    ValidateSourceSpecRequest,
    ValidateSourceSpecResponse,
    ValidateWatchSpecRequest,
    ValidateWatchSpecResponse,
)
from src.api.serializers import info_item_to_out
from src.core.changes.dlq_triage import (
    DiscardInterruptedError,
    ReprocessInterruptedError,
    discard_dead_letters,
    list_dead_letters,
    reprocess_dead_letters,
)
from src.core.rep_fields import resolve_rep_fields
from src.core.rep_fields_schema.validator import (
    validate_rep_fields,
    validate_rep_fields_against_spec,
)
from src.core.rep_spec_schema.validator import validate_rep_spec
from src.core.source_spec_schema.validator import validate_source_spec
from src.core.tools.fetch_and_render import fetch_and_render
from src.core.tools.find_info_item import find_info_item
from src.core.tools.preview_extraction import (
    SourceSpecValidationError,
    TargetUnreachableError,
    preview_extraction,
)
from src.core.tools.propose_selectors import propose_selectors
from src.core.watch_spec_schema.validator import validate_watch_spec

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisAsync

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post(
    "/validate-source-spec",
    response_model=ValidateSourceSpecResponse,
    response_model_exclude_none=True,
)
async def validate_source_spec_route(
    body: ValidateSourceSpecRequest,
) -> ValidateSourceSpecResponse:
    """Validate a SourceSpec document against the v1 JSON Schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues. This
    differs from create/patch routes (which return 422 on invalid input);
    here, validation IS the purpose, so the result is the response.
    """
    ok, errors = validate_source_spec(body.document)
    return ValidateSourceSpecResponse(
        valid=ok,
        errors=[FieldError(path=e["path"], message=e["message"]) for e in errors],
    )


@router.post(
    "/validate-rep-spec",
    response_model=ValidateRepSpecResponse,
    response_model_exclude_none=True,
)
async def validate_rep_spec_route(
    body: ValidateRepSpecRequest,
) -> ValidateRepSpecResponse:
    """Validate a RepSpec document against the v1 envelope + provider sub-schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues.
    """
    ok, errors = validate_rep_spec(body.document)
    return ValidateRepSpecResponse(
        valid=ok,
        errors=[FieldError(path=e["path"], message=e["message"]) for e in errors],
    )


@router.post(
    "/validate-rep-fields",
    response_model=ValidateRepFieldsResponse,
    response_model_exclude_none=True,
)
async def validate_rep_fields_route(
    body: ValidateRepFieldsRequest,
) -> ValidateRepFieldsResponse:
    """Validate a rep_fields bag against the v1 schema and optional required_fields list.

    When ``required_fields`` is supplied, also checks that every 'ns.key' path
    resolves to a non-null value in the bag. Always returns 200 — validation is
    the purpose.
    """
    if body.required_fields is not None:
        ok, errors = validate_rep_fields_against_spec(body.bag, body.required_fields)
    else:
        ok, errors = validate_rep_fields(body.bag)
    return ValidateRepFieldsResponse(
        valid=ok,
        errors=[FieldError(path=e["path"], message=e["message"]) for e in errors],
    )


@router.post("/resolve-rep-fields", response_model=ResolveRepFieldsResponse)
async def resolve_rep_fields_route(
    body: ResolveRepFieldsRequest,
) -> ResolveRepFieldsResponse:
    """Enrich a raw rep_fields bag with slug companions and acronym_or_title derivations.

    Idempotent: existing ``_slug`` keys are preserved. Unknown namespaces and
    non-string values pass through unchanged.
    """
    resolved = resolve_rep_fields(body.bag)
    return ResolveRepFieldsResponse(bag=resolved)


@router.get("/find-info-items", response_model=list[InfoItemOut])
async def find_info_items_route(
    q: str = Query(
        min_length=1,
        description="Substring matched against name + description (case-insensitive).",
    ),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum matches to return."),
    session: AsyncSession = Depends(get_db_session),
) -> list[InfoItemOut]:
    """Search Information Items by name or description (substring, case-insensitive).

    Use this *before* ``create_info_item`` to avoid duplicating an existing
    Information Item. Returns up to ``limit`` matches, newest first.
    """
    items = await find_info_item(session, q, limit=limit)
    base_url = os.environ.get("ARCHIVER_PUBLIC_BASE_URL")
    return [info_item_to_out(item, base_url=base_url) for item in items]


@router.post("/fetch-and-render", response_model=FetchAndRenderResult)
async def fetch_and_render_route(
    body: FetchAndRenderRequest,
    driver: AsyncFetchDriver = Depends(get_fetch_driver),
) -> FetchAndRenderResult:
    """Fetch a target URL and return its body + headers for downstream tools.

    Use during SourceSpec authoring to inspect what the extractor will see (e.g.
    pipe the body into ``propose_selectors`` or ``preview_extraction``). Body
    payloads larger than 5 MiB are truncated; ``truncated`` flags the case.
    ``render=True`` returns 501 until the Playwright fetcher (#3) lands.
    """
    if body.render:
        raise_envelope(501, "unimplemented", "Playwright fetcher not yet integrated (#3)")
    result = await fetch_and_render(driver, str(body.url), render=False)
    return FetchAndRenderResult(
        url=result.url,
        status_code=result.status_code,
        headers=result.headers,
        body=result.body,
        body_bytes_total=result.body_bytes_total,
        truncated=result.truncated,
        screenshot_url=result.screenshot_url,
    )


@router.post("/preview-extraction", response_model=PreviewExtractionResult)
async def preview_extraction_route(
    body: PreviewExtractionRequest,
    driver: AsyncFetchDriver = Depends(get_fetch_driver),
) -> PreviewExtractionResult:
    """Validate, fetch, extract, and fingerprint with a candidate SourceSpec.

    Composes ``validate_source_spec`` + ``fetch_and_render`` + the HTML extractor
    + the spec's fingerprint algorithm so an authoring agent can verify the
    spec yields the expected content before persisting.

    Returns 422 with the standard error envelope; ``code`` on each FieldError
    disambiguates (``target_unreachable``, etc.).
    """
    try:
        result = await preview_extraction(driver, body.url, body.source_spec)
    except SourceSpecValidationError as e:
        raise_422(
            "source_spec validation failed",
            kind="schema",
            errors=[FieldError(path=err["path"] or "", message=err["message"]) for err in e.errors]
            or [FieldError(path="", message=str(e))],
            source_exc=e,
        )
    except TargetUnreachableError as e:
        raise_422(
            str(e),
            kind="domain",
            errors=[FieldError(path="/url", message=str(e), code="target_unreachable")],
            source_exc=e,
        )

    return PreviewExtractionResult(
        chunks=[
            ChunkPreviewOut(
                index=c.index,
                chunk_type=c.chunk_type,
                label=c.label,
                text=c.text,
                char_count=c.char_count,
            )
            for c in result.chunks
        ],
        total_chars=result.total_chars,
        fingerprint_algorithm=result.fingerprint_algorithm,
        computed_fingerprint=result.computed_fingerprint,
        page_title=result.page_title,
    )


@router.post("/propose-selectors", response_model=list[SelectorCandidateOut])
async def propose_selectors_route(
    body: ProposeSelectorsRequest,
    driver: AsyncFetchDriver = Depends(get_fetch_driver),
) -> list[SelectorCandidateOut]:
    """Suggest CSS selector candidates for content matching ``description``.

    v1 returns CSS selectors only — pair with ``extraction.algorithm: "css"``
    in the resulting SourceSpec. XPath / JSONPath / regex / full_page proposers
    are on the roadmap; track via #148.

    Heuristic v1: substring match + specificity + text-length proximity +
    volatility penalty (hash-looking class names get demoted). Empty match
    set returns ``[]``. Operators always verify the chosen selector via
    ``preview_extraction`` before persisting a SourceSpec.
    """
    candidates = await propose_selectors(driver, str(body.url), body.description, top_k=body.top_k)
    return [
        SelectorCandidateOut(
            selector=c.selector,
            sample_text=c.sample_text,
            stability_score=c.stability_score,
        )
        for c in candidates
    ]


@router.post(
    "/validate-watch-spec",
    response_model=ValidateWatchSpecResponse,
    response_model_exclude_none=True,
)
async def validate_watch_spec_route(
    body: ValidateWatchSpecRequest,
) -> ValidateWatchSpecResponse:
    """Validate a WatchSpec document against the v1 JSON Schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues.
    """
    ok, errors = validate_watch_spec(body.document)
    return ValidateWatchSpecResponse(
        valid=ok,
        errors=[FieldError(path=e["path"], message=e["message"]) for e in errors],
    )


@router.post(
    "/republish-registry-announcements",
    status_code=202,
    response_model=RepublishRegistryResponse,
)
async def republish_registry_announcements_route(request: Request) -> RepublishRegistryResponse:
    """Trigger an immediate full-set republish on ``info.registry`` (archiver#141).

    The operator's "republish now": sets the event the snapshot loop waits on,
    so the publish happens on the loop's task — 202, never blocking an HTTP
    worker on a full-set publish. 409 when the bus is dormant (no
    ``ARCHIVER_REDIS_URL``, e.g. the dev server): a silent 202 that never
    publishes would read as success.
    """
    trigger = getattr(request.app.state, "registry_snapshot_trigger", None)
    if trigger is None:
        raise_envelope(
            409,
            "conflict",
            "registry snapshot loop is not running (bus dormant — no ARCHIVER_REDIS_URL)",
        )
    trigger.set()
    return RepublishRegistryResponse(triggered=True)


def _require_bus(redis: "RedisAsync | None") -> "RedisAsync":
    """409 when bus-dormant: an empty listing would read as a clean queue."""
    if redis is None:
        raise_envelope(409, "conflict", "no broker client (bus dormant — no ARCHIVER_REDIS_URL)")
    return redis


@router.get("/dead-letters/{dlq}", response_model=Page[DeadLetterOut])
async def list_dead_letters_route(
    dlq: TriageDlqStr,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=2**63 - 1),
    redis: "RedisAsync | None" = Depends(get_redis_client),
) -> Page[DeadLetterOut]:
    """List one of archiver's two DLQs, oldest first, for triage (archiver#238).

    Each entry is tried against the running co-core, so ``decodes`` answers the
    version-skew question. 503 when the broker cannot be read, distinct from an
    empty page.
    """
    client = _require_bus(redis)
    try:
        entries, has_more = await list_dead_letters(client, dlq, limit=limit, offset=offset)
    except (RedisError, OSError) as e:
        raise_envelope(503, "server", f"broker read failed: {type(e).__name__}", source_exc=e)
    return Page[DeadLetterOut](
        items=[DeadLetterOut.model_validate(entry, from_attributes=True) for entry in entries],
        has_more=has_more,
        limit=limit,
        offset=offset,
    )


@router.post("/dead-letters/{dlq}/discard", response_model=DiscardDeadLettersResponse)
async def discard_dead_letters_route(
    dlq: TriageDlqStr,
    body: DiscardDeadLettersRequest,
    redis: "RedisAsync | None" = Depends(get_redis_client),
) -> DiscardDeadLettersResponse:
    """Delete the named entries from one of archiver's two DLQs (archiver#238).

    ``XDEL`` by id, each frame logged in full to journald first. Ids not in the
    queue come back in ``not_found`` rather than failing the request, so a
    retried discard is harmless. A broker failure part-way through is a 503 whose
    ``data`` carries ``discarded``, ``not_found`` and ``in_doubt`` (the id whose
    delete was in flight, or null): the progress a retry could not reconstruct.
    """
    client = _require_bus(redis)
    try:
        result = await discard_dead_letters(client, dlq, body.entry_ids)
    except DiscardInterruptedError as e:
        raise_envelope(
            503,
            "server",
            str(e),
            data={
                "discarded": list(e.discarded),
                "not_found": list(e.not_found),
                "in_doubt": e.in_doubt,
            },
            source_exc=e,
        )
    return DiscardDeadLettersResponse(
        discarded=list(result.discarded), not_found=list(result.not_found)
    )


@router.post("/dead-letters/{dlq}/reprocess", response_model=ReprocessDeadLettersResponse)
async def reprocess_dead_letters_route(
    dlq: TriageDlqStr,
    body: ReprocessDeadLettersRequest,
    redis: "RedisAsync | None" = Depends(get_redis_client),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_db_session_factory),
) -> ReprocessDeadLettersResponse:
    """Run the named entries through the queue's own handler (archiver#238).

    The handler is the one the consumer loop runs, so an entry is decided exactly
    as a live delivery would be; only a settled one is ``XDEL``ed, after its frame
    is logged. An entry another group parked, or one with no provenance, is left
    alone. Every outcome is per entry, in request order. A broker failure
    part-way through is a 503 whose ``data`` carries ``results`` so far and
    ``in_doubt`` (the id whose delete was in flight, its handler already
    committed; or null).
    """
    client = _require_bus(redis)
    try:
        results = await reprocess_dead_letters(
            client, dlq, body.entry_ids, session_factory=session_factory
        )
    except ReprocessInterruptedError as e:
        raise_envelope(
            503,
            "server",
            str(e),
            data={
                "results": [
                    ReprocessResultOut.model_validate(r, from_attributes=True).model_dump()
                    for r in e.results
                ],
                "in_doubt": e.in_doubt,
            },
            source_exc=e,
        )
    return ReprocessDeadLettersResponse(
        results=[ReprocessResultOut.model_validate(r, from_attributes=True) for r in results]
    )
