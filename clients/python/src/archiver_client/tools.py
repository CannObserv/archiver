"""Hand-written wrappers for /api/v1/tools/* endpoints.

Mixed into ``ArchiverClient`` via composition in ``client.py``. These
endpoints are reached via the generated client's underlying httpx instance
so callers get a stable high-level API regardless of openapi-python-client
regen cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from archiver_client.errors import error_from_response
from archiver_client.generated.models.info_item_out import InfoItemOut

if TYPE_CHECKING:
    from archiver_client.client import ArchiverClient


@dataclass(frozen=True)
class ValidationIssue:
    """One validation problem with a structured path + message."""

    path: list[str | int]
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of a validate_* call."""

    valid: bool
    errors: list[ValidationIssue]


async def _post_json(
    client_facade: ArchiverClient, path: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Send a JSON POST through the generated client's httpx instance.

    Returns the parsed JSON body on 2xx; raises a typed ``ArchiverClientError``
    subclass otherwise.
    """
    httpx_client = client_facade._gen_client.get_async_httpx_client()
    response = await httpx_client.post(path, json=body)
    if 200 <= response.status_code < 300:
        return response.json()
    raise error_from_response(int(response.status_code), response.content)


async def _get_json(
    client_facade: ArchiverClient, path: str, params: dict[str, Any] | None = None
) -> Any:
    """GET counterpart of ``_post_json``."""
    httpx_client = client_facade._gen_client.get_async_httpx_client()
    response = await httpx_client.get(path, params=params or {})
    if 200 <= response.status_code < 300:
        return response.json()
    raise error_from_response(int(response.status_code), response.content)


def _parse_validation_result(body: dict[str, Any]) -> ValidationResult:
    """Shared parser for validate_* responses (same shape for all three endpoints)."""
    return ValidationResult(
        valid=bool(body["valid"]),
        errors=[
            ValidationIssue(path=list(e["path"]), message=str(e["message"]))
            for e in body.get("errors", [])
        ],
    )


# --- Authoring tool functions ---


async def validate_source_spec(
    client_facade: ArchiverClient, document: dict[str, Any]
) -> ValidationResult:
    """Validate a SourceSpec document against the v1 JSON Schema."""
    body = await _post_json(
        client_facade, "/api/v1/tools/validate-source-spec", {"document": document}
    )
    return _parse_validation_result(body)


async def validate_rep_spec(
    client_facade: ArchiverClient, document: dict[str, Any]
) -> ValidationResult:
    """Validate a RepSpec document against the v1 JSON Schema."""
    body = await _post_json(
        client_facade, "/api/v1/tools/validate-rep-spec", {"document": document}
    )
    return _parse_validation_result(body)


async def validate_rep_fields(
    client_facade: ArchiverClient,
    bag: dict[str, Any],
    *,
    required_fields: list[str] | None = None,
) -> ValidationResult:
    """Validate a rep_fields bag; optionally check required 'ns.key' paths."""
    payload: dict[str, Any] = {"bag": bag}
    if required_fields is not None:
        payload["required_fields"] = required_fields
    body = await _post_json(client_facade, "/api/v1/tools/validate-rep-fields", payload)
    return _parse_validation_result(body)


async def resolve_rep_fields(client_facade: ArchiverClient, bag: dict[str, Any]) -> dict[str, Any]:
    """Enrich a raw rep_fields bag with slug companions.

    Returns the resolved bag dict (the ``bag`` key from the response body).
    """
    body = await _post_json(client_facade, "/api/v1/tools/resolve-rep-fields", {"bag": bag})
    return dict(body.get("bag", {}))


async def find_info_item(
    client_facade: ArchiverClient, query: str, *, limit: int = 20
) -> list[InfoItemOut]:
    """Search Information Items by name + description (case-insensitive substring).

    Returns a list of ``InfoItemOut`` instances so callers get the same typed
    shape as ``list_info_items``. Use before ``create_info_item`` to dedupe.
    """
    body = await _get_json(
        client_facade,
        "/api/v1/tools/find-info-items",
        params={"q": query, "limit": limit},
    )
    return [InfoItemOut.from_dict(item) for item in body]


@dataclass(frozen=True)
class FetchAndRenderResult:
    """Outcome of a ``fetch_and_render`` call."""

    url: str
    status_code: int
    headers: dict[str, str]
    body: str
    body_bytes_total: int
    truncated: bool
    screenshot_url: str | None


async def fetch_and_render(
    client_facade: ArchiverClient, url: str, *, render: bool = False
) -> FetchAndRenderResult:
    """Fetch ``url`` and return body + headers.

    ``render=True`` raises ``ArchiverClientError`` (501) until #3 lands.
    Body bytes larger than 5 MiB are truncated server-side; check
    ``truncated`` and ``body_bytes_total`` to detect.
    """
    body = await _post_json(
        client_facade,
        "/api/v1/tools/fetch-and-render",
        {"url": url, "render": render},
    )
    return FetchAndRenderResult(
        url=str(body["url"]),
        status_code=int(body["status_code"]),
        headers=dict(body.get("headers") or {}),
        body=str(body["body"]),
        body_bytes_total=int(body["body_bytes_total"]),
        truncated=bool(body["truncated"]),
        screenshot_url=body.get("screenshot_url"),
    )


@dataclass(frozen=True)
class SelectorCandidate:
    """One ranked selector candidate from ``propose_selectors``."""

    selector: str
    sample_text: str
    stability_score: float


async def propose_selectors(
    client_facade: ArchiverClient,
    url: str,
    description: str,
    *,
    top_k: int = 5,
) -> list[SelectorCandidate]:
    """Return ranked selector candidates for ``description`` on ``url``.

    Empty match set returns ``[]``. Always pair with ``preview_extraction``
    against the chosen candidate before persisting a SourceSpec.
    """
    body = await _post_json(
        client_facade,
        "/api/v1/tools/propose-selectors",
        {"url": url, "description": description, "top_k": top_k},
    )
    return [
        SelectorCandidate(
            selector=str(c["selector"]),
            sample_text=str(c["sample_text"]),
            stability_score=float(c["stability_score"]),
        )
        for c in body
    ]


@dataclass(frozen=True)
class ChunkPreview:
    """Per-chunk preview entry from ``preview_extraction``."""

    index: int
    chunk_type: str
    label: str
    text: str
    char_count: int


@dataclass(frozen=True)
class PreviewExtractionResult:
    """Outcome of a ``preview_extraction`` call."""

    chunks: list[ChunkPreview]
    total_chars: int
    fingerprint_algorithm: str
    computed_fingerprint: str


async def preview_extraction(
    client_facade: ArchiverClient,
    source_spec: dict[str, Any],
) -> PreviewExtractionResult:
    """Validate, fetch, extract, and fingerprint with a candidate SourceSpec.

    Accepts a SourceSpec document dict (v2 shape). On schema validation failure
    or target unreachability, the underlying HTTPException is surfaced as an
    ``ArchiverClientError`` subclass with the structured ``detail`` body intact.
    """
    body = await _post_json(
        client_facade,
        "/api/v1/tools/preview-extraction",
        {"source_spec": source_spec},
    )
    return PreviewExtractionResult(
        chunks=[
            ChunkPreview(
                index=int(c["index"]),
                chunk_type=str(c["chunk_type"]),
                label=str(c["label"]),
                text=str(c["text"]),
                char_count=int(c["char_count"]),
            )
            for c in body.get("chunks", [])
        ],
        total_chars=int(body["total_chars"]),
        fingerprint_algorithm=str(body["fingerprint_algorithm"]),
        computed_fingerprint=str(body["computed_fingerprint"]),
    )
