from enum import Enum


class NotificationSubscriptionOutScope(str, Enum):
    DOMAIN = "domain"
    GLOBAL = "global"
    ITEM = "item"

    def __str__(self) -> str:
        return str(self.value)
