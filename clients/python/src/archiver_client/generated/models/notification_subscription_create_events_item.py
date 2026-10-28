from enum import Enum


class NotificationSubscriptionCreateEventsItem(str, Enum):
    CHANGE_DETECTED = "change_detected"
    WATCH_ERROR = "watch_error"
    WATCH_RECOVERED = "watch_recovered"

    def __str__(self) -> str:
        return str(self.value)
