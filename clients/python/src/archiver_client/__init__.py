"""archiver-client — async Python SDK for the Archiver service.

Versioned independently of the Archiver service. See README for usage.
"""

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _dist_version

from archiver_client.client import ArchiverClient
from archiver_client.defaults import (
    DEFAULT_FETCH_RENDER,
    DEFAULT_FETCH_TIMEOUT_SECONDS,
    fetch_render,
    fetch_timeout_seconds,
)
from archiver_client.errors import (
    AuthError,
    Conflict,
    InformationError,
    NotFound,
    ServerError,
    ValidationError,
)
from archiver_client.generated.models.field_error import FieldError
from archiver_client.generated.models.info_item_out import InfoItemOut
from archiver_client.generated.models.info_item_rep_spec_out import InfoItemRepSpecOut
from archiver_client.generated.models.info_item_source_out import InfoItemSourceOut
from archiver_client.generated.models.info_source_out import InfoSourceOut
from archiver_client.generated.models.page_info_item_out import PageInfoItemOut
from archiver_client.generated.models.page_info_source_out import PageInfoSourceOut
from archiver_client.generated.models.page_rep_spec_out import PageRepSpecOut
from archiver_client.generated.models.rep_spec_out import RepSpecOut
from archiver_client.generated.models.source_revision_out import SourceRevisionOut
from archiver_client.tools import ValidationResult

# Read from the installed distribution, never a literal: a literal sat at 5.0.0
# through seven SDK releases (archiver#248).
try:
    __version__ = _dist_version("archiver-client")
except _PackageNotFoundError:  # pragma: no cover - source tree without an install
    __version__ = "0+unknown"

__all__ = [
    "ArchiverClient",
    "AuthError",
    "Conflict",
    "DEFAULT_FETCH_RENDER",
    "DEFAULT_FETCH_TIMEOUT_SECONDS",
    "FieldError",
    "InfoItemOut",
    "InfoItemRepSpecOut",
    "InfoItemSourceOut",
    "InfoSourceOut",
    "InformationError",
    "NotFound",
    "PageInfoItemOut",
    "PageInfoSourceOut",
    "PageRepSpecOut",
    "RepSpecOut",
    "ServerError",
    "SourceRevisionOut",
    "ValidationError",
    "ValidationResult",
    "fetch_render",
    "fetch_timeout_seconds",
]
