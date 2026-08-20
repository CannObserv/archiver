from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.error_envelope import ErrorEnvelope


T = TypeVar("T", bound="EnvelopeResponse")


@_attrs_define
class EnvelopeResponse:
    """Outer ``{"detail": ErrorEnvelope}`` wrapper for OpenAPI docs.

    Public name (no leading underscore) so ``openapi-python-client`` generates a
    cleanly-named SDK model - the class name is what surfaces in
    ``components/schemas`` and feeds the SDK code generator.

        Attributes:
            detail (ErrorEnvelope): Unified error response body.
    """

    detail: ErrorEnvelope
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        detail = self.detail.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "detail": detail,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.error_envelope import ErrorEnvelope

        d = dict(src_dict)
        detail = ErrorEnvelope.from_dict(d.pop("detail"))

        envelope_response = cls(
            detail=detail,
        )

        envelope_response.additional_properties = d
        return envelope_response

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
