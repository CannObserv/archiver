from enum import Enum


class DeadLetterOutParkedAsType0(str, Enum):
    HANDLER_POISON = "handler_poison"
    UNDECODABLE = "undecodable"

    def __str__(self) -> str:
        return str(self.value)
