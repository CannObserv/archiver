from enum import Enum


class RearmResultOutOutcome(str, Enum):
    NOT_FOUND = "not_found"
    REARMED = "rearmed"
    REFUSED = "refused"
    REJECTED = "rejected"

    def __str__(self) -> str:
        return str(self.value)
