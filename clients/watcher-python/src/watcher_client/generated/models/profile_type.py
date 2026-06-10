from enum import Enum


class ProfileType(str, Enum):
    DEADLINE = "deadline"
    EVENT = "event"
    SEASONAL = "seasonal"

    def __str__(self) -> str:
        return str(self.value)
