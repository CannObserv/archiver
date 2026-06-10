from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="ProbeResponse")


@_attrs_define
class ProbeResponse:
    """Output schema for the probe endpoint.

    Attributes:
        effective_url (str):
        effective_domain (str):
        redirect_chain (list[str]):
        status_code (int):
        content_type (None | str):
    """

    effective_url: str
    effective_domain: str
    redirect_chain: list[str]
    status_code: int
    content_type: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        effective_url = self.effective_url

        effective_domain = self.effective_domain

        redirect_chain = self.redirect_chain

        status_code = self.status_code

        content_type: None | str
        content_type = self.content_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "effective_url": effective_url,
                "effective_domain": effective_domain,
                "redirect_chain": redirect_chain,
                "status_code": status_code,
                "content_type": content_type,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        effective_url = d.pop("effective_url")

        effective_domain = d.pop("effective_domain")

        redirect_chain = cast(list[str], d.pop("redirect_chain"))

        status_code = d.pop("status_code")

        def _parse_content_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        content_type = _parse_content_type(d.pop("content_type"))

        probe_response = cls(
            effective_url=effective_url,
            effective_domain=effective_domain,
            redirect_chain=redirect_chain,
            status_code=status_code,
            content_type=content_type,
        )

        probe_response.additional_properties = d
        return probe_response

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
