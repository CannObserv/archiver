"""URL canonicalization for InfoSource.url storage and lookup.

Applied at write time before persisting to info_sources. Keeps the UNIQUE(url)
constraint coherent and prevents duplicate sources for cosmetically-different URLs.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonicalize_url(url: str, *, strip_query_keys: list[str] | None = None) -> str:
    """Return canonical form of `url`.

    - Strips #fragment.
    - Lowercases scheme + host.
    - Collapses duplicate path slashes (preserves single trailing slash).
    - Optionally drops query-string keys named in strip_query_keys.

    Raises ValueError on a URL with no scheme or host.
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"URL must have scheme and host: {url!r}")

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()

    # collapse duplicate slashes in path (keep single trailing slash if present)
    path_segments = [seg for seg in parts.path.split("/") if seg != ""]
    canonical_path = "/" + "/".join(path_segments)
    if parts.path.endswith("/") and canonical_path != "/":
        canonical_path += "/"

    query = parts.query
    if strip_query_keys:
        keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k not in strip_query_keys]
        query = urlencode(keep)

    return urlunsplit((scheme, netloc, canonical_path, query, ""))
