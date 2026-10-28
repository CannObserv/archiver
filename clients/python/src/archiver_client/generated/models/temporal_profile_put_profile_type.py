from enum import Enum


class TemporalProfilePutProfileType(str, Enum):
    DEADLINE = "deadline"
    EVENT = "event"
    SEASONAL = "seasonal"

    def __str__(self) -> str:
        return str(self.value)
