from enum import Enum


class PostAction(str, Enum):
    ARCHIVE = "archive"
    DEACTIVATE = "deactivate"
    REDUCE_FREQUENCY = "reduce_frequency"

    def __str__(self) -> str:
        return str(self.value)
