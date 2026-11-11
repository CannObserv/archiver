from enum import Enum


class CaptureWaitPolicyKind(str, Enum):
    DELAY = "delay"
    NETWORKIDLE = "networkidle"
    SELECTOR = "selector"

    def __str__(self) -> str:
        return str(self.value)
