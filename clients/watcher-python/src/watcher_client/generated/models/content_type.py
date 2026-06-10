from enum import Enum


class ContentType(str, Enum):
    FILE = "file"
    HTML = "html"
    PDF = "pdf"

    def __str__(self) -> str:
        return str(self.value)
