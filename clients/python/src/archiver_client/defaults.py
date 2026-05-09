"""Default values for optional ``target.fetch`` fields on a SourceSpec document.

The v1 SourceSpec JSON Schema deliberately omits ``default:`` keys because
``Draft202012Validator`` does not inject defaults during validation.
Consumers that read a SourceSpec document apply these constants when the
optional fields are absent.

These are *consumer* defaults — the Archiver service itself stores
documents verbatim, never injecting these values.
"""

DEFAULT_FETCH_RENDER: bool = False
"""Whether the consumer should render JS when fetching the target URL."""

DEFAULT_FETCH_TIMEOUT_SECONDS: int = 30
"""HTTP timeout (seconds) the consumer should apply when fetching the target."""


def fetch_render(document: dict) -> bool:
    """Resolve ``target.fetch.render`` from a SourceSpec document, or default."""
    fetch = (document.get("target") or {}).get("fetch") or {}
    value = fetch.get("render")
    return DEFAULT_FETCH_RENDER if value is None else bool(value)


def fetch_timeout_seconds(document: dict) -> int:
    """Resolve ``target.fetch.timeout_seconds`` from a SourceSpec document, or default."""
    fetch = (document.get("target") or {}).get("fetch") or {}
    value = fetch.get("timeout_seconds")
    return DEFAULT_FETCH_TIMEOUT_SECONDS if value is None else int(value)
