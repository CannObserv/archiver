from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.resolve_rep_fields_response_bag import ResolveRepFieldsResponseBag


T = TypeVar("T", bound="ResolveRepFieldsResponse")


@_attrs_define
class ResolveRepFieldsResponse:
    """Response body for POST /api/v1/tools/resolve-rep-fields.

    Attributes:
        bag (ResolveRepFieldsResponseBag): The slug-enriched bag after resolution.
    """

    bag: ResolveRepFieldsResponseBag
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        bag = self.bag.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "bag": bag,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.resolve_rep_fields_response_bag import ResolveRepFieldsResponseBag

        d = dict(src_dict)
        bag = ResolveRepFieldsResponseBag.from_dict(d.pop("bag"))

        resolve_rep_fields_response = cls(
            bag=bag,
        )

        resolve_rep_fields_response.additional_properties = d
        return resolve_rep_fields_response

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
