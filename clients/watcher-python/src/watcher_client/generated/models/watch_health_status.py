from enum import Enum


class WatchHealthStatus(str, Enum):
    ERROR = "error"
    OK = "ok"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return str(self.value)
