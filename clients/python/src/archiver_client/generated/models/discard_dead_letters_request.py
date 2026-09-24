from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="DiscardDeadLettersRequest")


@_attrs_define
class DiscardDeadLettersRequest:
    """Request body for POST /api/v1/tools/dead-letters/{dlq}/discard.

    Attributes:
        entry_ids (list[str]): Exact stream ids (`<ms>-<seq>`) to delete. A range or bare timestamp is refused: XRANGE
            would read it as more entries than were named.
    """

    entry_ids: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        entry_ids = self.entry_ids

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "entry_ids": entry_ids,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        entry_ids = cast(list[str], d.pop("entry_ids"))

        discard_dead_letters_request = cls(
            entry_ids=entry_ids,
        )

        discard_dead_letters_request.additional_properties = d
        return discard_dead_letters_request

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
