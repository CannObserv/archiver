from enum import Enum


class InfoItemSourceCreateRoleType0(str, Enum):
    CROSS_CHECK = "cross_check"
    SUB_ASPECT = "sub_aspect"

    def __str__(self) -> str:
        return str(self.value)
