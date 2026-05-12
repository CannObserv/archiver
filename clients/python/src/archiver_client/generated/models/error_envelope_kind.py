from enum import Enum


class ErrorEnvelopeKind(str, Enum):
    AUTH = "auth"
    BODY = "body"
    CONFLICT = "conflict"
    DOMAIN = "domain"
    LOOKUP = "lookup"
    SCHEMA = "schema"
    SERVER = "server"
    UNIMPLEMENTED = "unimplemented"

    def __str__(self) -> str:
        return str(self.value)
