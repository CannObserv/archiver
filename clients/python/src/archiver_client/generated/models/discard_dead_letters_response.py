from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="DiscardDeadLettersResponse")


@_attrs_define
class DiscardDeadLettersResponse:
    """Response body for POST /api/v1/tools/dead-letters/{dlq}/discard.

    Attributes:
        discarded (list[str]): Ids deleted, each logged in full to journald first.
        not_found (list[str]): Ids that were not in the queue.
    """

    discarded: list[str]
    not_found: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        discarded = self.discarded

        not_found = self.not_found

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "discarded": discarded,
                "not_found": not_found,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        discarded = cast(list[str], d.pop("discarded"))

        not_found = cast(list[str], d.pop("not_found"))

        discard_dead_letters_response = cls(
            discarded=discarded,
            not_found=not_found,
        )

        discard_dead_letters_response.additional_properties = d
        return discard_dead_letters_response

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
