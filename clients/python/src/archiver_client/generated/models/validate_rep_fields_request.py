from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.validate_rep_fields_request_bag import ValidateRepFieldsRequestBag


T = TypeVar("T", bound="ValidateRepFieldsRequest")


@_attrs_define
class ValidateRepFieldsRequest:
    """Request body for POST /api/v1/tools/validate-rep-fields.

    Attributes:
        bag (ValidateRepFieldsRequestBag): The rep_fields bag to validate.
        required_fields (list[str] | None | Unset): Optional list of 'ns.key' paths that must be present and non-null.
            When omitted, only the bag's shape is validated.
    """

    bag: ValidateRepFieldsRequestBag
    required_fields: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        bag = self.bag.to_dict()

        required_fields: list[str] | None | Unset
        if isinstance(self.required_fields, Unset):
            required_fields = UNSET
        elif isinstance(self.required_fields, list):
            required_fields = self.required_fields

        else:
            required_fields = self.required_fields

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "bag": bag,
            }
        )
        if required_fields is not UNSET:
            field_dict["required_fields"] = required_fields

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.validate_rep_fields_request_bag import ValidateRepFieldsRequestBag

        d = dict(src_dict)
        bag = ValidateRepFieldsRequestBag.from_dict(d.pop("bag"))

        def _parse_required_fields(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                required_fields_type_0 = cast(list[str], data)

                return required_fields_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        required_fields = _parse_required_fields(d.pop("required_fields", UNSET))

        validate_rep_fields_request = cls(
            bag=bag,
            required_fields=required_fields,
        )

        validate_rep_fields_request.additional_properties = d
        return validate_rep_fields_request

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
