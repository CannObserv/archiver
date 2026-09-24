from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.reprocess_result_out import ReprocessResultOut


T = TypeVar("T", bound="ReprocessDeadLettersResponse")


@_attrs_define
class ReprocessDeadLettersResponse:
    """Response body for POST /api/v1/tools/dead-letters/{dlq}/reprocess.

    Attributes:
        results (list[ReprocessResultOut]): One per distinct id, in request order.
    """

    results: list[ReprocessResultOut]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        results = []
        for results_item_data in self.results:
            results_item = results_item_data.to_dict()
            results.append(results_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "results": results,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.reprocess_result_out import ReprocessResultOut

        d = dict(src_dict)
        results = []
        _results = d.pop("results")
        for results_item_data in _results:
            results_item = ReprocessResultOut.from_dict(results_item_data)

            results.append(results_item)

        reprocess_dead_letters_response = cls(
            results=results,
        )

        reprocess_dead_letters_response.additional_properties = d
        return reprocess_dead_letters_response

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
