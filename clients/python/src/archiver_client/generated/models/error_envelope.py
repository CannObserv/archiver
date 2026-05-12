from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.error_envelope_kind import ErrorEnvelopeKind
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.error_envelope_data_type_0 import ErrorEnvelopeDataType0
    from ..models.field_error import FieldError


T = TypeVar("T", bound="ErrorEnvelope")


@_attrs_define
class ErrorEnvelope:
    """Unified error response body.

    Attributes:
        kind (ErrorEnvelopeKind): Discriminator for client-side switching.
        message (str): Human-readable summary; safe to surface to users.
        data (ErrorEnvelopeDataType0 | None | Unset): Optional kind-specific structured payload (e.g. conflict id).
        errors (list[FieldError] | Unset): Field-level problems; empty list when none apply.
    """

    kind: ErrorEnvelopeKind
    message: str
    data: ErrorEnvelopeDataType0 | None | Unset = UNSET
    errors: list[FieldError] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.error_envelope_data_type_0 import ErrorEnvelopeDataType0

        kind = self.kind.value

        message = self.message

        data: dict[str, Any] | None | Unset
        if isinstance(self.data, Unset):
            data = UNSET
        elif isinstance(self.data, ErrorEnvelopeDataType0):
            data = self.data.to_dict()
        else:
            data = self.data

        errors: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.errors, Unset):
            errors = []
            for errors_item_data in self.errors:
                errors_item = errors_item_data.to_dict()
                errors.append(errors_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
                "message": message,
            }
        )
        if data is not UNSET:
            field_dict["data"] = data
        if errors is not UNSET:
            field_dict["errors"] = errors

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.error_envelope_data_type_0 import ErrorEnvelopeDataType0
        from ..models.field_error import FieldError

        d = dict(src_dict)
        kind = ErrorEnvelopeKind(d.pop("kind"))

        message = d.pop("message")

        def _parse_data(data: object) -> ErrorEnvelopeDataType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                data_type_0 = ErrorEnvelopeDataType0.from_dict(data)

                return data_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ErrorEnvelopeDataType0 | None | Unset, data)

        data = _parse_data(d.pop("data", UNSET))

        _errors = d.pop("errors", UNSET)
        errors: list[FieldError] | Unset = UNSET
        if _errors is not UNSET:
            errors = []
            for errors_item_data in _errors:
                errors_item = FieldError.from_dict(errors_item_data)

                errors.append(errors_item)

        error_envelope = cls(
            kind=kind,
            message=message,
            data=data,
            errors=errors,
        )

        return error_envelope
