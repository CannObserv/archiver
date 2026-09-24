from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="RearmOutboxRowsRequest")


@_attrs_define
class RearmOutboxRowsRequest:
    """Request body for POST /api/v1/tools/outbox/dead-lettered/rearm.

    Attributes:
        row_ids (list[str]): Dead-lettered row ids to return to the drain's queue. Fix the cause first: a rearmed row
            that fails the same way dead-letters again.
    """

    row_ids: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        row_ids = self.row_ids

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "row_ids": row_ids,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        row_ids = cast(list[str], d.pop("row_ids"))

        rearm_outbox_rows_request = cls(
            row_ids=row_ids,
        )

        rearm_outbox_rows_request.additional_properties = d
        return rearm_outbox_rows_request

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
