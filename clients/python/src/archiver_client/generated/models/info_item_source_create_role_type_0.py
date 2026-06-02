from enum import Enum


class InfoItemSourceCreateRoleType0(str, Enum):
    CROSS_CHECK = "cross_check"

    def __str__(self) -> str:
        return str(self.value)
