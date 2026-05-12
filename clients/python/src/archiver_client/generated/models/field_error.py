from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="FieldError")


@_attrs_define
class FieldError:
    """Single field-level validation problem.

    Attributes:
        message (str): Human-readable error message.
        path (str): JSON-Pointer style path to the offending field.
        code (None | str | Unset): Optional short machine-readable token (e.g. 'required').
    """

    message: str
    path: str
    code: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        message = self.message

        path = self.path

        code: None | str | Unset
        if isinstance(self.code, Unset):
            code = UNSET
        else:
            code = self.code

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "message": message,
                "path": path,
            }
        )
        if code is not UNSET:
            field_dict["code"] = code

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        message = d.pop("message")

        path = d.pop("path")

        def _parse_code(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        code = _parse_code(d.pop("code", UNSET))

        field_error = cls(
            message=message,
            path=path,
            code=code,
        )

        return field_error
