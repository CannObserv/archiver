from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

T = TypeVar("T", bound="InfoItemRepSpecOut")


@_attrs_define
class InfoItemRepSpecOut:
    """Projection of an info_item_rep_specs row.

    Attributes:
        activated_at (datetime.datetime):
        deactivated_at (datetime.datetime | None):
        id (str):
        public_url (None | str):
        rep_spec_id (str):
    """

    activated_at: datetime.datetime
    deactivated_at: datetime.datetime | None
    id: str
    public_url: None | str
    rep_spec_id: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        activated_at = self.activated_at.isoformat()

        deactivated_at: None | str
        if isinstance(self.deactivated_at, datetime.datetime):
            deactivated_at = self.deactivated_at.isoformat()
        else:
            deactivated_at = self.deactivated_at

        id = self.id

        public_url: None | str
        public_url = self.public_url

        rep_spec_id = self.rep_spec_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "activated_at": activated_at,
                "deactivated_at": deactivated_at,
                "id": id,
                "public_url": public_url,
                "rep_spec_id": rep_spec_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        activated_at = isoparse(d.pop("activated_at"))

        def _parse_deactivated_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                deactivated_at_type_0 = isoparse(data)

                return deactivated_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        deactivated_at = _parse_deactivated_at(d.pop("deactivated_at"))

        id = d.pop("id")

        def _parse_public_url(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        public_url = _parse_public_url(d.pop("public_url"))

        rep_spec_id = d.pop("rep_spec_id")

        info_item_rep_spec_out = cls(
            activated_at=activated_at,
            deactivated_at=deactivated_at,
            id=id,
            public_url=public_url,
            rep_spec_id=rep_spec_id,
        )

        info_item_rep_spec_out.additional_properties = d
        return info_item_rep_spec_out

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
