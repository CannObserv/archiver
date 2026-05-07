"""archiver-client — async Python SDK for the Archiver service.

Pinned 1:1 with Archiver service version. See README for usage.
"""

from archiver_client.client import ArchiverClient
from archiver_client.defaults import (
    DEFAULT_FETCH_RENDER,
    DEFAULT_FETCH_TIMEOUT_SECONDS,
    fetch_render,
    fetch_timeout_seconds,
)
from archiver_client.errors import (
    AuthError,
    InformationError,
    NotFound,
    ServerError,
    ValidationError,
)
from archiver_client.generated.models.info_item_out import InfoItemOut
from archiver_client.generated.models.info_spec_out import InfoSpecOut

__version__ = "0.1.0"

__all__ = [
    "AuthError",
    "DEFAULT_FETCH_RENDER",
    "DEFAULT_FETCH_TIMEOUT_SECONDS",
    "InfoItemOut",
    "InfoSpecOut",
    "ArchiverClient",
    "InformationError",
    "NotFound",
    "ServerError",
    "ValidationError",
    "fetch_render",
    "fetch_timeout_seconds",
]
