"""Authoring tool endpoints under /api/v1/tools/*.

Non-mutating helpers that an LLM agent (or human operator) calls while
composing Information Items + SourceSpecs. Mutating CRUD lives on the existing
/api/v1/info-items and sub-resource routes.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, get_http_fetcher
from src.api.schemas.info_item import InfoItemOut
from src.api.schemas.tools import (
    ChunkPreviewOut,
    FetchAndRenderRequest,
    FetchAndRenderResult,
    PreviewExtractionRequest,
    PreviewExtractionResult,
    ProposeSelectorsRequest,
    ResolveRepFieldsRequest,
    ResolveRepFieldsResponse,
    SelectorCandidateOut,
    ValidateRepFieldsRequest,
    ValidateRepFieldsResponse,
    ValidateRepSpecRequest,
    ValidateRepSpecResponse,
    ValidateSourceSpecRequest,
    ValidateSourceSpecResponse,
    ValidationErrorOut,
)
from src.api.serializers import info_item_to_out
from src.core.rep_fields_schema.validator import (
    validate_rep_fields,
    validate_rep_fields_against_spec,
)
from src.core.rep_spec_schema.validator import validate_rep_spec
from src.core.source_spec_schema.validator import validate_source_spec
from src.core.tools.fetch_and_render import (
    HttpFetcherProtocol,
    fetch_and_render,
)
from src.core.tools.find_info_item import find_info_item
from src.core.tools.preview_extraction import (
    SourceSpecValidationError,
    TargetUnreachableError,
    preview_extraction,
)
from src.core.tools.propose_selectors import propose_selectors
from src.core.tools.resolve_rep_fields import resolve_rep_fields

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/validate-source-spec", response_model=ValidateSourceSpecResponse)
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
        errors=[ValidationErrorOut(path=e["path"], message=e["message"]) for e in errors],
    )


@router.post("/validate-rep-spec", response_model=ValidateRepSpecResponse)
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
        errors=[ValidationErrorOut(path=e["path"], message=e["message"]) for e in errors],
    )


@router.post("/validate-rep-fields", response_model=ValidateRepFieldsResponse)
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
        errors=[ValidationErrorOut(path=e["path"], message=e["message"]) for e in errors],
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
    return [info_item_to_out(item) for item in items]


@router.post("/fetch-and-render", response_model=FetchAndRenderResult)
async def fetch_and_render_route(
    body: FetchAndRenderRequest,
    fetcher: HttpFetcherProtocol = Depends(get_http_fetcher),
) -> FetchAndRenderResult:
    """Fetch a target URL and return its body + headers for downstream tools.

    Use during SourceSpec authoring to inspect what the extractor will see (e.g.
    pipe the body into ``propose_selectors`` or ``preview_extraction``). Body
    payloads larger than 5 MiB are truncated; ``truncated`` flags the case.
    ``render=True`` returns 501 until the Playwright fetcher (#3) lands.
    """
    if body.render:
        raise HTTPException(status_code=501, detail="Playwright fetcher not yet integrated (#3)")
    result = await fetch_and_render(fetcher, str(body.url), render=False)
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
    fetcher: HttpFetcherProtocol = Depends(get_http_fetcher),
) -> PreviewExtractionResult:
    """Validate, fetch, extract, and fingerprint with a candidate SourceSpec.

    Composes ``validate_source_spec`` + ``fetch_and_render`` + the HTML extractor
    + the spec's fingerprint algorithm so an authoring agent can verify the
    spec yields the expected content before persisting.

    The URL is read from ``source_spec["target"]["url"]``.

    Returns 422 with structured errors on schema validation failure
    (``error: "validation_failed"``) or target unreachability
    (``error: "target_unreachable"``).
    """
    try:
        result = await preview_extraction(fetcher, body.source_spec)
    except SourceSpecValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "validation_failed",
                "errors": [{"path": err["path"], "message": err["message"]} for err in e.errors]
                or [{"path": "", "message": str(e)}],
            },
        ) from e
    except TargetUnreachableError as e:
        raise HTTPException(
            status_code=422,
            detail={"error": "target_unreachable", "message": str(e)},
        ) from e

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
    )


@router.post("/propose-selectors", response_model=list[SelectorCandidateOut])
async def propose_selectors_route(
    body: ProposeSelectorsRequest,
    fetcher: HttpFetcherProtocol = Depends(get_http_fetcher),
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
    candidates = await propose_selectors(fetcher, str(body.url), body.description, top_k=body.top_k)
    return [
        SelectorCandidateOut(
            selector=c.selector,
            sample_text=c.sample_text,
            stability_score=c.stability_score,
        )
        for c in candidates
    ]
