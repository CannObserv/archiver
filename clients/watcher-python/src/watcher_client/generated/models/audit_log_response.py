from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.audit_log_response_payload import AuditLogResponsePayload


T = TypeVar("T", bound="AuditLogResponse")


@_attrs_define
class AuditLogResponse:
    """Response schema for an audit log entry.

    Attributes:
        id (str):
        event_type (str):
        payload (AuditLogResponsePayload):
        created_at (datetime.datetime):
    """

    id: str
    event_type: str
    payload: AuditLogResponsePayload
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        event_type = self.event_type

        payload = self.payload.to_dict()

        created_at = self.created_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "event_type": event_type,
                "payload": payload,
                "created_at": created_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.audit_log_response_payload import AuditLogResponsePayload

        d = dict(src_dict)
        id = d.pop("id")

        event_type = d.pop("event_type")

        payload = AuditLogResponsePayload.from_dict(d.pop("payload"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        audit_log_response = cls(
            id=id,
            event_type=event_type,
            payload=payload,
            created_at=created_at,
        )

        audit_log_response.additional_properties = d
        return audit_log_response

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
