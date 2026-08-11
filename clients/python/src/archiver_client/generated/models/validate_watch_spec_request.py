from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.validate_watch_spec_request_document import ValidateWatchSpecRequestDocument


T = TypeVar("T", bound="ValidateWatchSpecRequest")


@_attrs_define
class ValidateWatchSpecRequest:
    """Request body for POST /api/v1/tools/validate-watch-spec.

    Attributes:
        document (ValidateWatchSpecRequestDocument): The WatchSpec document to validate against the v1 JSON Schema.
    """

    document: ValidateWatchSpecRequestDocument
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        document = self.document.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "document": document,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.validate_watch_spec_request_document import ValidateWatchSpecRequestDocument

        d = dict(src_dict)
        document = ValidateWatchSpecRequestDocument.from_dict(d.pop("document"))

        validate_watch_spec_request = cls(
            document=document,
        )

        validate_watch_spec_request.additional_properties = d
        return validate_watch_spec_request

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
