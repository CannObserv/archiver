"""watcher-client — async Python SDK for the Watcher service (Archiver adapter layer)."""

from watcher_client.client import WatcherClient
from watcher_client.errors import (
    WatcherAuthError,
    WatcherConflict,
    WatcherError,
    WatcherNotFound,
    WatcherServerError,
    WatcherValidationError,
)
from watcher_client.generated.models.change_revision_response import ChangeRevisionResponse
from watcher_client.generated.models.watch_health_status import WatchHealthStatus
from watcher_client.generated.models.watched_item_response import WatchedItemResponse

__version__ = "1.2.0"

__all__ = [
    "ChangeRevisionResponse",
    "WatcherAuthError",
    "WatcherClient",
    "WatcherConflict",
    "WatcherError",
    "WatcherNotFound",
    "WatcherServerError",
    "WatcherValidationError",
    "WatchHealthStatus",
    "WatchedItemResponse",
]
