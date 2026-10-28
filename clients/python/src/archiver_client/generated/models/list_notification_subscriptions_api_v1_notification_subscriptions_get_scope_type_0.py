from enum import Enum


class ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0(str, Enum):
    DOMAIN = "domain"
    GLOBAL = "global"
    ITEM = "item"

    def __str__(self) -> str:
        return str(self.value)
