from enum import Enum


class WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode(str, Enum):
    EDIT = "edit"
    VIEW = "view"

    def __str__(self) -> str:
        return str(self.value)
