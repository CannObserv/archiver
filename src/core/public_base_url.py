"""Where a link to this Archiver points: ``ARCHIVER_PUBLIC_BASE_URL``, an origin (archiver#367).

The base is the origin people open in a browser (``https://co-registrar.exe.xyz``),
and an item's page is ``/dashboard/info-items/{id}`` under it. The API's
``dashboard_url`` and a notification's ``app_url``/``change_url`` both come from
here, so they cannot disagree.

**Unset or unusable means no link** (Watcher's #296 D6 rule): a relative link is
useless in Slack or email, and a guessed host points readers at the wrong
deployment. Only ``http(s)://host[:port]`` is used. A path is refused because it
would double up with ``/dashboard``.
"""

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

PUBLIC_BASE_URL_ENV = "ARCHIVER_PUBLIC_BASE_URL"


def public_base_url(environ: Mapping[str, str] = os.environ) -> str | None:
    """The configured origin without a trailing slash, or ``None``. Never raises."""
    value = environ.get(PUBLIC_BASE_URL_ENV, "").strip().rstrip("/")
    if not value:
        return None
    try:
        parts = urlsplit(value)
        origin = (
            parts.scheme in {"http", "https"}
            and bool(parts.hostname)
            and "@" not in parts.netloc
            and not (parts.path or parts.query or parts.fragment)
            and (parts.port is None or parts.port > 0)  # .port raises on a malformed one
        )
    except ValueError:
        return None
    return value if origin else None


def item_page_url(base: str, info_item_id: str) -> str:
    """The item's dashboard page under ``base`` (from :func:`public_base_url`)."""
    return f"{base}/dashboard/info-items/{info_item_id}"
