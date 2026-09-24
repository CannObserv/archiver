from enum import Enum


class ReprocessResultOutOutcome(str, Enum):
    DEFERRED = "deferred"
    FAILED = "failed"
    NOT_FOUND = "not_found"
    NOT_OWNED = "not_owned"
    REJECTED = "rejected"
    REPROCESSED = "reprocessed"
    UNDECODABLE = "undecodable"

    def __str__(self) -> str:
        return str(self.value)
