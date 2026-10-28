from enum import Enum


class NotificationSubscriptionCreateScope(str, Enum):
    DOMAIN = "domain"
    GLOBAL = "global"
    ITEM = "item"

    def __str__(self) -> str:
        return str(self.value)
