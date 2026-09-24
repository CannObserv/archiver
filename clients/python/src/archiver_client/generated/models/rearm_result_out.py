from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.rearm_result_out_outcome import RearmResultOutOutcome

T = TypeVar("T", bound="RearmResultOut")


@_attrs_define
class RearmResultOut:
    """What happened to one requested row. Only `rearmed` changed it.

    Attributes:
        detail (None | str): Why it stayed; null when it did not.
        outcome (RearmResultOutOutcome): `rearmed`: back in the drain's queue, attempts reset. `not_found`: not a dead-
            lettered row. `refused`: its topic is not rearmable - discard it. `rejected`: its payload still does not build
            against the running co-core - discard it.
        row_id (str):
    """

    detail: None | str
    outcome: RearmResultOutOutcome
    row_id: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        detail: None | str
        detail = self.detail

        outcome = self.outcome.value

        row_id = self.row_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "detail": detail,
                "outcome": outcome,
                "row_id": row_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_detail(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        detail = _parse_detail(d.pop("detail"))

        outcome = RearmResultOutOutcome(d.pop("outcome"))

        row_id = d.pop("row_id")

        rearm_result_out = cls(
            detail=detail,
            outcome=outcome,
            row_id=row_id,
        )

        rearm_result_out.additional_properties = d
        return rearm_result_out

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
